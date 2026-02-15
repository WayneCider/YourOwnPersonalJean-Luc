"""Git operations for YOPJ — wraps git CLI with safety guardrails.

Safety rules:
  - Never force-push
  - Never --no-verify
  - Never amend without explicit request
  - Never reset --hard without explicit request
"""

import subprocess
import os


def _run_git(args: list[str], cwd: str = ".") -> dict:
    """Run a git command and return structured result."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Git command timed out.", "returncode": -1}
    except FileNotFoundError:
        return {"ok": False, "error": "git not found on PATH.", "returncode": -1}


def git_status(cwd: str = ".") -> dict:
    """Get git status (short format)."""
    return _run_git(["status", "--short"], cwd)


def git_diff(staged: bool = False, cwd: str = ".") -> dict:
    """Get git diff. If staged=True, shows staged changes."""
    args = ["diff"]
    if staged:
        args.append("--cached")
    return _run_git(args, cwd)


def git_log(count: int = 10, oneline: bool = True, cwd: str = ".") -> dict:
    """Get recent git log entries."""
    args = ["log", f"-{count}"]
    if oneline:
        args.append("--oneline")
    return _run_git(args, cwd)


def git_add(files: str, cwd: str = ".") -> dict:
    """Stage files for commit. Pass specific filenames, not '.' or '-A'.

    Args:
        files: Space-separated file paths to stage.
    """
    file_list = files.split()

    # Safety: reject broad staging
    if "." in file_list or "-A" in file_list:
        return {"ok": False, "error": "Use specific file names instead of '.' or '-A'."}

    return _run_git(["add"] + file_list, cwd)


def git_commit(message: str, cwd: str = ".") -> dict:
    """Create a git commit with the given message.

    Never amends, never skips hooks.
    """
    if not message.strip():
        return {"ok": False, "error": "Commit message cannot be empty."}

    return _run_git(["commit", "-m", message], cwd)


def git_branch(cwd: str = ".") -> dict:
    """List branches and show current branch."""
    return _run_git(["branch", "-v"], cwd)
