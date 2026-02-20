"""Security sandbox for YOPJ tool execution.

Centralizes all security policies:
- Path confinement: file operations restricted to allowed directories (STRICT by default)
- Command validation: 4-phase (normalize → shell operators → allowlist → blocklist)
- Interpreter restrictions: python -c, node -e, dynamic imports all blocked
- Network egress blocking: no curl, wget, git push, interpreters w/ network libs
- Protected files: MEMORY.md is read-only at runtime
- Output limits: prevent memory exhaustion from large outputs
- Symlink resolution: prevent directory escape via symlinks
- Audit logging: all tool invocations recorded

SECURITY MODEL (post-Archie-audit, v0.14.0):
- Default is STRICT — file ops confined to cwd + explicitly allowed dirs
- Commands: normalize → reject shell operators → allowlist → blocklist
- Shell operators (&&, ||, ;, |, >, >>, <, 2>, backtick, $()) blocked before allowlist check
- Interpreters (python, node) blocked from inline execution (-c, -e, __import__)
- Git network commands (push, pull, fetch, clone) blocked
- MEMORY.md is immutable at runtime (read-only)

This is YOPJ's Layer 1 security — basic governance that ships with the open
agent. The full Gatekeeper (Layer 3) is part of R2, not YOPJ.
"""

import os
import re
import time
import unicodedata
from pathlib import Path


# ============================================================
# Command ALLOWLIST — only these prefixes are permitted
# ============================================================

# Commands that are allowed to execute. Everything else is blocked.
_ALLOWED_COMMAND_PREFIXES = [
    # Version control — read-only + safe write ops only (Archie audit round 2)
    # Read-only: status, diff, log, show, blame, branch, tag, rev-parse, ls-files
    # Safe write: add, commit, stash, init
    # REMOVED: checkout, reset, clean, merge, rebase, cherry-pick, config, remote
    "git status", "git diff", "git log", "git add", "git commit",
    "git branch", "git stash",
    "git show", "git blame", "git tag",
    "git init",
    "git rev-parse", "git ls-files",
    # Build/package tools (restricted — see blocklist for -c/-e blocks)
    "python ", "python3 ", "pip ", "pip3 ",
    "node ", "npm ", "yarn ",
    "cargo ", "rustc ",
    "go ", "go build", "go test", "go run",
    "make", "cmake ",
    "dotnet ", "nuget ",
    "javac ", "java ", "mvn ", "gradle ",
    # File inspection (read-only)
    "cat ", "head ", "tail ", "less ", "more ",
    "ls", "dir", "tree ",
    "find ", "grep ", "rg ", "ag ",
    "wc ", "sort ", "uniq ", "diff ",
    "file ", "stat ", "du ", "df ",
    "type ", "where ", "which ",
    # Text processing
    "sed ", "awk ", "cut ", "tr ",
    "echo ", "printf ",
    # Archive (read)
    "tar ", "unzip ", "7z ",
    # Testing
    "pytest", "unittest", "jest ", "mocha ", "vitest ",
    # Misc safe
    "cd ", "pwd", "date", "whoami", "hostname",
    "mkdir ", "touch ", "cp ", "mv ",
]

# ============================================================
# Shell operator blocking (Phase 1 — before allowlist)
# ============================================================

# These shell metacharacters enable command chaining, piping, and substitution.
# Blocking them prevents "git status && curl evil.com" style attacks.
_SHELL_OPERATOR_PATTERNS = [
    r'&&',              # AND chaining: cmd1 && cmd2
    r'\|\|',            # OR chaining: cmd1 || cmd2
    r';\s',             # semicolon separator: cmd1; cmd2
    r';$',              # trailing semicolon
    r'`',               # backtick command substitution
    r'\$\(',            # dollar-paren substitution: $(cmd)
    r'\$\{',            # variable expansion: ${var}
    r'\s\|\s',          # pipe: cmd1 | cmd2 (space-delimited to avoid grep regex false positives)
    r'\s>\s',           # output redirection: cmd > file
    r'\s>>\s',          # append redirection: cmd >> file
    r'\s<\s',           # input redirection: cmd < file
    r'\s2>\s',          # stderr redirection: cmd 2> file
]

_SHELL_OPERATOR_RE = [re.compile(p) for p in _SHELL_OPERATOR_PATTERNS]

# ============================================================
# Command BLOCKLIST — blocked even if allowlist matches
# ============================================================

_BLOCKED_PATTERNS = [
    # --- Interpreter inline execution (V1, V6) ---
    r'\bpython3?\s+-c\b',                # python -c "code" (inline execution)
    r'\bpython3?\s+-m\s+http\b',         # python -m http.server (network)
    r'\bpython3?\s+-m\s+smtplib\b',      # python -m smtplib
    r'\bpython3?\s+-m\s+smtpd\b',        # python -m smtpd
    r'\bpython3?\s+-m\s+SimpleHTTP',     # python -m SimpleHTTPServer
    r'\bnode\s+-e\b',                     # node -e "code" (inline execution)
    r'\bnode\s+--eval\b',                 # node --eval "code"
    r'\bnpx\s',                           # npx (runs arbitrary npm packages)
    # Dynamic import/execution patterns (catch obfuscated imports)
    r'__import__',                        # __import__('socket')
    r'\beval\s*\(',                       # eval(...)
    r'\bexec\s*\(',                       # exec(...)
    r'\bcompile\s*\(',                    # compile(...)
    r'\bgetattr\s*\(',                    # getattr(module, 'dangerous')
    r"globals\s*\(\s*\)\s*\[",           # globals()['__import__']
    r"builtins",                          # __builtins__.__import__
    # --- Destructive file operations ---
    r'\brm\s+(-\w*f\w*\s+)*-\w*r',       # rm -rf, rm -fr, rm --recursive -f
    r'\brm\s+-rf\b',                      # explicit rm -rf
    r'\brmdir\s+/s\b',                    # Windows rmdir /s
    r'\bdel\s+/[sS]\b',                   # Windows del /s
    r'\bformat\s+[A-Za-z]:',             # format C:
    r'\bmkfs\b',                          # mkfs (disk format)
    r'\bdd\s+.*\bof=/',                   # dd writing to device
    r'\b:\(\)\s*\{\s*:\|:&\s*\}',        # fork bomb :(){ :|:& }
    # --- System configuration modification ---
    r'\bgit\s+config\s+--global\b',       # git config --global (system-wide change)
    r'\bgit\s+config\s+--system\b',       # git config --system
    r'\breg\s+add\b',                     # Windows registry modification
    r'\breg\s+delete\b',                  # Windows registry deletion
    r'\bsetx\b',                          # Windows persistent env var
    r'\bschtasks\b',                      # Windows scheduled tasks
    r'\bsc\s+(create|config|delete)\b',   # Windows service modification
    r'\bnet\s+user\b',                    # Windows user management
    r'\bnet\s+localgroup\b',              # Windows group management
    r'\bicacls\b',                        # Windows ACL modification
    # --- Git network operations (V5) ---
    r'\bgit\s+push\b',                    # git push (network exfil)
    r'\bgit\s+fetch\b',                   # git fetch (network)
    r'\bgit\s+pull\b',                    # git pull (network)
    r'\bgit\s+clone\b',                   # git clone (network)
    r'\bgit\s+remote\s+add\b',            # git remote add (set up exfil target)
    r'\bgit\s+remote\s+set-url\b',        # git remote set-url (redirect exfil)
    # --- Credential/key theft ---
    r'\bcurl\b.*\|\s*sh\b',              # curl | sh (remote code execution)
    r'\bwget\b.*\|\s*sh\b',              # wget | sh
    r'\bwget\b.*\|\s*bash\b',            # wget | bash
    r'\bcurl\b.*\|\s*bash\b',            # curl | bash
    r'\bcurl\b.*\|\s*powershell\b',      # curl | powershell
    # --- Privilege escalation ---
    r'\bchmod\s+777\b',                   # chmod 777 (world-writable)
    r'\bchmod\s+(-\w+\s+)*\+s\b',        # setuid
    r'\bchown\s+root\b',                  # chown root
    r'\bsudo\b',                          # sudo (privilege escalation)
    r'\brunas\b',                         # Windows runas
    # --- Network exfiltration / egress ---
    r'\bcurl\b',                          # curl (any use)
    r'\bwget\b',                          # wget (any use)
    r'\bcertutil\b.*-urlcache\b',         # certutil download
    r'\bcertutil\b.*-encode\b',           # certutil encode (data exfil)
    r'\bInvoke-WebRequest\b',             # PowerShell web request
    r'\bInvoke-RestMethod\b',             # PowerShell REST
    r'\bStart-BitsTransfer\b',            # PowerShell BITS download
    r'\bNew-Object\s+.*Net\.WebClient\b', # .NET WebClient
    r'\bNet\.Sockets\b',                  # .NET raw sockets
    r'\b(System\.)?Net\.Http\b',          # .NET HTTP client
    r'\bnc\s',                            # netcat
    r'\bncat\s',                          # ncat
    r'\bsocat\s',                         # socat
    r'\bssh\s',                           # ssh (tunnel/egress)
    r'\bscp\s',                           # scp (file transfer)
    r'\bsftp\s',                          # sftp
    r'\bftp\s',                           # ftp
    r'\btelnet\s',                        # telnet
    # --- Python-based egress ---
    r'import\s+urllib',                    # urllib import
    r'import\s+requests',                 # requests import
    r'import\s+http\.client',             # http.client import
    r'import\s+socket\b',                 # socket import
    r'from\s+urllib',                     # from urllib import
    r'from\s+requests',                   # from requests import
    r'from\s+http\.client',              # from http.client import
    r'from\s+socket\b',                   # from socket import
    r'import\s+subprocess\b',             # subprocess import (process spawning)
    r'from\s+subprocess\b',              # from subprocess import
    r'import\s+ctypes\b',                # ctypes import (FFI escape)
    r'from\s+ctypes\b',                  # from ctypes import
    r'import\s+os\b',                     # os import (file/process access)
    r'from\s+os\b',                       # from os import
    # --- Node-based egress ---
    r"require\(['\"]https?['\"]",         # require('http')
    r"require\(['\"]net['\"]",            # require('net')
    r"require\(['\"]child_process['\"]",  # require('child_process')
    r"require\(['\"]fs['\"]",             # require('fs')
    # --- Environment enumeration (Zephyr audit — info disclosure) ---
    r'^\s*set\s*$',                       # set (dumps all env vars)
    r'^\s*env\s*$',                       # env (dumps all env vars)
    r'\bprintenv\b',                      # printenv (dumps env vars)
    # --- Shutdown/reboot ---
    r'\bshutdown\b',
    r'\breboot\b',
    r'\bhalt\b',
    r'\binit\s+0\b',
    # --- PowerShell escape hatches ---
    r'\bpowershell\b',                    # powershell (can bypass everything)
    r'\bpwsh\b',                          # PowerShell Core
    r'\bcmd\s*/c\b',                      # cmd /c (shell escape)
    r'\bcmd\.exe\b',                      # cmd.exe direct
    r'\bwscript\b',                       # Windows Script Host
    r'\bcscript\b',                       # Windows Script Host
    r'\bmshta\b',                         # MSHTA (HTML Application)
    r'\brundll32\b',                      # rundll32 (DLL execution)
    r'\bregsvr32\b',                      # regsvr32 (DLL registration)
]

_BLOCKED_RE = [re.compile(p, re.IGNORECASE) for p in _BLOCKED_PATTERNS]

# ============================================================
# Protected files — read-only at runtime (V3)
# ============================================================

# Filenames that cannot be written or edited via tools.
# MEMORY.md is the system prompt memory — poisoning it persists across sessions.
# Security-critical source files are also protected to prevent self-modification attacks.
_PROTECTED_FILENAMES = {"memory.md"}

# Path patterns that cannot be written or edited — protects security-critical source.
# Matches against the resolved path (case-insensitive).
_PROTECTED_PATH_PATTERNS = [
    "core/sandbox.py",
    "core/tool_protocol.py",
    "core/permission_system.py",
    "core\\sandbox.py",
    "core\\tool_protocol.py",
    "core\\permission_system.py",
    "knowledge/",
    "knowledge\\",
]

# Auto-execution locations — file_write blocked here (Archie audit round 2)
_BLOCKED_WRITE_PATTERNS = [
    ".git/hooks/",          # Git hooks (pre-commit, post-checkout, etc.)
    ".git\\hooks\\",
    "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/",  # Windows startup
    "Startup/",             # Catch partial matches
]

# Executable file extensions — blocked for file_write (no auto-execution artifacts)
_BLOCKED_WRITE_EXTENSIONS = {
    ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".wsf", ".wsh",
    ".exe", ".dll", ".scr", ".com", ".msi",
}

# NTFS reserved device names — cannot be used as filenames on Windows
# Writing to these can hang processes or cause OS-level side effects
_NTFS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}

# Sensitive file patterns — file_read requires redaction warning (data exfil defense)
_SENSITIVE_FILE_PATTERNS = [
    re.compile(r'\.env$', re.IGNORECASE),
    re.compile(r'\.env\.\w+$', re.IGNORECASE),  # .env.local, .env.production
    re.compile(r'id_rsa', re.IGNORECASE),
    re.compile(r'id_ed25519', re.IGNORECASE),
    re.compile(r'id_ecdsa', re.IGNORECASE),
    re.compile(r'\.pem$', re.IGNORECASE),
    re.compile(r'\.key$', re.IGNORECASE),
    re.compile(r'\.p12$', re.IGNORECASE),
    re.compile(r'\.pfx$', re.IGNORECASE),
    re.compile(r'secrets\.\w+$', re.IGNORECASE),
    re.compile(r'credentials', re.IGNORECASE),
    re.compile(r'\.npmrc$', re.IGNORECASE),
    re.compile(r'\.netrc$', re.IGNORECASE),
    re.compile(r'\.pgpass$', re.IGNORECASE),
    re.compile(r'token', re.IGNORECASE),
    re.compile(r'api[_-]?key', re.IGNORECASE),
]

# ============================================================
# Path confinement
# ============================================================

# Maximum file size for read/write operations (10 MB)
MAX_FILE_SIZE = 10 * 1024 * 1024

# Maximum output size from bash_exec (1 MB)
MAX_OUTPUT_SIZE = 1024 * 1024

# Maximum lines returned by file_read (V4 — context erosion defense)
MAX_READ_LINES = 500


def _normalize_command(command: str) -> str:
    """Normalize a command string before security validation (V7).

    Strips Unicode homoglyphs, collapses whitespace, removes zero-width
    characters. This prevents regex evasion via Unicode tricks.
    """
    # Strip zero-width characters (ZWJ, ZWNJ, zero-width space, etc.)
    command = re.sub(r'[\u200b-\u200f\u2028-\u202f\u2060\ufeff]', '', command)

    # Normalize Unicode to ASCII-compatible form (NFKD strips diacritics/homoglyphs)
    command = unicodedata.normalize('NFKD', command)

    # Remove non-ASCII characters that could be homoglyphs
    command = command.encode('ascii', errors='ignore').decode('ascii')

    # Collapse multiple whitespace into single space
    command = re.sub(r'\s+', ' ', command).strip()

    # Handle backslash-newline continuation (multiline evasion)
    command = command.replace('\\\n', '')

    return command


class Sandbox:
    """Security sandbox that validates tool operations before execution.

    All file and command operations pass through the sandbox for validation.
    Default mode is STRICT: only allowed_dirs are accessible.
    Use strict=False to enable permissive mode (not recommended).
    """

    def __init__(
        self,
        allowed_dirs: list[str] = None,
        strict: bool = True,
        max_file_size: int = MAX_FILE_SIZE,
        max_output_size: int = MAX_OUTPUT_SIZE,
    ):
        if allowed_dirs:
            self.allowed_dirs = [os.path.realpath(d) for d in allowed_dirs]
        else:
            self.allowed_dirs = [os.path.realpath(os.getcwd())]
        self.strict = strict
        self.max_file_size = max_file_size
        self.max_output_size = max_output_size
        self.audit_log: list[dict] = []
        # Callback for runtime path approval. When set, called with (resolved_path, operation)
        # before denying access. If it returns True, the directory is added to allowed_dirs.
        self.on_path_denied: callable = None

    def validate_path(self, path: str, operation: str = "read") -> dict:
        """Validate a file path for security.

        Checks:
        1. Protected file check (MEMORY.md immutable at runtime)
        2. Path resolves within allowed directories (strict mode — default)
        3. No symlink escape
        4. File size within limits (for reads)
        """
        try:
            resolved = os.path.realpath(path)
        except (OSError, ValueError) as e:
            return {"ok": False, "error": f"Invalid path: {e}"}

        # Windows path hardening (Archie audit round 2)
        # Block UNC paths, device paths, alternate data streams, short names
        raw = path.replace("/", "\\")
        if raw.startswith("\\\\"):
            self._audit("unc_path_blocked", path, "UNC path attempt")
            return {"ok": False, "error": f"UNC paths not allowed: {path}"}
        if "\\\\?\\" in raw or raw.startswith("\\\\?\\"):
            self._audit("device_path_blocked", path, "Device path attempt")
            return {"ok": False, "error": f"Device paths not allowed: {path}"}
        if ":" in os.path.splitdrive(path)[1]:
            # Alternate data stream: file.txt:stream (colon after drive letter split)
            self._audit("ads_blocked", path, "Alternate data stream attempt")
            return {"ok": False, "error": f"Alternate data streams not allowed: {path}"}
        if "~" in os.path.basename(path):
            # Short name like PROGRA~1 — resolve and compare
            if os.path.basename(path) != os.path.basename(resolved):
                self._audit("short_name_blocked", path,
                            f"Short name resolves to: {resolved}")
                return {"ok": False, "error": f"Short file names not allowed: {path}. Use full path."}

        # NTFS reserved device name check (Archie extended suite)
        # Strip extension for check: CON.txt → CON, NUL → NUL
        basename_raw = os.path.basename(resolved)
        basename_stem = os.path.splitext(basename_raw)[0].lower()
        if basename_stem in _NTFS_RESERVED_NAMES:
            self._audit("ntfs_reserved_blocked", path,
                        f"NTFS reserved device name: {basename_stem}")
            return {
                "ok": False,
                "error": f"NTFS reserved device name not allowed: {basename_raw}",
            }

        # Protected file check (V3 — memory poisoning defense)
        if operation in ("write", "edit"):
            basename = os.path.basename(resolved).lower()
            if basename in _PROTECTED_FILENAMES:
                self._audit("protected_file_blocked", path,
                            f"Write to protected file: {basename}")
                return {
                    "ok": False,
                    "error": f"Protected file — cannot modify {basename} at runtime. "
                             f"Use /learn for SEAL lessons instead.",
                }

            # Protected path patterns (XTI-06 — self-modification defense)
            resolved_lower = resolved.replace("\\", "/").lower()
            for pattern in _PROTECTED_PATH_PATTERNS:
                if pattern.replace("\\", "/").lower() in resolved_lower:
                    self._audit("protected_path_blocked", path,
                                f"Write to security-critical file: {pattern}")
                    return {
                        "ok": False,
                        "error": f"Security-critical file — cannot modify {pattern} at runtime.",
                    }

            # Blocked write locations (auto-execution defense — Archie round 2)
            for blocked_dir in _BLOCKED_WRITE_PATTERNS:
                if blocked_dir.replace("\\", "/").lower() in resolved_lower:
                    self._audit("autoexec_path_blocked", path,
                                f"Write to auto-execution location: {blocked_dir}")
                    return {
                        "ok": False,
                        "error": f"Cannot write to auto-execution location: {path}",
                    }

            # Blocked executable extensions (Archie round 2)
            ext = os.path.splitext(resolved)[1].lower()
            if ext in _BLOCKED_WRITE_EXTENSIONS:
                self._audit("executable_ext_blocked", path,
                            f"Write to executable file type: {ext}")
                return {
                    "ok": False,
                    "error": f"Cannot write executable file type ({ext}): {path}",
                }

        # Sensitive file warning for reads (data exfil defense — Archie round 2)
        if operation == "read":
            basename = os.path.basename(resolved)
            for pattern in _SENSITIVE_FILE_PATTERNS:
                if pattern.search(basename):
                    self._audit("sensitive_file_read", path,
                                f"Sensitive file accessed: {basename}")
                    # Don't block — but flag it. The tool_protocol anchor will warn the model.
                    break

        # Check path confinement (strict mode is default)
        if self.strict:
            in_allowed = any(
                resolved.startswith(d + os.sep) or resolved == d
                for d in self.allowed_dirs
            )
            if not in_allowed:
                # Runtime approval callback — ask operator before denying
                approved = False
                if self.on_path_denied is not None:
                    try:
                        approved = self.on_path_denied(resolved, operation)
                    except Exception:
                        approved = False
                if approved:
                    # Add the parent directory for this session
                    new_dir = os.path.dirname(resolved) if os.path.isfile(resolved) else resolved
                    new_dir = os.path.realpath(new_dir)
                    if new_dir not in self.allowed_dirs:
                        self.allowed_dirs.append(new_dir)
                        self._audit("path_approved_runtime", path,
                                    f"Operator approved: {new_dir}")
                else:
                    self._audit("path_blocked", path, f"Outside allowed dirs: {resolved}")
                    return {
                        "ok": False,
                        "error": f"Path outside allowed directories: {path}",
                    }

        # Symlink check
        if os.path.islink(path):
            self._audit("symlink_detected", path, f"Resolves to: {resolved}")
            in_allowed = any(
                resolved.startswith(d + os.sep) or resolved == d
                for d in self.allowed_dirs
            )
            if not in_allowed:
                return {"ok": False, "error": f"Symlink escapes allowed directory: {path}"}

        # File size check for reads
        if operation == "read" and os.path.exists(resolved):
            try:
                size = os.path.getsize(resolved)
                if size > self.max_file_size:
                    return {
                        "ok": False,
                        "error": f"File too large ({size:,} bytes, max {self.max_file_size:,}): {path}",
                    }
            except OSError:
                pass

        return {"ok": True, "resolved_path": resolved}

    def validate_command(self, command: str) -> dict:
        """Validate a shell command for security.

        Four-phase validation:
        0. Normalize (strip Unicode tricks, collapse whitespace)
        1. Reject shell operators (&&, ||, ;, |, backtick, $())
        2. Command must match at least one allowlist prefix
        3. Command must NOT match any blocklist pattern
        """
        # Phase 0: Normalize (V7 — Unicode/multiline evasion defense)
        cmd_normalized = _normalize_command(command)

        # Phase 1: Shell operator check (V2 — command chaining defense)
        for pattern in _SHELL_OPERATOR_RE:
            if pattern.search(cmd_normalized):
                self._audit("shell_operator_blocked", command,
                            f"Matched operator: {pattern.pattern}")
                return {
                    "ok": False,
                    "error": "Blocked: shell operators (&&, ||, ;, |, backtick, $()) "
                             "are not permitted. Use one command at a time.",
                }

        # Phase 2: Allowlist check — command must start with an approved prefix
        cmd_stripped = cmd_normalized
        allowed = False
        for prefix in _ALLOWED_COMMAND_PREFIXES:
            if cmd_stripped.startswith(prefix) or cmd_stripped == prefix.strip():
                allowed = True
                break

        if not allowed:
            self._audit("command_not_allowlisted", command, "No matching allowlist prefix")
            return {
                "ok": False,
                "error": f"Command not in allowlist. Only approved commands are permitted. "
                         f"Use /run in the YOPJ terminal for direct command execution.",
            }

        # Phase 2.5: Argument path confinement (Zephyr audit — bash_exec path escape)
        # Commands that take file/dir path arguments must have those args confined
        # to allowed_dirs, same as file_read/file_write already do.
        path_cmd_result = self._check_command_path_args(cmd_stripped)
        if path_cmd_result is not None:
            return path_cmd_result

        # Phase 2.6: mv/cp destination extension check (Zephyr audit — rename bypass)
        # Extension blocking only fires on file_write/file_edit validate_path.
        # mv/cp via bash_exec bypass it. Check destination extension here.
        mv_cp_match = re.match(
            r'^(?:mv|cp)\s+.+\s+["\']?(.+?)["\']?\s*$', cmd_stripped
        )
        if mv_cp_match:
            dest = mv_cp_match.group(1).strip().strip("'\"")
            dest_ext = os.path.splitext(dest)[1].lower()
            if dest_ext in _BLOCKED_WRITE_EXTENSIONS:
                self._audit("mv_cp_ext_blocked", command,
                            f"Rename/copy to executable extension: {dest_ext}")
                return {
                    "ok": False,
                    "error": f"Blocked: cannot rename/copy to executable extension ({dest_ext}).",
                }

        # Phase 3: Blocklist check — even allowed commands can be blocked
        # Check BOTH original and normalized (catch evasion in both forms)
        for pattern in _BLOCKED_RE:
            if pattern.search(cmd_normalized) or pattern.search(command):
                self._audit("command_blocked", command,
                            f"Matched blocklist: {pattern.pattern}")
                return {
                    "ok": False,
                    "error": f"Blocked: command matches dangerous pattern.",
                }

        return {"ok": True}

    def truncate_output(self, output: str) -> str:
        """Truncate output to max_output_size."""
        if len(output) > self.max_output_size:
            truncated = output[:self.max_output_size]
            return truncated + f"\n[...truncated at {self.max_output_size:,} chars]"
        return output

    def get_audit_log(self) -> list[dict]:
        """Return the audit log."""
        return list(self.audit_log)

    # Commands whose arguments should be path-confined to allowed_dirs.
    # Maps command prefix → list of argument positions that are paths.
    # "all" means every non-flag argument is treated as a path.
    _PATH_ARG_COMMANDS = {
        "ls": "all", "dir": "all", "tree": "all",
        "cat": "all", "head": "all", "tail": "all",
        "less": "all", "more": "all", "type": "all",
        "find": "first",   # find <path> -name ... — first arg is path
        "grep": "last",    # grep [flags] pattern path — last arg(s) are paths
        "rg": "last",
        "ag": "last",
        "wc": "all", "sort": "all", "uniq": "all",
        "diff": "all", "file": "all", "stat": "all",
        "du": "all", "df": "all",
        "cp": "all", "mv": "all",
        "mkdir": "all", "touch": "all",
    }

    def _check_command_path_args(self, cmd: str) -> dict | None:
        """Check whether path arguments in a command stay within allowed_dirs.

        Returns an error dict if a path escapes confinement, or None if OK.
        """
        parts = cmd.split()
        if not parts:
            return None

        # Get the base command (strip leading path if any)
        base_cmd = os.path.basename(parts[0]).lower()

        # Handle "git" subcommands — git is already gated by allowlist
        if base_cmd == "git":
            return None

        rule = self._PATH_ARG_COMMANDS.get(base_cmd)
        if rule is None:
            return None

        # Extract non-flag arguments (skip -x, --flag style args)
        args = [a.strip("'\"") for a in parts[1:] if not a.startswith("-")]

        if not args:
            return None

        if rule == "first":
            paths_to_check = [args[0]]
        elif rule == "last":
            # For grep/rg: last non-flag arg(s) are paths, first is pattern
            # Skip the pattern (first non-flag arg)
            paths_to_check = args[1:] if len(args) > 1 else []
        else:  # "all"
            paths_to_check = args

        for path_arg in paths_to_check:
            if not path_arg:
                continue
            try:
                resolved = os.path.realpath(path_arg)
            except (OSError, ValueError):
                continue

            in_allowed = any(
                resolved.startswith(d + os.sep) or resolved == d
                for d in self.allowed_dirs
            )
            if not in_allowed:
                self._audit("path_arg_blocked", cmd,
                            f"Argument '{path_arg}' resolves outside sandbox: {resolved}")
                return {
                    "ok": False,
                    "error": f"Blocked: path argument '{path_arg}' is outside the allowed directory.",
                }

        return None

    def _audit(self, event: str, target: str, detail: str = "") -> None:
        """Record a security event."""
        self.audit_log.append({
            "event": event,
            "target": target[:200],
            "detail": detail[:200],
            "timestamp": time.time(),
        })


# ============================================================
# Module-level singleton for use by tools
# ============================================================

_sandbox: Sandbox | None = None


def get_sandbox() -> Sandbox:
    """Get the global sandbox instance. Creates a STRICT default if not configured."""
    global _sandbox
    if _sandbox is None:
        _sandbox = Sandbox(strict=True)
    return _sandbox


def configure_sandbox(
    allowed_dirs: list[str] = None,
    strict: bool = True,
    max_file_size: int = MAX_FILE_SIZE,
    max_output_size: int = MAX_OUTPUT_SIZE,
) -> Sandbox:
    """Configure and set the global sandbox instance."""
    global _sandbox
    _sandbox = Sandbox(
        allowed_dirs=allowed_dirs,
        strict=strict,
        max_file_size=max_file_size,
        max_output_size=max_output_size,
    )
    return _sandbox
