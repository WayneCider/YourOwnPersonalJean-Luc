"""Project type detection for YOPJ.

Scans the working directory for common project markers (package.json,
pyproject.toml, Cargo.toml, etc.) and returns structured info about the
project. This feeds into the system prompt so the model has project context.
"""

import os
import json
from pathlib import Path


# Marker files → project type mapping
_MARKERS = [
    # Python
    ("pyproject.toml", "python"),
    ("setup.py", "python"),
    ("setup.cfg", "python"),
    ("requirements.txt", "python"),
    ("Pipfile", "python"),
    ("poetry.lock", "python"),
    # JavaScript / TypeScript
    ("package.json", "javascript"),
    ("tsconfig.json", "typescript"),
    ("deno.json", "deno"),
    ("bun.lockb", "javascript"),
    # Rust
    ("Cargo.toml", "rust"),
    # Go
    ("go.mod", "go"),
    # Java / Kotlin
    ("pom.xml", "java"),
    ("build.gradle", "java"),
    ("build.gradle.kts", "kotlin"),
    # C / C++
    ("CMakeLists.txt", "cpp"),
    ("Makefile", "c"),
    ("meson.build", "cpp"),
    # .NET / C#
    ("*.csproj", "csharp"),
    ("*.sln", "csharp"),
    ("*.fsproj", "fsharp"),
    # Ruby
    ("Gemfile", "ruby"),
    # PHP
    ("composer.json", "php"),
    # Elixir
    ("mix.exs", "elixir"),
    # Zig
    ("build.zig", "zig"),
]

# Glob markers (need pattern matching)
_GLOB_MARKERS = [
    ("*.csproj", "csharp"),
    ("*.sln", "csharp"),
    ("*.fsproj", "fsharp"),
]


def detect_project(cwd: str = ".") -> dict:
    """Detect project type and metadata from the working directory.

    Returns dict with:
        type: str — project type ("python", "javascript", etc.) or "unknown"
        name: str — project name if detectable
        markers: list[str] — marker files found
        summary: str — one-line description for system prompt
        files_count: int — approximate file count (top 2 levels)
        has_git: bool — whether .git exists
        has_tests: bool — whether test directory/files exist
    """
    root = Path(cwd).resolve()
    result = {
        "type": "unknown",
        "name": root.name,
        "markers": [],
        "summary": "",
        "files_count": 0,
        "has_git": (root / ".git").is_dir(),
        "has_tests": False,
    }

    # Check marker files
    detected_types = []
    for marker, ptype in _MARKERS:
        if "*" in marker:
            continue  # Skip glob markers in this pass
        if (root / marker).exists():
            result["markers"].append(marker)
            detected_types.append(ptype)

    # Check glob markers
    for pattern, ptype in _GLOB_MARKERS:
        matches = list(root.glob(pattern))
        if matches:
            result["markers"].append(matches[0].name)
            detected_types.append(ptype)

    # Pick the most specific type
    if detected_types:
        # TypeScript > JavaScript (TS projects also have package.json)
        if "typescript" in detected_types:
            result["type"] = "typescript"
        else:
            result["type"] = detected_types[0]

    # Extract project name from metadata files
    result["name"] = _extract_name(root, result["type"]) or root.name

    # Count files (top 2 levels, skip hidden/build dirs)
    skip = {".git", "__pycache__", "node_modules", ".venv", "venv",
            "target", "build", "dist", ".mypy_cache", ".next", ".nuxt"}
    count = 0
    for item in root.iterdir():
        if item.name.startswith(".") and item.is_dir():
            continue
        if item.name in skip:
            continue
        if item.is_file():
            count += 1
        elif item.is_dir():
            try:
                count += sum(1 for f in item.iterdir() if f.is_file())
            except PermissionError:
                pass
    result["files_count"] = count

    # Detect test directories
    test_indicators = ["tests", "test", "__tests__", "spec", "specs"]
    for t in test_indicators:
        if (root / t).is_dir():
            result["has_tests"] = True
            break
    # Also check for test files in root
    for f in root.iterdir():
        if f.is_file() and f.name.startswith("test_") and f.suffix == ".py":
            result["has_tests"] = True
            break

    # Build summary
    result["summary"] = _build_summary(result)

    return result


def _extract_name(root: Path, ptype: str) -> str | None:
    """Try to extract the project name from a metadata file."""
    try:
        if ptype == "python":
            pyproject = root / "pyproject.toml"
            if pyproject.exists():
                text = pyproject.read_text(encoding="utf-8")
                for line in text.splitlines():
                    line = line.strip()
                    if line.startswith("name"):
                        # name = "foo"
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            return parts[1].strip().strip('"').strip("'")

        elif ptype in ("javascript", "typescript"):
            pkg = root / "package.json"
            if pkg.exists():
                data = json.loads(pkg.read_text(encoding="utf-8"))
                return data.get("name")

        elif ptype == "rust":
            cargo = root / "Cargo.toml"
            if cargo.exists():
                text = cargo.read_text(encoding="utf-8")
                for line in text.splitlines():
                    line = line.strip()
                    if line.startswith("name"):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            return parts[1].strip().strip('"').strip("'")

        elif ptype == "go":
            gomod = root / "go.mod"
            if gomod.exists():
                first_line = gomod.read_text(encoding="utf-8").splitlines()[0]
                # module github.com/user/repo
                parts = first_line.split()
                if len(parts) >= 2:
                    return parts[1].rsplit("/", 1)[-1]

    except Exception:
        pass
    return None


def _build_summary(info: dict) -> str:
    """Build a one-line summary for the system prompt."""
    parts = []
    if info["type"] != "unknown":
        parts.append(f"{info['type']} project")
    else:
        parts.append("project")

    if info["name"]:
        parts[0] = f"{info['name']} ({parts[0]})"

    parts.append(f"~{info['files_count']} files")

    if info["has_git"]:
        parts.append("git")
    if info["has_tests"]:
        parts.append("has tests")

    return ", ".join(parts)


def format_project_context(info: dict) -> str:
    """Format project info as a system prompt section.

    Returns a string suitable for appending to the system prompt, or empty
    string if no useful info was detected.
    """
    if info["type"] == "unknown" and not info["markers"]:
        return ""

    lines = ["\n# Project Context"]
    lines.append(f"Working directory: {info['summary']}")
    if info["markers"]:
        lines.append(f"Detected from: {', '.join(info['markers'])}")
    if info["has_git"]:
        lines.append("Version control: git")
    if info["has_tests"]:
        lines.append("Has test directory")

    return "\n".join(lines)
