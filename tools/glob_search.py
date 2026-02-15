"""Find files by glob pattern, sorted by modification time, with security validation."""

import os
from pathlib import Path

from core.sandbox import get_sandbox


def glob_search(pattern: str, path: str = ".") -> dict:
    """Find files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g., "**/*.py", "*.txt").
        path: Root directory to search from. Default is current directory.

    Returns:
        dict with ok, matches (list of file paths sorted by mtime, newest first).
    """
    # Normalize model-generated LaTeX escaping (e.g. YOPJ\_Portable -> YOPJ_Portable)
    import re as _re
    if not os.path.exists(path):
        normalized = _re.sub(r'(?<=[A-Za-z])\\_(?=[A-Za-z])', '_', path)
        normalized = _re.sub(r'(?<=[A-Za-z])\\~(?=[A-Za-z])', '~', normalized)
        if normalized != path:
            path = normalized

    sandbox = get_sandbox()
    check = sandbox.validate_path(path, operation="read")
    if not check["ok"]:
        return {"ok": False, "error": check["error"]}

    root = Path(path)

    if not root.exists():
        return {"ok": False, "error": f"Directory not found: {path}"}

    if not root.is_dir():
        return {"ok": False, "error": f"Not a directory: {path}"}

    try:
        matches = [p for p in root.glob(pattern) if p.is_file()]
    except ValueError as e:
        return {"ok": False, "error": f"Invalid glob pattern: {e}"}

    # Sort by modification time, newest first
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    return {
        "ok": True,
        "matches": [str(m) for m in matches],
    }
