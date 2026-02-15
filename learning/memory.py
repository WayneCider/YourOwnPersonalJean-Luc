"""Cross-session memory for YOPJ.

Manages a MEMORY.md file that persists across sessions. The model reads this
at session start to recover context from previous work. Sections can be
updated, appended to, or removed.

The memory file uses markdown sections (## headers) as keys.
"""

import os
import re
from pathlib import Path


DEFAULT_MAX_LINES = 200  # Keep memory concise


def load_memory(memory_dir: str, filename: str = "MEMORY.md") -> str:
    """Load memory file contents. Returns empty string if not found."""
    path = os.path.join(memory_dir, filename)
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save_memory(memory_dir: str, content: str, filename: str = "MEMORY.md") -> dict:
    """Save memory file. Creates directory if needed.

    Returns dict with ok, lines_count.
    """
    os.makedirs(memory_dir, exist_ok=True)
    path = os.path.join(memory_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    lines = content.count("\n") + 1
    return {"ok": True, "lines_count": lines}


def get_sections(content: str) -> dict[str, str]:
    """Parse memory content into sections keyed by ## header.

    Returns dict mapping section header text to section body.
    The content before the first ## header (if any) is keyed as "_preamble".
    """
    sections = {}
    current_key = "_preamble"
    current_lines = []

    for line in content.splitlines():
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            # Save previous section
            sections[current_key] = "\n".join(current_lines).strip()
            current_key = m.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Save last section
    sections[current_key] = "\n".join(current_lines).strip()

    # Remove empty preamble
    if "_preamble" in sections and not sections["_preamble"]:
        del sections["_preamble"]

    return sections


def update_section(content: str, section_name: str, new_body: str) -> str:
    """Update or create a section in memory content.

    If section exists, replaces its body. If not, appends it at the end.
    Returns the updated content string.
    """
    sections = get_sections(content)

    if section_name in sections:
        sections[section_name] = new_body
    else:
        sections[section_name] = new_body

    return _rebuild_content(sections)


def remove_section(content: str, section_name: str) -> str:
    """Remove a section from memory content.

    Returns the updated content string. No-op if section doesn't exist.
    """
    sections = get_sections(content)
    sections.pop(section_name, None)
    return _rebuild_content(sections)


def append_to_section(content: str, section_name: str, text: str) -> str:
    """Append text to an existing section, or create it.

    Returns the updated content string.
    """
    sections = get_sections(content)
    existing = sections.get(section_name, "")
    if existing:
        sections[section_name] = existing + "\n" + text
    else:
        sections[section_name] = text
    return _rebuild_content(sections)


def trim_to_limit(content: str, max_lines: int = DEFAULT_MAX_LINES) -> str:
    """Trim content to max_lines, keeping the most important sections.

    Removes from the bottom up to stay within limit.
    """
    lines = content.splitlines()
    if len(lines) <= max_lines:
        return content
    return "\n".join(lines[:max_lines]) + "\n... (truncated)"


def _rebuild_content(sections: dict[str, str]) -> str:
    """Rebuild memory content from sections dict."""
    parts = []

    # Preamble first (if any)
    if "_preamble" in sections:
        parts.append(sections["_preamble"])

    # All other sections
    for key, body in sections.items():
        if key == "_preamble":
            continue
        parts.append(f"## {key}\n{body}")

    return "\n\n".join(parts) + "\n"
