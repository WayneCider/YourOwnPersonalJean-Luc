"""Context manager for YOPJ — tracks conversation and token budget.

Manages the conversation history, tracks approximate token count,
and handles context window limits with smart compression:
1. Compress consumed tool results (model already responded → shrink to summary)
2. Truncate middle conversation (keep first + last exchanges intact)
3. Drop oldest messages as last resort

Also maintains a file cache to avoid re-reading recently accessed files.
"""

import re
import time


# Rough approximation: 1 token ~ 4 characters for English text
CHARS_PER_TOKEN = 4

# Tool result summary pattern
_TOOL_RESULT_RE = re.compile(
    r'\[TOOL_RESULT\s+(\w+)\](.*?)\[/TOOL_RESULT\]',
    re.DOTALL,
)

# How many recent messages to keep at full fidelity
TAIL_PRESERVE = 6  # ~3 exchanges (user+assistant or user+tool_result+assistant)

# How many messages at the start to keep at full fidelity
HEAD_PRESERVE = 2  # First user question + first response

# Max chars for truncated middle messages
MIDDLE_TRUNCATE_CHARS = 400


class ContextManager:
    """Manages conversation context and token budget."""

    def __init__(self, max_tokens: int = 8192, reserved_tokens: int = 1024):
        """Initialize context manager.

        Args:
            max_tokens: Maximum context window size in tokens.
            reserved_tokens: Tokens reserved for system prompt + generation headroom.
        """
        self.max_tokens = max_tokens
        self.reserved_tokens = reserved_tokens
        self.messages: list[dict] = []
        self.file_cache: dict[str, dict] = {}  # path -> {content, timestamp, tokens}
        self._system_prompt: str = ""
        self._system_tokens: int = 0
        self._running_summary: list[str] = []
        self._context_summary: list[str] = []  # Running summary of dropped context

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt (counted against token budget)."""
        self._system_prompt = prompt
        self._system_tokens = self._estimate_tokens(prompt)

    def add_message(self, role: str, content: str) -> None:
        """Add a message to conversation history."""
        tokens = self._estimate_tokens(content)
        self.messages.append({
            "role": role,
            "content": content,
            "tokens": tokens,
            "timestamp": time.time(),
            "compressed": False,
        })
        # Eagerly compress consumed tool results on every assistant message
        # (don't wait for budget overflow — proactive compression preserves more context)
        if role == "assistant":
            self._compress_tool_results()
        self._enforce_budget()

    def get_messages(self) -> list[dict]:
        """Return current conversation messages (role, content only)."""
        return [{"role": m["role"], "content": m["content"]} for m in self.messages]

    def get_token_usage(self) -> dict:
        """Return current token usage stats."""
        message_tokens = self._message_tokens()
        total = self._system_tokens + message_tokens
        available = self.max_tokens - self.reserved_tokens
        compressed = sum(1 for m in self.messages if m.get("compressed"))
        return {
            "system_tokens": self._system_tokens,
            "message_tokens": message_tokens,
            "total_tokens": total,
            "available_tokens": available,
            "headroom": max(0, available - total),
            "message_count": len(self.messages),
            "compressed_count": compressed,
        }

    def cache_file(self, path: str, content: str) -> None:
        """Cache file content to avoid re-reading."""
        self.file_cache[path] = {
            "content": content,
            "timestamp": time.time(),
            "tokens": self._estimate_tokens(content),
        }

    def get_cached_file(self, path: str, max_age_seconds: int = 300) -> str | None:
        """Get cached file content if fresh enough."""
        entry = self.file_cache.get(path)
        if entry is None:
            return None
        if time.time() - entry["timestamp"] > max_age_seconds:
            del self.file_cache[path]
            return None
        return entry["content"]

    def clear(self) -> None:
        """Clear all conversation history and file cache."""
        self.messages.clear()
        self.file_cache.clear()

    def compress(self) -> None:
        """Manually trigger context compression (all 3 phases)."""
        self._compress_tool_results()
        self._truncate_middle()
        # Phase 3: summarize everything except the last few messages
        available = self.max_tokens - self.reserved_tokens - self._system_tokens
        while len(self.messages) > 4 and self._message_tokens() > available * 0.7:
            dropped = self.messages.pop(0)
            self._absorb_into_summary(dropped)
        if self._running_summary:
            self._inject_summary()

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count using word + punctuation heuristic.

        More accurate than simple char/4 division:
        - Words ≈ 1-2 tokens each (short words 1, long words 2+)
        - Punctuation and special chars are often separate tokens
        - Code identifiers with underscores split into multiple tokens
        """
        if not text:
            return 0
        # Split on whitespace to get words, then estimate
        words = text.split()
        token_count = 0
        for word in words:
            if len(word) <= 4:
                token_count += 1
            elif len(word) <= 10:
                token_count += 2
            else:
                # Long words (paths, URLs, identifiers) get split more
                token_count += max(2, len(word) // 4)
        # Add tokens for newlines and structural characters
        token_count += text.count("\n")
        return max(1, token_count)

    def _message_tokens(self) -> int:
        """Total tokens across all messages."""
        return sum(m["tokens"] for m in self.messages)

    def _enforce_budget(self) -> None:
        """Remove/compress messages to fit token budget.

        Three-phase strategy (each phase only runs if still over budget):
        1. Compress consumed tool results (already processed by model)
        2. Truncate middle messages (keep head + tail intact)
        3. Drop oldest messages as last resort
        """
        available = self.max_tokens - self.reserved_tokens - self._system_tokens

        if self._message_tokens() <= available:
            return

        # Phase 1: Compress consumed tool results
        self._compress_tool_results()

        if self._message_tokens() <= available:
            return

        # Phase 2: Truncate middle messages
        self._truncate_middle()

        if self._message_tokens() <= available:
            return

        # Phase 3: Summarize and drop oldest (last resort)
        while self.messages and self._message_tokens() > available:
            dropped = self.messages.pop(0)
            self._absorb_into_summary(dropped)
        self._inject_summary()

    def _compress_tool_results(self) -> None:
        """Compress tool_result messages that have been consumed.

        A tool result is "consumed" when an assistant message follows it
        (meaning the model has already processed the result and responded).
        Compressed form: [TOOL_RESULT name](N lines, M chars)[/TOOL_RESULT]
        """
        for i, msg in enumerate(self.messages):
            if msg["role"] != "tool_result":
                continue
            if msg.get("compressed"):
                continue

            # Check if an assistant message follows this tool result
            # (possibly after other tool_results in the same batch)
            has_response = False
            for j in range(i + 1, len(self.messages)):
                if self.messages[j]["role"] == "assistant":
                    has_response = True
                    break
                if self.messages[j]["role"] == "user":
                    # New user turn without assistant response — consumed by inference
                    has_response = True
                    break

            if not has_response:
                continue  # Not yet consumed, keep full content

            # Compress the tool result
            content = msg["content"]
            compressed = _compress_tool_result_content(content)
            if len(compressed) < len(content):
                msg["content"] = compressed
                msg["tokens"] = self._estimate_tokens(compressed)
                msg["compressed"] = True

    def _absorb_into_summary(self, msg: dict) -> None:
        """Extract key facts from a message being dropped and add to running summary."""
        role = msg["role"]
        content = msg["content"]

        if role == "user":
            # Keep user questions (they're usually short and define task context)
            text = content.strip()
            if len(text) > 200:
                text = text[:197] + "..."
            self._context_summary.append(f"User asked: {text}")

        elif role == "assistant":
            # Extract key statements: file paths, decisions, results
            facts = _extract_facts(content)
            for fact in facts:
                self._context_summary.append(fact)

        elif role == "tool_result":
            # Extract tool name and outcome
            match = _TOOL_RESULT_RE.search(content)
            if match:
                tool_name = match.group(1)
                body = match.group(2).strip()
                ok = "error" not in body.lower()[:100]
                lines = body.count('\n') + 1
                status = "ok" if ok else "error"
                self._context_summary.append(f"Tool {tool_name}: {status} ({lines} lines)")

        # Cap summary size
        max_summary_items = 30
        if len(self._context_summary) > max_summary_items:
            self._context_summary = self._context_summary[-max_summary_items:]

    def _inject_summary(self) -> None:
        """Inject the running summary as the first message if we have one."""
        if not self._context_summary:
            return

        summary_text = "[Context from earlier in session]\n" + "\n".join(self._context_summary)

        # Check if first message is already a summary — update it
        if self.messages and self.messages[0].get("_is_summary"):
            self.messages[0]["content"] = summary_text
            self.messages[0]["tokens"] = self._estimate_tokens(summary_text)
        else:
            # Insert new summary message at start
            self.messages.insert(0, {
                "role": "user",
                "content": summary_text,
                "tokens": self._estimate_tokens(summary_text),
                "timestamp": time.time(),
                "compressed": True,
                "_is_summary": True,
            })

    def _truncate_middle(self) -> None:
        """Truncate messages in the middle of the conversation.

        Keeps HEAD_PRESERVE messages at the start and TAIL_PRESERVE at the end
        at full fidelity. Middle messages get truncated to MIDDLE_TRUNCATE_CHARS.
        """
        n = len(self.messages)
        if n <= HEAD_PRESERVE + TAIL_PRESERVE:
            return  # Too few messages to have a "middle"

        for i in range(HEAD_PRESERVE, n - TAIL_PRESERVE):
            msg = self.messages[i]
            content = msg["content"]
            if len(content) <= MIDDLE_TRUNCATE_CHARS:
                continue
            if msg.get("compressed"):
                continue  # Already compressed

            # Truncate with marker
            role = msg["role"]
            if role == "tool_result":
                # Tool results: compress to summary
                truncated = _compress_tool_result_content(content)
            elif role == "assistant":
                # Assistant: keep first N chars + truncation marker
                truncated = content[:MIDDLE_TRUNCATE_CHARS] + "\n[...truncated...]"
            else:
                # User messages: keep full (they're usually short)
                continue

            msg["content"] = truncated
            msg["tokens"] = self._estimate_tokens(truncated)
            msg["compressed"] = True


# Patterns for extracting facts from assistant messages
_FILE_PATH_RE = re.compile(r'(?:^|\s)([A-Za-z]:\\[\w\\./\-]+|/[\w/.\-]+\.\w+)', re.MULTILINE)
_TOOL_CALL_RE = re.compile(r'::\s*(?:TOOL\s+)?(\w+)\(', re.IGNORECASE)


def _extract_facts(text: str) -> list[str]:
    """Extract key facts from an assistant message for context summary.

    Extracts: file paths mentioned, tool calls made, and first sentence of response.
    """
    facts = []

    # Extract file paths mentioned
    paths = set(_FILE_PATH_RE.findall(text))
    if paths:
        path_list = ", ".join(sorted(paths)[:5])
        facts.append(f"Files mentioned: {path_list}")

    # Extract tool calls
    tools = _TOOL_CALL_RE.findall(text)
    if tools:
        facts.append(f"Tools called: {', '.join(tools)}")

    # First meaningful sentence (skip tool calls and code)
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        if line.startswith('::') or line.startswith('[TOOL') or line.startswith('```'):
            continue
        if len(line) > 20:
            if len(line) > 150:
                line = line[:147] + "..."
            facts.append(f"Said: {line}")
            break

    return facts


def _compress_tool_result_content(content: str) -> str:
    """Compress a tool result string to a summary.

    Input:  [TOOL_RESULT file_read]  1| line one\n  2| line two\n...[/TOOL_RESULT]
    Output: [TOOL_RESULT file_read](47 lines, 1,204 chars)[/TOOL_RESULT]
    """
    match = _TOOL_RESULT_RE.search(content)
    if not match:
        # Not a standard format — just truncate
        if len(content) > MIDDLE_TRUNCATE_CHARS:
            return content[:MIDDLE_TRUNCATE_CHARS] + "\n[...truncated...]"
        return content

    tool_name = match.group(1)
    body = match.group(2).strip()
    line_count = body.count('\n') + (1 if body else 0)
    char_count = len(body)

    return f"[TOOL_RESULT {tool_name}]({line_count} lines, {char_count:,} chars)[/TOOL_RESULT]"
