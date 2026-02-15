"""Structured audit logging for YOPJ sessions.

Logs all tool calls, model interactions, errors, and session events to a
JSONL (JSON Lines) file. Each line is a self-contained JSON object.

Log files are written to the working directory as .yopj-audit-YYYYMMDD-HHMMSS.jsonl.
"""

import json
import os
import time
from datetime import datetime, timezone


class AuditLog:
    """Append-only structured logger for session events."""

    def __init__(self, log_dir: str = "."):
        """Initialize audit logger.

        Args:
            log_dir: Directory to write log files. Defaults to cwd.
        """
        self.log_dir = log_dir
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.log_path = os.path.join(log_dir, f".yopj-audit-{ts}.jsonl")
        self._session_id = ts
        self._event_count = 0
        self._start_time = time.time()
        self._file = None

    def _ensure_open(self):
        """Lazily open the log file on first write."""
        if self._file is None:
            os.makedirs(self.log_dir, exist_ok=True)
            self._file = open(self.log_path, "a", encoding="utf-8")

    def _write(self, event_type: str, data: dict) -> None:
        """Write a single event to the log."""
        self._ensure_open()
        self._event_count += 1
        entry = {
            "seq": self._event_count,
            "ts": datetime.now(timezone.utc).isoformat(),
            "elapsed_s": round(time.time() - self._start_time, 2),
            "event": event_type,
            **data,
        }
        self._file.write(json.dumps(entry, separators=(",", ":")) + "\n")
        self._file.flush()

    def session_start(self, backend: str, template: str, model: str = "",
                      ctx_size: int = 0, plugins: list[str] = None) -> None:
        """Log session start with configuration."""
        self._write("session_start", {
            "session_id": self._session_id,
            "backend": backend,
            "template": template,
            "model": model,
            "ctx_size": ctx_size,
            "plugins": plugins or [],
        })

    def session_end(self, turns: int, tool_calls: int, error_rate: float) -> None:
        """Log session end with summary stats."""
        self._write("session_end", {
            "turns": turns,
            "tool_calls": tool_calls,
            "error_rate": round(error_rate, 1),
            "duration_s": round(time.time() - self._start_time, 1),
        })
        self.close()

    def tool_call(self, name: str, args: str, ok: bool, duration_ms: int,
                  error: str = "", round_num: int = 0) -> None:
        """Log a tool execution."""
        self._write("tool_call", {
            "tool": name,
            "args": args[:500],
            "ok": ok,
            "duration_ms": duration_ms,
            "error": error[:300] if error else "",
            "round": round_num,
        })

    def generation(self, tokens_est: int, duration_ms: int, ok: bool,
                   error: str = "", rounds: int = 1) -> None:
        """Log a model generation."""
        self._write("generation", {
            "tokens_est": tokens_est,
            "duration_ms": duration_ms,
            "ok": ok,
            "error": error[:300] if error else "",
            "rounds": rounds,
        })

    def permission_check(self, tool: str, allowed: bool, mode: str) -> None:
        """Log a permission decision."""
        self._write("permission", {
            "tool": tool,
            "allowed": allowed,
            "mode": mode,
        })

    def sandbox_block(self, tool: str, reason: str, args: str = "") -> None:
        """Log a sandbox block event."""
        self._write("sandbox_block", {
            "tool": tool,
            "reason": reason[:300],
            "args": args[:200],
        })

    def error(self, source: str, message: str) -> None:
        """Log an error."""
        self._write("error", {
            "source": source,
            "message": message[:500],
        })

    def command(self, cmd: str) -> None:
        """Log a slash command."""
        self._write("command", {"cmd": cmd})

    def confab_flag(self, heuristic: str, severity: str, detail: str) -> None:
        """Log a confabulation detection."""
        self._write("confab", {
            "heuristic": heuristic,
            "severity": severity,
            "detail": detail[:300],
        })

    def context_pressure(self, total_tokens: int, headroom: int,
                         compressed: int) -> None:
        """Log context window pressure."""
        self._write("context_pressure", {
            "total_tokens": total_tokens,
            "headroom": headroom,
            "compressed_msgs": compressed,
        })

    def close(self) -> None:
        """Flush and close the log file."""
        if self._file is not None:
            self._file.flush()
            self._file.close()
            self._file = None

    @property
    def event_count(self) -> int:
        return self._event_count

    @property
    def session_id(self) -> str:
        return self._session_id
