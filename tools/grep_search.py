"""Search file contents by regex pattern, with security validation."""

import os
import re
from pathlib import Path

from core.sandbox import get_sandbox


def grep_search(
    pattern: str,
    path: str = ".",
    glob_filter: str = None,
    max_results: int = 50,
) -> dict:
    """Search files for lines matching a regex pattern.

    Args:
        pattern: Regex pattern to search for.
        path: Root directory or single file to search.
        glob_filter: Optional glob to filter which files to search (e.g., "*.py").
        max_results: Maximum number of matches to return. Default 50.

    Returns:
        dict with ok, matches (list of dicts with file, line_number, line_text).
    """
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return {"ok": False, "error": f"Invalid regex: {e}"}

    # Normalize model-generated path escaping (e.g. \_Portable -> _Portable)
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
    matches = []

    if root.is_file():
        files = [root]
    elif root.is_dir():
        if glob_filter:
            files = sorted(root.rglob(glob_filter))
        else:
            files = sorted(root.rglob("*"))
        files = [f for f in files if f.is_file()]
    else:
        return {"ok": False, "error": f"Path not found: {path}"}

    for fpath in files:
        if len(matches) >= max_results:
            break

        # Skip binary files
        try:
            head = fpath.read_bytes()[:512]
            if b"\x00" in head:
                continue
        except (PermissionError, OSError):
            continue

        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except (PermissionError, OSError):
            continue

        for i, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append({
                    "file": str(fpath),
                    "line_number": i,
                    "line_text": line.rstrip(),
                })
                if len(matches) >= max_results:
                    break

    return {"ok": True, "matches": matches}
