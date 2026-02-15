"""Configuration file support for YOPJ.

Loads settings from .yopj.toml (project-level) or ~/.yopj.toml (user-level).
CLI flags override config file values. Config file overrides defaults.

Supports TOML format (Python 3.11+ has tomllib built-in, fallback parser for 3.10).
"""

import os
import sys
from pathlib import Path


# Default configuration values (same as CLI defaults)
DEFAULTS = {
    "model": None,
    "server": False,
    "host": "127.0.0.1",
    "port": 8080,
    "template": None,
    "ctx_size": 8192,
    "temp": 0.2,
    "n_predict": 4096,
    "ngl": 99,
    "timeout": 300,
    "memory_dir": ".",
    "cwd": None,
    "lessons_dir": None,
    "strict_sandbox": False,
    "dangerously_skip_permissions": False,
    "llama_cli": None,
    "plugins_dir": None,
    "expected_model": None,
}

# Config file search order (first found wins)
CONFIG_FILENAMES = [".yopj.toml", "yopj.toml"]
CONFIG_SEARCH_DIRS = [
    ".",                          # Current directory (project-level)
    str(Path.home()),             # Home directory (user-level)
]


def _parse_toml(text: str) -> dict:
    """Minimal TOML parser for simple key-value configs.

    Handles: strings, integers, floats, booleans, comments.
    Does NOT handle: arrays, tables, inline tables, multiline strings.
    Good enough for YOPJ config files.
    """
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        # Skip table headers like [section]
        if key.startswith("["):
            continue

        # Remove inline comments
        if "#" in value and not value.startswith('"') and not value.startswith("'"):
            value = value[:value.index("#")].strip()

        # Parse value type
        if value.lower() == "true":
            result[key] = True
        elif value.lower() == "false":
            result[key] = False
        elif value.startswith('"') and value.endswith('"'):
            result[key] = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            result[key] = value[1:-1]
        else:
            # Try numeric
            try:
                if "." in value:
                    result[key] = float(value)
                else:
                    result[key] = int(value)
            except ValueError:
                result[key] = value  # Keep as string

    return result


def find_config_file() -> str | None:
    """Find the first config file in the search path."""
    for directory in CONFIG_SEARCH_DIRS:
        for filename in CONFIG_FILENAMES:
            path = os.path.join(directory, filename)
            if os.path.isfile(path):
                return path
    return None


def load_config(config_path: str = None) -> dict:
    """Load configuration from file.

    Args:
        config_path: Explicit path to config file. If None, searches default locations.

    Returns:
        Dict of configuration values. Missing keys use DEFAULTS.
    """
    config = dict(DEFAULTS)

    # Find config file
    path = config_path or find_config_file()
    if not path or not os.path.isfile(path):
        return config

    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return config

    # Try Python 3.11+ tomllib first
    try:
        import tomllib
        file_config = tomllib.loads(text)
    except ImportError:
        # Fallback to minimal parser
        file_config = _parse_toml(text)

    # Normalize key names (TOML uses - or _, CLI uses _)
    normalized = {}
    for key, value in file_config.items():
        norm_key = key.replace("-", "_")
        normalized[norm_key] = value

    # Merge: file values override defaults
    for key, value in normalized.items():
        if key in config:
            config[key] = value

    config["_config_file"] = path
    return config


def merge_cli_args(config: dict, args) -> dict:
    """Merge CLI arguments over config file values.

    CLI args that are None or False (defaults) don't override config.
    Explicitly set CLI args always win.
    """
    result = dict(config)

    # Map argparse attribute names to config keys
    mappings = {
        "model": "model",
        "server": "server",
        "host": "host",
        "port": "port",
        "template": "template",
        "ctx_size": "ctx_size",
        "temp": "temp",
        "n_predict": "n_predict",
        "ngl": "ngl",
        "timeout": "timeout",
        "memory_dir": "memory_dir",
        "cwd": "cwd",
        "lessons_dir": "lessons_dir",
        "strict_sandbox": "strict_sandbox",
        "dangerously_skip_permissions": "dangerously_skip_permissions",
        "llama_cli": "llama_cli",
        "plugins_dir": "plugins_dir",
    }

    for arg_name, config_key in mappings.items():
        cli_value = getattr(args, arg_name, None)
        if cli_value is None:
            continue
        # For boolean flags: only override if True (explicitly set)
        if isinstance(cli_value, bool) and not cli_value:
            continue
        # For numeric with defaults: only override if different from argparse default
        result[config_key] = cli_value

    return result


def generate_sample_config() -> str:
    """Generate a sample .yopj.toml config file."""
    return '''# YOPJ Configuration
# Place this file at .yopj.toml (project) or ~/.yopj.toml (user)

# Model settings
# model = "path/to/model.gguf"     # Required unless server = true
# llama_cli = "path/to/llama-cli"  # Auto-detected if omitted
# template = "chatml"              # Auto-detected from model name

# Server mode (recommended — 20x faster)
server = true
host = "127.0.0.1"
port = 8080

# Generation settings
ctx_size = 8192
temp = 0.2
n_predict = 4096
ngl = 99
timeout = 300

# Learning (SEAL)
# lessons_dir = "./lessons"
# memory_dir = "."

# Plugins
# plugins_dir = "./plugins"

# Security
# strict_sandbox = false
# dangerously_skip_permissions = false
'''
