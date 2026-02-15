"""Absolute path resolution for critical binaries.

Resolves all external binaries at boot time using shutil.which(),
storing absolute paths so subprocess calls never rely on PATH after boot.
This eliminates PATH poisoning attacks (T4.1 in Co-Residency Threat Model).
"""

import os
import shutil


class PathRegistry:
    """Resolves and stores absolute paths for critical binaries at boot."""

    # Binaries required for core functionality. Missing = RuntimeError.
    REQUIRED_BINARIES = {
        "python": ["python.exe", "python3.exe", "python"],
        "git": ["git.exe", "git"],
    }

    # Binaries needed for server trust verification. Missing = warning.
    OPTIONAL_BINARIES = {
        "netstat": ["netstat.exe", "netstat"],
        "tasklist": ["tasklist.exe", "tasklist"],
        "findstr": ["findstr.exe", "findstr"],
    }

    def __init__(self):
        self._paths: dict[str, str] = {}
        self._warnings: list[str] = []

    def resolve_all(self) -> dict[str, str]:
        """Resolve all binaries. Returns dict of {name: absolute_path}.

        Raises RuntimeError if any REQUIRED binary cannot be found.
        """
        self._paths.clear()
        self._warnings.clear()

        # Required binaries — hard failure if missing
        missing = []
        for name, candidates in self.REQUIRED_BINARIES.items():
            path = self._resolve_one(candidates)
            if path:
                self._paths[name] = path
            else:
                missing.append(name)

        if missing:
            raise RuntimeError(
                f"Required binaries not found: {', '.join(missing)}. "
                f"Ensure they are installed and on PATH."
            )

        # Optional binaries — warn if missing
        for name, candidates in self.OPTIONAL_BINARIES.items():
            path = self._resolve_one(candidates)
            if path:
                self._paths[name] = path
            else:
                self._warnings.append(
                    f"Optional binary '{name}' not found — "
                    f"some security checks will be skipped."
                )

        return dict(self._paths)

    def _resolve_one(self, candidates: list[str]) -> str | None:
        """Try each candidate via shutil.which(). Return first absolute path."""
        for candidate in candidates:
            path = shutil.which(candidate)
            if path:
                return os.path.realpath(path)
        return None

    def get(self, name: str) -> str:
        """Get resolved absolute path. Raises KeyError if not resolved."""
        if name not in self._paths:
            raise KeyError(f"Binary '{name}' not in path registry")
        return self._paths[name]

    def get_optional(self, name: str) -> str | None:
        """Get path or None for optional binaries."""
        return self._paths.get(name)

    @property
    def warnings(self) -> list[str]:
        """Warnings about missing optional binaries."""
        return list(self._warnings)
