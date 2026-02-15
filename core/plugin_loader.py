"""Plugin loader for YOPJ — load user-defined tools from a directory.

Users drop Python files into a plugins/ directory. Each file should define
a register_tools(registry) function that registers tools on the given
ToolRegistry.

Example plugin (plugins/my_tool.py):

    def word_count(text):
        '''Count words in text.'''
        words = text.split()
        return {"ok": True, "count": len(words)}

    def register_tools(registry):
        registry.register_tool("word_count", word_count, "Count words in text")
"""

import os
import sys
import importlib.util
from pathlib import Path


def load_plugins(plugin_dir: str, registry) -> list[dict]:
    """Load all plugin files from a directory and register their tools.

    Each plugin file must define register_tools(registry).
    Files starting with _ or . are skipped.

    Args:
        plugin_dir: Path to directory containing plugin .py files.
        registry: ToolRegistry instance to register tools on.

    Returns:
        List of dicts with: name (str), file (str), ok (bool), error (str|None).
    """
    results = []
    plugin_path = Path(plugin_dir)

    if not plugin_path.is_dir():
        return results

    for entry in sorted(plugin_path.iterdir()):
        if not entry.is_file():
            continue
        if not entry.name.endswith(".py"):
            continue
        if entry.name.startswith(("_", ".")):
            continue

        result = _load_single_plugin(entry, registry)
        results.append(result)

    return results


def _load_single_plugin(filepath: Path, registry) -> dict:
    """Load a single plugin file and call its register_tools()."""
    module_name = f"yopj_plugin_{filepath.stem}"

    try:
        spec = importlib.util.spec_from_file_location(module_name, str(filepath))
        if spec is None or spec.loader is None:
            return {
                "name": filepath.stem,
                "file": str(filepath),
                "ok": False,
                "error": "Could not create module spec",
            }

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        if not hasattr(module, "register_tools"):
            return {
                "name": filepath.stem,
                "file": str(filepath),
                "ok": False,
                "error": "Missing register_tools(registry) function",
            }

        # Count tools before and after to report what was registered
        before = set(t["name"] for t in registry.list_tools())
        module.register_tools(registry)
        after = set(t["name"] for t in registry.list_tools())
        new_tools = after - before

        return {
            "name": filepath.stem,
            "file": str(filepath),
            "ok": True,
            "error": None,
            "tools": sorted(new_tools),
        }

    except Exception as e:
        # Clean up partial module
        if module_name in sys.modules:
            del sys.modules[module_name]
        return {
            "name": filepath.stem,
            "file": str(filepath),
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
        }


def check_unexpected_plugins(plugin_dir: str) -> list[str]:
    """Check for .py files in a plugins directory WITHOUT loading them.

    Used when --plugins-dir is NOT specified to warn about unexpected
    plugin files that could be dropped by a co-resident agent.

    Returns:
        List of unexpected .py filenames found.
    """
    plugin_path = Path(plugin_dir)
    if not plugin_path.is_dir():
        return []

    unexpected = []
    for entry in sorted(plugin_path.iterdir()):
        if not entry.is_file():
            continue
        if not entry.name.endswith(".py"):
            continue
        if entry.name.startswith(("_", ".")):
            continue
        unexpected.append(entry.name)

    return unexpected


def format_plugin_tool_docs(registry, builtin_tools: set[str]) -> str:
    """Generate system prompt documentation for plugin-added tools.

    Args:
        registry: ToolRegistry with all tools registered.
        builtin_tools: Set of tool names that are built-in (not plugins).

    Returns:
        String to append to system prompt, or empty string if no plugins.
    """
    all_tools = {t["name"]: t["description"] for t in registry.list_tools()}
    plugin_tools = {n: d for n, d in all_tools.items() if n not in builtin_tools}

    if not plugin_tools:
        return ""

    lines = ["\n# Plugin Tools (user-installed)"]
    for name, desc in sorted(plugin_tools.items()):
        lines.append(f"::TOOL {name}(...):: — {desc}")

    return "\n".join(lines)
