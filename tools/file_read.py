"""Read file contents with line numbers, offset/limit, encoding detection, and security validation."""

import os
from pathlib import Path

from core.sandbox import get_sandbox, MAX_READ_LINES


def file_read(path: str, offset: int = 0, limit: int = 0) -> dict:
    """Read file contents and return with line numbers.

    Security: validates path against sandbox (confinement, symlink, size limits).

    Args:
        path: Absolute or relative file path.
        offset: Line number to start from (0-based). Default 0.
        limit: Max lines to return. 0 = all lines.

    Returns:
        dict with ok, content, lines_count, encoding, or ok=False with error.
    """
    # Normalize model-generated LaTeX escaping (e.g. YOPJ\_Portable -> YOPJ_Portable)
    # Only attempt normalization if the path doesn't already exist as-is.
    # This prevents mangling valid Windows paths like C:\Temp\_file.txt
    import re as _re
    if not os.path.exists(path):
        normalized = _re.sub(r'(?<=[A-Za-z])\\_(?=[A-Za-z])', '_', path)
        normalized = _re.sub(r'(?<=[A-Za-z])\\~(?=[A-Za-z])', '~', normalized)
        if normalized != path:
            path = normalized

    sandbox = get_sandbox()

    # Security check
    check = sandbox.validate_path(path, operation="read")
    if not check["ok"]:
        return {"ok": False, "error": check["error"]}

    p = Path(path)

    if not p.exists():
        return {"ok": False, "error": f"File not found: {path}"}

    if not p.is_file():
        return {"ok": False, "error": f"Not a file: {path}"}

    # Binary detection: read first 8KB and check for null bytes
    try:
        raw = p.read_bytes()[:8192]
        if b"\x00" in raw:
            size = p.stat().st_size
            return {"ok": False, "error": f"Binary file detected ({size} bytes): {path}"}
    except PermissionError:
        return {"ok": False, "error": f"Permission denied: {path}"}

    # Try encodings in order
    content = None
    detected_encoding = None
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            content = p.read_text(encoding=enc)
            detected_encoding = enc
            break
        except (UnicodeDecodeError, ValueError):
            continue

    if content is None:
        return {"ok": False, "error": f"Could not decode file: {path}"}

    lines = content.splitlines(keepends=True)
    total_lines = len(lines)

    # Apply offset/limit with hard cap (V4 — context erosion defense)
    if offset > 0:
        lines = lines[offset:]
    effective_limit = limit if limit > 0 else MAX_READ_LINES
    truncated_by_cap = len(lines) > effective_limit
    lines = lines[:effective_limit]

    # Format with line numbers
    start_num = offset + 1
    numbered = []
    for i, line in enumerate(lines):
        num = start_num + i
        numbered.append(f"{num:>6}\t{line.rstrip()}")

    result = {
        "ok": True,
        "content": "\n".join(numbered),
        "lines_count": total_lines,
        "encoding": detected_encoding,
    }
    if truncated_by_cap:
        result["truncated"] = True
        result["note"] = (
            f"Output capped at {effective_limit} lines (file has {total_lines}). "
            f"Use offset/limit to read remaining sections."
        )
    return result
