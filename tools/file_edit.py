"""Find-and-replace string editing for files with security validation."""

import os
from pathlib import Path

from core.sandbox import get_sandbox


def file_edit(path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict:
    """Replace occurrences of old_string with new_string in a file.

    Security: validates path against sandbox before reading or writing.

    Args:
        path: Absolute or relative file path.
        old_string: The text to find. Must be non-empty.
        new_string: The replacement text. Must differ from old_string.
        replace_all: If False, old_string must appear exactly once (default).
                     If True, replace all occurrences.

    Returns:
        dict with ok, replacements_count, or ok=False with error.
    """
    if not old_string:
        return {"ok": False, "error": "old_string must not be empty."}

    if old_string == new_string:
        return {"ok": False, "error": "old_string and new_string are identical."}

    # Normalize model-generated LaTeX escaping (e.g. YOPJ\_Portable -> YOPJ_Portable)
    import re as _re
    if not os.path.exists(path):
        normalized = _re.sub(r'(?<=[A-Za-z])\\_(?=[A-Za-z])', '_', path)
        normalized = _re.sub(r'(?<=[A-Za-z])\\~(?=[A-Za-z])', '~', normalized)
        if normalized != path:
            path = normalized

    sandbox = get_sandbox()

    # Security check (edit = read + write)
    check = sandbox.validate_path(path, operation="edit")
    if not check["ok"]:
        return {"ok": False, "error": check["error"]}

    p = Path(path)

    if not p.exists():
        return {"ok": False, "error": f"File not found: {path}"}

    try:
        content = p.read_text(encoding="utf-8")
    except PermissionError:
        return {"ok": False, "error": f"Permission denied: {path}"}
    except UnicodeDecodeError:
        return {"ok": False, "error": f"Cannot decode file as UTF-8: {path}"}

    count = content.count(old_string)

    if count == 0:
        return {"ok": False, "error": "old_string not found in file."}

    if not replace_all and count > 1:
        return {
            "ok": False,
            "error": f"old_string found {count} times. Use replace_all=True or provide more context to make it unique.",
        }

    if replace_all:
        new_content = content.replace(old_string, new_string)
        replacements = count
    else:
        new_content = content.replace(old_string, new_string, 1)
        replacements = 1

    try:
        p.write_text(new_content, encoding="utf-8")
    except PermissionError:
        return {"ok": False, "error": f"Permission denied writing: {path}"}

    return {"ok": True, "replacements_count": replacements}
