"""Server trust verification for llama-server connections.

Verifies that the process on the target port is the expected llama-server
binary, not an impersonator. Also validates model identity via /props.
Protects against server swap attacks (Co-Residency Threat Model v1.1,
Section 7, threat T3.2).
"""

import json
import os
import re
import subprocess
import urllib.request
from typing import Optional


class ServerTrustError(Exception):
    """Raised when server trust verification fails."""
    pass


class ServerTrustVerifier:
    """Process-level and model-level verification for llama-server."""

    EXPECTED_PROCESS_NAMES = {"llama-server.exe", "llama-cli.exe"}

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        path_registry=None,
        expected_model: str = None,
    ):
        self.host = host
        self.port = port
        self.path_registry = path_registry
        self.expected_model = expected_model

    def check_port_available(self) -> dict:
        """Check that the target port is NOT already bound.

        Used in managed mode BEFORE Jean-Luc launches llama-server.
        If port is pre-bound, a rogue server may be waiting.

        Returns:
            dict with ok (bool), error (str|None), pid (int|None)
        """
        netstat_path = self._get_binary("netstat")
        if not netstat_path:
            return {
                "ok": True,
                "warning": "netstat not available — skipping port pre-check.",
            }

        try:
            result = subprocess.run(
                [netstat_path, "-ano"],
                capture_output=True, text=True, timeout=10,
            )
            pid = self._find_listening_pid(result.stdout)
            if pid is not None:
                return {
                    "ok": False,
                    "error": (
                        f"Port {self.port} already bound by PID {pid}. "
                        f"Possible rogue server. Refusing to start."
                    ),
                    "pid": pid,
                }
            return {"ok": True}
        except (subprocess.TimeoutExpired, OSError) as e:
            return {
                "ok": True,
                "warning": f"Port pre-check failed: {e}",
            }

    def verify_process(self) -> dict:
        """Verify the process behind the port is the expected llama-server.

        Runs AFTER connection is established, BEFORE sending system prompt
        (TOCTOU mitigation).

        Returns:
            dict with ok (bool), error/warning (str|None),
            process_name (str|None), pid (int|None)
        """
        netstat_path = self._get_binary("netstat")
        tasklist_path = self._get_binary("tasklist")

        if not netstat_path or not tasklist_path:
            return {
                "ok": True,
                "warning": (
                    "Cannot verify server process — "
                    "netstat/tasklist not available."
                ),
            }

        # Step 1: Get PID listening on port
        try:
            result = subprocess.run(
                [netstat_path, "-ano"],
                capture_output=True, text=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            return {"ok": True, "warning": f"netstat failed: {e}"}

        pid = self._find_listening_pid(result.stdout)
        if pid is None:
            return {
                "ok": False,
                "error": f"No process found listening on port {self.port}.",
            }

        # Step 2: Get process name for PID
        process_name = self._get_process_name(tasklist_path, pid)
        if process_name is None:
            return {
                "ok": False,
                "error": f"Cannot identify process for PID {pid}.",
            }

        # Step 3: Verify against expected names
        expected_lower = {n.lower() for n in self.EXPECTED_PROCESS_NAMES}
        if process_name.lower() not in expected_lower:
            return {
                "ok": False,
                "error": (
                    f"Unexpected process on port {self.port}: "
                    f"'{process_name}' (PID {pid}). "
                    f"Expected one of: {', '.join(sorted(self.EXPECTED_PROCESS_NAMES))}"
                ),
                "process_name": process_name,
                "pid": pid,
            }

        return {"ok": True, "process_name": process_name, "pid": pid}

    def verify_model_identity(self, base_url: str = None) -> dict:
        """Query /props and compare model metadata against expectations.

        Returns:
            dict with ok (bool), warnings (list[str]),
            model_name (str|None), ctx_size (int|None)
        """
        if base_url is None:
            base_url = f"http://{self.host}:{self.port}"

        result = {"ok": True, "warnings": []}

        try:
            req = urllib.request.Request(f"{base_url}/props", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            result["warnings"].append(f"Cannot query /props: {e}")
            return result

        # Extract model info from /props response
        # model_path is top-level; n_ctx may be in default_generation_settings
        gen_settings = data.get("default_generation_settings", {})
        model_path = data.get("model_path", "") or gen_settings.get("model", "unknown")
        ctx_size = gen_settings.get("n_ctx", 0)

        result["model_name"] = model_path
        result["ctx_size"] = ctx_size

        # Model name substring match (checks against model_path)
        if self.expected_model:
            if self.expected_model.lower() not in model_path.lower():
                result["ok"] = False
                result["warnings"].append(
                    f"Model name mismatch: expected '{self.expected_model}' "
                    f"in '{model_path}'"
                )

        return result

    def _get_binary(self, name: str) -> Optional[str]:
        """Get absolute path from PathRegistry, or None."""
        if self.path_registry:
            return self.path_registry.get_optional(name)
        return None

    def _find_listening_pid(self, netstat_output: str) -> Optional[int]:
        """Parse netstat -ano output for PID listening on self.port."""
        # Match lines like: TCP  0.0.0.0:8080  0.0.0.0:0  LISTENING  1234
        # or: TCP  127.0.0.1:8080  0.0.0.0:0  LISTENING  1234
        pattern = re.compile(
            rf'TCP\s+\S+:{self.port}\s+\S+\s+LISTENING\s+(\d+)',
            re.IGNORECASE,
        )
        for line in netstat_output.splitlines():
            m = pattern.search(line)
            if m:
                return int(m.group(1))
        return None

    def _get_process_name(self, tasklist_path: str, pid: int) -> Optional[str]:
        """Get process image name for a PID via tasklist."""
        try:
            result = subprocess.run(
                [tasklist_path, "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.strip().splitlines():
                # CSV: "Image Name","PID","Session Name","Session#","Mem Usage"
                line = line.strip()
                if not line or line.startswith("INFO:"):
                    continue
                parts = line.split(",")
                if len(parts) >= 2:
                    proc_name = parts[0].strip().strip('"')
                    proc_pid = parts[1].strip().strip('"')
                    if proc_pid == str(pid):
                        return proc_name
        except (subprocess.TimeoutExpired, OSError):
            pass
        return None
