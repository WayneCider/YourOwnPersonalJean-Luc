# Backward compatibility — canonical location is tools/core/git_tools.py
from tools.core.git_tools import (  # noqa: F401
    git_status, git_diff, git_log, git_add, git_commit, git_branch,
    register_tools,
)
