"""Boot integrity verification via HMAC-signed manifest.

Generates and verifies a .yopj.manifest file containing SHA-256 hashes
of trust root files. HMAC key derived from operator passphrase via PBKDF2.
Protects against pre-boot tampering by co-resident agents (Co-Residency
Threat Model v1.1, Section 6).
"""

import getpass
import hashlib
import hmac as hmac_mod
import json
import os
import sys
from datetime import datetime, timezone


# PBKDF2 parameters (OWASP 2023 recommendation for SHA-256)
PBKDF2_ITERATIONS = 600_000
PBKDF2_SALT_LENGTH = 32
PBKDF2_KEY_LENGTH = 32

MANIFEST_FILENAME = ".yopj.manifest"

# Trust root tiers. Tier 1-2 mismatch = ABORT. Tier 3-4 = WARN.
TRUST_TIERS = {
    1: {
        "label": "Security Core",
        "files": [
            "core/sandbox.py",
            "core/tool_protocol.py",
            "core/permission_system.py",
        ],
    },
    2: {
        "label": "Boot Path",
        "files": [
            "yopj.py",
            "core/config.py",
            "core/plugin_loader.py",
            "core/integrity.py",
            "core/path_registry.py",
            "core/server_trust.py",
        ],
    },
    3: {
        "label": "Runtime",
        "files": [
            "core/server_interface.py",
            "core/model_interface.py",
            "core/context_manager.py",
            "core/audit_log.py",
            "core/chat_templates.py",
            "core/project_detect.py",
        ],
    },
    4: {
        "label": "Tools",
        "files": [
            "tools/bash_exec.py",
            "tools/file_read.py",
            "tools/file_write.py",
            "tools/file_edit.py",
            "tools/git_tools.py",
            "tools/grep_search.py",
            "tools/glob_search.py",
        ],
    },
}

# Directories to scan for unexpected files
SECURITY_DIRS = ["core", "tools"]


class ManifestError(Exception):
    """Raised on manifest generation or verification failure."""
    pass


class IntegrityVerifier:
    """Generates and verifies HMAC-signed boot integrity manifests."""

    def __init__(self, base_dir: str):
        self.base_dir = os.path.realpath(base_dir)
        self.manifest_path = os.path.join(self.base_dir, MANIFEST_FILENAME)

    def generate_manifest(self, passphrase: str = None) -> str:
        """Generate HMAC-signed manifest and write to disk.

        Args:
            passphrase: Signing passphrase. If None, prompts interactively.

        Returns:
            Path to the written manifest file.

        Raises:
            ManifestError: If passphrases don't match or other generation error.
        """
        if passphrase is None:
            passphrase = getpass.getpass("Manifest signing passphrase: ")
            confirm = getpass.getpass("Confirm passphrase: ")
            if passphrase != confirm:
                raise ManifestError("Passphrases do not match.")
            if not passphrase:
                raise ManifestError("Passphrase cannot be empty.")

        # Generate random salt
        salt = os.urandom(PBKDF2_SALT_LENGTH)

        # Derive HMAC key from passphrase
        key = hashlib.pbkdf2_hmac(
            "sha256",
            passphrase.encode("utf-8"),
            salt,
            PBKDF2_ITERATIONS,
            dklen=PBKDF2_KEY_LENGTH,
        )

        # Hash all trust root files
        file_entries = {}
        for tier_num, tier_info in sorted(TRUST_TIERS.items()):
            for relpath in tier_info["files"]:
                abspath = os.path.join(self.base_dir, relpath)
                if os.path.exists(abspath):
                    file_entries[relpath] = {
                        "sha256": _hash_file(abspath),
                        "tier": tier_num,
                        "size": os.path.getsize(abspath),
                    }
                else:
                    file_entries[relpath] = {
                        "sha256": None,
                        "tier": tier_num,
                        "missing": True,
                    }

        # Build manifest payload (without HMAC — HMAC computed over this)
        manifest = {
            "manifest_version": "1.0",
            "created": datetime.now(timezone.utc).isoformat(),
            "algorithm": "sha256",
            "pbkdf2_iterations": PBKDF2_ITERATIONS,
            "salt": salt.hex(),
            "files": file_entries,
        }

        # Compute HMAC over canonical JSON
        payload_bytes = _canonical_json(manifest)
        mac = hmac_mod.new(key, payload_bytes, hashlib.sha256).hexdigest()
        manifest["hmac"] = mac

        # Write manifest
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)

        return self.manifest_path

    def verify(self, passphrase: str = None) -> dict:
        """Verify manifest HMAC and all file hashes.

        Args:
            passphrase: Signing passphrase. If None, prompts interactively.

        Returns:
            dict with:
                ok (bool): True if no ABORT-level failures
                abort (bool): True if Tier 1-2 mismatch or HMAC failure
                errors (list[str]): ABORT-level messages
                warnings (list[str]): WARN-level messages
        """
        result = {"ok": True, "abort": False, "errors": [], "warnings": []}

        # Load manifest
        if not os.path.exists(self.manifest_path):
            result["warnings"].append(
                "No integrity manifest found. "
                "Use --generate-manifest to create one."
            )
            return result

        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            result["ok"] = False
            result["abort"] = True
            result["errors"].append(f"Cannot read manifest: {e}")
            return result

        # Prompt for passphrase
        if passphrase is None:
            passphrase = getpass.getpass("Manifest passphrase: ")

        # Derive key from stored salt
        try:
            salt = bytes.fromhex(manifest["salt"])
        except (KeyError, ValueError) as e:
            result["ok"] = False
            result["abort"] = True
            result["errors"].append(f"Invalid manifest format (salt): {e}")
            return result

        iterations = manifest.get("pbkdf2_iterations", PBKDF2_ITERATIONS)
        key = hashlib.pbkdf2_hmac(
            "sha256",
            passphrase.encode("utf-8"),
            salt,
            iterations,
            dklen=PBKDF2_KEY_LENGTH,
        )

        # Verify HMAC
        stored_hmac = manifest.get("hmac")
        if not stored_hmac:
            result["ok"] = False
            result["abort"] = True
            result["errors"].append("Manifest has no HMAC signature.")
            return result

        # Remove HMAC for verification payload
        manifest_copy = {k: v for k, v in manifest.items() if k != "hmac"}
        payload_bytes = _canonical_json(manifest_copy)
        expected_mac = hmac_mod.new(key, payload_bytes, hashlib.sha256).hexdigest()

        if not hmac_mod.compare_digest(stored_hmac, expected_mac):
            result["ok"] = False
            result["abort"] = True
            result["errors"].append(
                "HMAC verification FAILED — manifest has been tampered with "
                "or passphrase is incorrect."
            )
            return result

        # HMAC valid — now check individual file hashes
        for relpath, info in manifest.get("files", {}).items():
            tier = info.get("tier", 99)
            expected_hash = info.get("sha256")
            abspath = os.path.join(self.base_dir, relpath)

            if info.get("missing"):
                # File was missing at generation time
                if os.path.exists(abspath):
                    msg = f"File appeared since manifest was created: {relpath} (Tier {tier})"
                    if tier <= 2:
                        result["errors"].append(msg)
                        result["abort"] = True
                        result["ok"] = False
                    else:
                        result["warnings"].append(msg)
                continue

            if not os.path.exists(abspath):
                msg = f"Missing trust root file: {relpath} (Tier {tier})"
                if tier <= 2:
                    result["errors"].append(msg)
                    result["abort"] = True
                    result["ok"] = False
                else:
                    result["warnings"].append(msg)
                continue

            actual_hash = _hash_file(abspath)
            if actual_hash != expected_hash:
                msg = f"TAMPERED: {relpath} (Tier {tier} — {_tier_label(tier)})"
                if tier <= 2:
                    result["errors"].append(msg)
                    result["abort"] = True
                    result["ok"] = False
                else:
                    result["warnings"].append(msg)

        # Check for unknown .py files in security directories
        known_files = set(manifest.get("files", {}).keys())
        for sec_dir in SECURITY_DIRS:
            dirpath = os.path.join(self.base_dir, sec_dir)
            if not os.path.isdir(dirpath):
                continue
            for entry in os.listdir(dirpath):
                if not entry.endswith(".py"):
                    continue
                if entry.startswith(("_", ".")):
                    continue
                relpath = f"{sec_dir}/{entry}"
                if relpath not in known_files:
                    result["warnings"].append(
                        f"Unknown file in security directory: {relpath}"
                    )

        return result


def _hash_file(filepath: str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical_json(obj: dict) -> bytes:
    """Deterministic JSON for HMAC computation. Sorted keys, no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _tier_label(tier: int) -> str:
    """Human-readable label for a trust tier."""
    info = TRUST_TIERS.get(tier)
    if info:
        return info["label"]
    return f"Tier {tier}"
