"""Session-based learning for YOPJ.

Tracks session patterns and enables lesson creation from conversations.
Two modes:
1. Auto-detect: Finds tool-failure→success sequences, high-round-count answers, etc.
2. Manual: /learn command lets users capture specific insights.

Lessons are stored via seal_store.py in SEAL v1.0 format.
"""

import os
import re
from datetime import datetime, timezone


class SessionLearner:
    """Tracks conversation patterns and creates SEAL lessons."""

    def __init__(self, lessons_dir: str, prefix: str = "JEANLUC"):
        self.lessons_dir = lessons_dir
        self.prefix = prefix
        # Session tracking
        self.tool_calls = []        # List of {"name", "args", "ok", "error", "round"}
        self.round_counts = []      # Rounds per user question
        self.current_round = 0
        self.turn_count = 0

    def record_tool_call(self, name: str, args: str, ok: bool, error: str = "", round_num: int = 0):
        """Record a tool call outcome for pattern detection."""
        self.tool_calls.append({
            "name": name,
            "args": args[:200],
            "ok": ok,
            "error": error[:200] if error else "",
            "round": round_num,
            "turn": self.turn_count,
        })

    def record_turn_complete(self, rounds_used: int):
        """Record how many rounds a user question took to answer."""
        self.round_counts.append(rounds_used)
        self.turn_count += 1

    def detect_patterns(self) -> list[dict]:
        """Analyze session data for learnable patterns.

        Returns a list of pattern dicts, each with:
            type: "tool_retry_success" | "high_round_count" | "repeated_error"
            detail: Human-readable description
            evidence: Dict suitable for SEAL evidence array
        """
        patterns = []

        # Pattern 1: Tool failure → same tool success later in same turn
        by_turn = {}
        for tc in self.tool_calls:
            by_turn.setdefault(tc["turn"], []).append(tc)

        for turn, calls in by_turn.items():
            failed_tools = {}
            for c in calls:
                if not c["ok"]:
                    failed_tools.setdefault(c["name"], []).append(c)
            for c in calls:
                if c["ok"] and c["name"] in failed_tools:
                    patterns.append({
                        "type": "tool_retry_success",
                        "detail": f"Tool '{c['name']}' failed then succeeded in turn {turn}. "
                                  f"Error was: {failed_tools[c['name']][0]['error']}",
                        "evidence": {
                            "type": "observation",
                            "source": "session_learner",
                            "detail": f"Tool {c['name']} failed ({failed_tools[c['name']][0]['error']}) "
                                      f"then succeeded with args: {c['args'][:100]}",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                    })

        # Pattern 2: Questions that took 4+ rounds (model struggled)
        for i, rounds in enumerate(self.round_counts):
            if rounds >= 4:
                patterns.append({
                    "type": "high_round_count",
                    "detail": f"Question {i+1} took {rounds} rounds to answer. "
                              f"Model may need better system prompt guidance for this task type.",
                    "evidence": {
                        "type": "metric",
                        "source": "session_learner",
                        "detail": f"Turn {i+1} required {rounds} tool rounds",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                })

        # Pattern 3: Same tool failing repeatedly with same error
        error_counts = {}
        for tc in self.tool_calls:
            if not tc["ok"] and tc["error"]:
                key = (tc["name"], tc["error"][:80])
                error_counts[key] = error_counts.get(key, 0) + 1

        for (name, error), count in error_counts.items():
            if count >= 2:
                patterns.append({
                    "type": "repeated_error",
                    "detail": f"Tool '{name}' failed {count} times with: {error}",
                    "evidence": {
                        "type": "observation",
                        "source": "session_learner",
                        "detail": f"Repeated failure ({count}x): {name} — {error}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                })

        return patterns

    def get_session_stats(self) -> dict:
        """Return session statistics."""
        total_calls = len(self.tool_calls)
        ok_calls = sum(1 for tc in self.tool_calls if tc["ok"])
        failed_calls = total_calls - ok_calls
        avg_rounds = (sum(self.round_counts) / len(self.round_counts)) if self.round_counts else 0

        tools_used = {}
        for tc in self.tool_calls:
            tools_used[tc["name"]] = tools_used.get(tc["name"], 0) + 1

        return {
            "turns": self.turn_count,
            "total_tool_calls": total_calls,
            "successful_calls": ok_calls,
            "failed_calls": failed_calls,
            "error_rate": (failed_calls / total_calls * 100) if total_calls else 0,
            "avg_rounds_per_turn": round(avg_rounds, 1),
            "tools_used": tools_used,
        }

    def create_lesson_from_input(
        self,
        topic: str,
        insight: str,
        category: str = "technical_insight",
        tags: list[str] = None,
    ) -> dict:
        """Create a SEAL lesson from user-provided description.

        Used by the /learn command.
        """
        from learning.seal_store import create_lesson

        # Build evidence from session stats
        stats = self.get_session_stats()
        evidence = [{
            "type": "observation",
            "source": "yopj_session",
            "detail": (f"Session with {stats['turns']} turns, "
                       f"{stats['total_tool_calls']} tool calls "
                       f"({stats['error_rate']:.0f}% error rate)"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]

        # Add any detected patterns as evidence
        for pattern in self.detect_patterns():
            evidence.append(pattern["evidence"])

        # Trim summary to 15 words
        words = topic.split()
        summary = " ".join(words[:15])

        return create_lesson(
            lessons_dir=self.lessons_dir,
            prefix=self.prefix,
            topic=topic,
            summary=summary,
            category=category,
            insight=insight,
            confidence=0.6,  # Default for session-derived lessons
            evidence=evidence,
            tags=tags or [],
        )
