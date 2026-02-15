"""Write string content to file with parent directory creation, backup, and security validation."""

import os
import shutil
import time
from pathlib import Path

from core.sandbox import get_sandbox


def file_write(path: str, content: str) -> dict:
    """Write content to a file, creating parent directories if needed.

    Security: validates path against sandbox (confinement, size limits).
    If the file already exists, a backup is created with a .bak.{timestamp} suffix.

    Args:
        path: Absolute or relative file path.
        content: String content to write.

    Returns:
        dict with ok, bytes_written, backup_path (if backup was made), or error.
    """
    # Normalize model-generated LaTeX escaping (e.g. YOPJ\_Portable -> YOPJ_Portable)
    import re as _re
    if not os.path.exists(path):
        normalized = _re.sub(r'(?<=[A-Za-z])\\_(?=[A-Za-z])', '_', path)
        normalized = _re.sub(r'(?<=[A-Za-z])\\~(?=[A-Za-z])', '~', normalized)
        if normalized != path:
            path = normalized

    sandbox = get_sandbox()

    # Security check
    check = sandbox.validate_path(path, operation="write")
    if not check["ok"]:
        return {"ok": False, "error": check["error"]}

    # Content size check
    if len(content.encode("utf-8")) > sandbox.max_file_size:
        return {
            "ok": False,
            "error": f"Content too large ({len(content):,} chars, max {sandbox.max_file_size:,} bytes)",
        }

    p = Path(path)
    backup_path = None

    try:
        # Create parent directories
        p.parent.mkdir(parents=True, exist_ok=True)

        # Backup existing file
        if p.exists() and p.is_file():
            ts = int(time.time())
            backup = p.with_suffix(f"{p.suffix}.bak.{ts}")
            shutil.copy2(str(p), str(backup))
            backup_path = str(backup)

        # Write content
        written = p.write_text(content, encoding="utf-8")

        result = {"ok": True, "bytes_written": written}
        if backup_path:
            result["backup_path"] = backup_path
        return result

    except PermissionError:
        return {"ok": False, "error": f"Permission denied: {path}"}
    except OSError as e:
        return {"ok": False, "error": f"OS error: {e}"}
