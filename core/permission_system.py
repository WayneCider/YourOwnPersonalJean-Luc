"""Permission system for YOPJ — controls which tools the model can invoke.

Three modes:
  - "ask": Prompt the user before executing (default for write/exec tools)
  - "allow": Auto-allow without prompting (default for read-only tools)
  - "deny": Block execution entirely

Per-tool overrides can be set. The --dangerously-skip-permissions flag
sets all tools to "allow" mode.
"""

import sys


# Default permission levels by tool name
DEFAULT_PERMISSIONS = {
    # Read-only tools: auto-allow
    "file_read": "allow",
    "glob_search": "allow",
    "grep_search": "allow",
    # Write tools: ask
    "file_write": "ask",
    "file_edit": "ask",
    # Execution tools: ask
    "bash_exec": "ask",
    # Git tools: ask
    "git_status": "allow",
    "git_diff": "allow",
    "git_log": "allow",
    "git_add": "ask",
    "git_commit": "ask",
    "git_branch": "allow",
}


class PermissionSystem:
    """Manages tool execution permissions."""

    def __init__(self, skip_permissions: bool = False):
        """Initialize permission system.

        Args:
            skip_permissions: If True, all tools are auto-allowed.
        """
        self.skip_all = skip_permissions
        self.overrides: dict[str, str] = {}
        self._session_allowed: set[str] = set()  # Tools allowed for this session

    def get_permission(self, tool_name: str) -> str:
        """Get the effective permission for a tool.

        Returns "allow", "ask", or "deny".
        """
        if self.skip_all:
            return "allow"
        if tool_name in self.overrides:
            return self.overrides[tool_name]
        return DEFAULT_PERMISSIONS.get(tool_name, "ask")

    def set_permission(self, tool_name: str, mode: str) -> None:
        """Override permission for a specific tool.

        Args:
            tool_name: Name of the tool.
            mode: "allow", "ask", or "deny".
        """
        if mode not in ("allow", "ask", "deny"):
            raise ValueError(f"Invalid permission mode: {mode}")
        self.overrides[tool_name] = mode

    def check_and_prompt(self, tool_name: str, args_preview: str) -> bool:
        """Check permission and prompt user if needed.

        Returns True if execution is allowed, False if denied.
        """
        perm = self.get_permission(tool_name)

        if perm == "allow":
            return True

        if perm == "deny":
            return False

        # "ask" mode — check if already allowed this session
        if tool_name in self._session_allowed:
            return True

        # Prompt user
        print(f"\n  Tool: {tool_name}({args_preview[:80]})")
        try:
            response = input("  Allow? [y/n/a(lways)] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False

        if response in ("y", "yes"):
            return True
        elif response in ("a", "always"):
            self._session_allowed.add(tool_name)
            return True
        else:
            return False

    def reset_session(self) -> None:
        """Clear session-level permissions (keeps overrides)."""
        self._session_allowed.clear()
