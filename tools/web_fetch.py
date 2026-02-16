"""Fetch and extract text content from a URL for research purposes."""

import re
import html
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse


# Hard cap on response size (512KB) to prevent context flooding
MAX_RESPONSE_BYTES = 512 * 1024

# Allowed schemes — no file://, ftp://, etc.
ALLOWED_SCHEMES = {"http", "https"}

# Block private/internal network ranges
BLOCKED_HOSTS = {
    "localhost", "127.0.0.1", "0.0.0.0", "::1",
    "metadata.google.internal", "169.254.169.254",
}


def _is_private_host(hostname: str) -> bool:
    """Reject private/internal hosts to prevent SSRF."""
    if hostname in BLOCKED_HOSTS:
        return True
    # Block 10.x.x.x, 192.168.x.x, 172.16-31.x.x patterns
    if re.match(r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)", hostname):
        return True
    return False


def _strip_html(raw_html: str) -> str:
    """Convert HTML to readable plain text."""
    # Remove script and style blocks entirely
    text = re.sub(r"<script[^>]*>.*?</script>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
    # Convert common block elements to newlines
    text = re.sub(r"<(br|hr|/p|/div|/h[1-6]|/li|/tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Remove all remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode HTML entities
    text = html.unescape(text)
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def web_fetch(url: str, max_lines: int = 200) -> dict:
    """Fetch a URL and return its text content.

    Security: only allows http/https, blocks private networks (SSRF defense),
    caps response size, returns plain text only.

    Args:
        url: The URL to fetch (must be http or https).
        max_lines: Max lines of text to return. Default 200.

    Returns:
        dict with ok, content, url, lines_count, or ok=False with error.
    """
    # Validate URL scheme
    try:
        parsed = urlparse(url)
    except Exception:
        return {"ok": False, "error": f"Invalid URL: {url}"}

    if parsed.scheme not in ALLOWED_SCHEMES:
        return {"ok": False, "error": f"Scheme '{parsed.scheme}' not allowed. Use http or https."}

    if not parsed.hostname:
        return {"ok": False, "error": f"No hostname in URL: {url}"}

    # SSRF defense — block private/internal hosts
    if _is_private_host(parsed.hostname):
        return {"ok": False, "error": f"Blocked: private/internal host '{parsed.hostname}'"}

    # Fetch with timeout and size cap
    try:
        req = Request(url, headers={"User-Agent": "YOPJ-JeanLuc/1.0 (research-agent)"})
        with urlopen(req, timeout=30) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read(MAX_RESPONSE_BYTES)
    except HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
    except URLError as e:
        return {"ok": False, "error": f"URL error: {e.reason}"}
    except TimeoutError:
        return {"ok": False, "error": "Request timed out (30s)"}
    except Exception as e:
        return {"ok": False, "error": f"Fetch failed: {e}"}

    # Decode to text
    encoding = "utf-8"
    if "charset=" in content_type:
        match = re.search(r"charset=([\w-]+)", content_type)
        if match:
            encoding = match.group(1)

    try:
        text = raw.decode(encoding, errors="replace")
    except (LookupError, UnicodeDecodeError):
        text = raw.decode("utf-8", errors="replace")

    # Strip HTML if content-type suggests it
    if "html" in content_type.lower() or text.strip().startswith("<!") or text.strip().startswith("<html"):
        text = _strip_html(text)

    # Apply line limit
    lines = text.splitlines()
    total_lines = len(lines)
    truncated = total_lines > max_lines
    lines = lines[:max_lines]

    result = {
        "ok": True,
        "content": "\n".join(lines),
        "url": url,
        "lines_count": total_lines,
    }
    if truncated:
        result["truncated"] = True
        result["note"] = (
            f"Output capped at {max_lines} lines (page has {total_lines}). "
            f"Use max_lines to read more."
        )
    return result
