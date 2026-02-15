"""Server interface for YOPJ — connects to a running llama-server over HTTP.

Instead of spawning a new llama-cli process per turn (7.5s model load each time),
this connects to a persistent llama-server that keeps the model loaded in memory.
Uses the OpenAI-compatible /v1/chat/completions endpoint.

Typical latency: ~2-3s per turn (vs ~10s with llama-cli subprocess).
"""

import json
import time
import urllib.request
import urllib.error


class ServerInterface:
    """Interface to a local LLM via llama-server HTTP API."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        temp: float = 0.2,
        top_p: float = 0.9,
        top_k: int = 40,
        repeat_penalty: float = 1.2,
        n_predict: int = 4096,
        timeout_seconds: int = 300,
        stop_tokens: list[str] = None,
    ):
        self.base_url = f"http://{host}:{port}"
        self.temp = temp
        self.top_p = top_p
        self.top_k = top_k
        self.repeat_penalty = repeat_penalty
        self.n_predict = n_predict
        self.timeout_seconds = timeout_seconds
        self.stop_tokens = stop_tokens or ["<|im_end|>", "<|im_start|>"]

    def health_check(self) -> bool:
        """Check if the server is running and model is loaded."""
        try:
            req = urllib.request.Request(f"{self.base_url}/health")
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read())
            return data.get("status") == "ok"
        except Exception:
            return False

    def get_model_info(self) -> dict | None:
        """Query the server for model information.

        Returns dict with model_name, ctx_size, etc. or None on failure.
        """
        # Try /props first (llama.cpp native)
        for endpoint in ("/props", "/v1/models"):
            try:
                req = urllib.request.Request(f"{self.base_url}{endpoint}")
                resp = urllib.request.urlopen(req, timeout=5)
                data = json.loads(resp.read())
                if endpoint == "/props":
                    return {
                        "model": data.get("default_generation_settings", {}).get("model", "unknown"),
                        "ctx_size": data.get("default_generation_settings", {}).get("n_ctx", 0),
                    }
                elif endpoint == "/v1/models":
                    models = data.get("data", [])
                    if models:
                        return {"model": models[0].get("id", "unknown")}
            except Exception:
                continue
        return None

    def reconnect(self, max_attempts: int = 3, delay: float = 2.0) -> bool:
        """Try to reconnect to the server with retries.

        Args:
            max_attempts: Number of reconnection attempts.
            delay: Seconds between attempts.

        Returns:
            True if reconnected, False if all attempts failed.
        """
        for attempt in range(1, max_attempts + 1):
            if self.health_check():
                return True
            if attempt < max_attempts:
                time.sleep(delay)
        return False

    def generate(self, prompt: str, system_prompt: str = None) -> dict:
        """Generate a response using /completion endpoint (raw prompt mode).

        Args:
            prompt: The full ChatML prompt string.
            system_prompt: Ignored (kept for API compatibility with ModelInterface).

        Returns dict with ok, text, duration_ms, returncode.
        """
        payload = {
            "prompt": prompt,
            "n_predict": self.n_predict,
            "temperature": self.temp,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repeat_penalty": self.repeat_penalty,
            "stream": False,
            "stop": self.stop_tokens,
        }

        t0 = time.time()
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/completion",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=self.timeout_seconds)
            result = json.loads(resp.read())
            duration_ms = int((time.time() - t0) * 1000)

            text = result.get("content", "").strip()
            return {
                "ok": True,
                "text": text,
                "duration_ms": duration_ms,
                "returncode": 0,
            }

        except urllib.error.URLError as e:
            duration_ms = int((time.time() - t0) * 1000)
            return {
                "ok": False,
                "text": "",
                "error": f"Server connection failed: {e.reason}",
                "duration_ms": duration_ms,
                "returncode": -1,
            }
        except TimeoutError:
            duration_ms = int((time.time() - t0) * 1000)
            return {
                "ok": False,
                "text": "",
                "error": f"Server timed out after {self.timeout_seconds}s",
                "duration_ms": duration_ms,
                "returncode": -1,
            }
        except Exception as e:
            duration_ms = int((time.time() - t0) * 1000)
            return {
                "ok": False,
                "text": "",
                "error": f"{type(e).__name__}: {e}",
                "duration_ms": duration_ms,
                "returncode": -1,
            }

    def generate_stream(self, prompt: str, callback=None):
        """Generate with streaming — tokens arrive via server-sent events.

        Args:
            prompt: Full ChatML prompt.
            callback: Optional callable(chunk: str) for each text chunk.

        Returns dict with ok, text, duration_ms, returncode.
        """
        payload = {
            "prompt": prompt,
            "n_predict": self.n_predict,
            "temperature": self.temp,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repeat_penalty": self.repeat_penalty,
            "stream": True,
            "stop": self.stop_tokens,
        }

        t0 = time.time()
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/completion",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=self.timeout_seconds)

            # Read server-sent events
            chunks = []
            for line in resp:
                line = line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue

                json_str = line[6:]  # Strip "data: " prefix
                if json_str == "[DONE]":
                    break

                try:
                    event = json.loads(json_str)
                    token = event.get("content", "")
                    if token:
                        chunks.append(token)
                        if callback:
                            callback(token)
                except json.JSONDecodeError:
                    continue

            duration_ms = int((time.time() - t0) * 1000)
            text = "".join(chunks).strip()

            return {
                "ok": True,
                "text": text,
                "duration_ms": duration_ms,
                "returncode": 0,
            }

        except urllib.error.URLError as e:
            duration_ms = int((time.time() - t0) * 1000)
            return {
                "ok": False,
                "text": "",
                "error": f"Server connection failed: {e.reason}",
                "duration_ms": duration_ms,
                "returncode": -1,
            }
        except Exception as e:
            duration_ms = int((time.time() - t0) * 1000)
            return {
                "ok": False,
                "text": "",
                "error": f"{type(e).__name__}: {e}",
                "duration_ms": duration_ms,
                "returncode": -1,
            }
