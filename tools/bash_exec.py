"""Execute shell commands via subprocess with timeout and security validation."""

import subprocess
import time

from core.sandbox import get_sandbox


def bash_exec(command: str, timeout_seconds: int = 120) -> dict:
    """Execute a shell command and return stdout, stderr, and return code.

    Security: validates command against blocked patterns before execution.
    Output is truncated to prevent memory exhaustion.

    Args:
        command: The shell command string to execute.
        timeout_seconds: Max seconds before killing the process. Default 120.

    Returns:
        dict with ok, stdout, stderr, returncode, duration_ms.
    """
    sandbox = get_sandbox()

    # Security check
    check = sandbox.validate_command(command)
    if not check["ok"]:
        return {
            "ok": False,
            "stdout": "",
            "stderr": check["error"],
            "returncode": -1,
            "duration_ms": 0,
            "error": check["error"],
        }

    start = time.time()

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        duration_ms = int((time.time() - start) * 1000)

        # Truncate large outputs
        stdout = sandbox.truncate_output(result.stdout)
        stderr = sandbox.truncate_output(result.stderr)

        return {
            "ok": result.returncode == 0,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": result.returncode,
            "duration_ms": duration_ms,
        }

    except subprocess.TimeoutExpired as e:
        duration_ms = int((time.time() - start) * 1000)
        return {
            "ok": False,
            "stdout": sandbox.truncate_output(e.stdout or ""),
            "stderr": sandbox.truncate_output(e.stderr or ""),
            "returncode": -1,
            "duration_ms": duration_ms,
            "error": f"Command timed out after {timeout_seconds}s.",
        }

    except OSError as e:
        duration_ms = int((time.time() - start) * 1000)
        return {
            "ok": False,
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
            "duration_ms": duration_ms,
            "error": f"OS error: {e}",
        }
