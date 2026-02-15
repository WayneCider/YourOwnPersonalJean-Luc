"""Model interface for YOPJ — spawns llama-cli and manages conversation turns.

Each call to generate() spawns a fresh llama-cli process with the full conversation
context as a prompt file. This is the single-shot pattern (proven in code_task_runner):
write prompt to temp file, pass via -f, capture stdout, clean up.

Uses stdin=DEVNULL to prevent llama-cli from blocking on interactive input.
Supports both batch (generate) and streaming (generate_stream) modes.
"""

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path


# Artifacts to strip from llama-cli output
_CLEANUP_PATTERNS = [
    (re.compile(r"\s*\[end of text\]\s*$", re.IGNORECASE), ""),
    (re.compile(r"\n*> EOF by user.*", re.DOTALL), ""),
]


class ModelInterface:
    """Interface to a local LLM via llama-cli subprocess."""

    def __init__(
        self,
        model_path: str,
        llama_cli_path: str = None,
        ctx_size: int = 8192,
        temp: float = 0.2,
        top_p: float = 0.9,
        top_k: int = 40,
        repeat_penalty: float = 1.2,
        n_predict: int = 4096,
        ngl: int = 99,
        timeout_seconds: int = 300,
        generation_prefix: str = None,
    ):
        self.model_path = model_path
        self.llama_cli_path = llama_cli_path or self._find_llama_cli()
        self.ctx_size = ctx_size
        self.temp = temp
        self.top_p = top_p
        self.top_k = top_k
        self.repeat_penalty = repeat_penalty
        self.n_predict = n_predict
        self.ngl = ngl
        self.timeout_seconds = timeout_seconds
        self.generation_prefix = generation_prefix or "<|im_start|>assistant\n"

    def _find_llama_cli(self) -> str:
        """Try to find llama-cli on PATH or in common locations."""
        from shutil import which
        for name in ("llama-cli", "llama-cli.exe"):
            found = which(name)
            if found:
                return found

        # Check common installation directories per platform
        import sys
        if sys.platform == "win32":
            candidates = list(Path.home().glob("Downloads/llama-*/llama-cli.exe"))
            candidates += list(Path("C:/llama.cpp/build/bin").glob("llama-cli.exe"))
        else:
            candidates = list(Path.home().glob("llama.cpp/build/bin/llama-cli"))
            candidates += list(Path("/usr/local/bin").glob("llama-cli"))

        for c in candidates:
            if c.exists():
                return str(c)

        raise FileNotFoundError(
            "llama-cli not found. Install llama.cpp and add to PATH, "
            "or pass --llama-cli /path/to/llama-cli"
        )

    def _build_args(self, prompt_path: str) -> list:
        """Build the llama-cli command line arguments."""
        args = [
            self.llama_cli_path,
            "-m", self.model_path,
            "-f", prompt_path,
            "--n-predict", str(self.n_predict),
            "--temp", str(self.temp),
            "--top-p", str(self.top_p),
            "--top-k", str(self.top_k),
            "--repeat-penalty", str(self.repeat_penalty),
            "--ctx-size", str(self.ctx_size),
            "--no-warmup",
            "-no-cnv",
            "--no-display-prompt",
        ]
        if self.ngl > 0:
            args.extend(["-ngl", str(self.ngl)])
        return args

    def _write_prompt(self, prompt: str) -> str:
        """Write prompt to temp file. Returns path. Caller must delete."""
        fd, path = tempfile.mkstemp(suffix=".txt", prefix="yopj_prompt_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(prompt)
        return path

    def generate(self, prompt: str, system_prompt: str = None) -> dict:
        """Generate a response (batch mode — waits for completion).

        Returns dict with ok, text, duration_ms, returncode.
        """
        prompt_path = self._write_prompt(prompt)
        try:
            args = self._build_args(prompt_path)
            t0 = time.time()
            cp = subprocess.run(
                args,
                cwd=os.path.dirname(self.llama_cli_path),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
            duration_ms = int((time.time() - t0) * 1000)
            output = self._clean_output(cp.stdout or "", prompt)
            return {
                "ok": cp.returncode == 0,
                "text": output,
                "duration_ms": duration_ms,
                "returncode": cp.returncode,
            }
        except subprocess.TimeoutExpired as te:
            duration_ms = int((time.time() - t0) * 1000)
            partial = getattr(te, "stdout", None) or ""
            partial = self._clean_output(partial, prompt)
            return {
                "ok": False, "text": partial,
                "error": f"Generation timed out after {self.timeout_seconds}s.",
                "duration_ms": duration_ms, "returncode": -1,
            }
        except FileNotFoundError:
            return {
                "ok": False, "text": "",
                "error": f"llama-cli not found at: {self.llama_cli_path}",
                "duration_ms": 0, "returncode": -1,
            }
        except OSError as e:
            return {
                "ok": False, "text": "",
                "error": f"OS error: {e}",
                "duration_ms": 0, "returncode": -1,
            }
        finally:
            try:
                os.unlink(prompt_path)
            except OSError:
                pass

    def generate_stream(self, prompt: str, callback=None):
        """Generate a response with streaming output.

        Args:
            prompt: Full conversation prompt.
            callback: Optional callable(chunk: str) called for each text chunk.
                     If None, chunks are accumulated silently.

        Returns:
            dict with ok, text (full output), duration_ms, returncode.
        """
        prompt_path = self._write_prompt(prompt)
        proc = None
        try:
            args = self._build_args(prompt_path)
            t0 = time.time()

            proc = subprocess.Popen(
                args,
                cwd=os.path.dirname(self.llama_cli_path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,  # Discard stderr to prevent pipe deadlock
                bufsize=0,  # Unbuffered
            )

            # Read stdout byte-by-byte for real-time streaming
            chunks = []
            deadline = t0 + self.timeout_seconds

            while True:
                if time.time() > deadline:
                    proc.kill()
                    proc.wait()
                    text = self._clean_output(b"".join(chunks).decode("utf-8", errors="replace"), prompt)
                    duration_ms = int((time.time() - t0) * 1000)
                    return {
                        "ok": False, "text": text,
                        "error": f"Generation timed out after {self.timeout_seconds}s.",
                        "duration_ms": duration_ms, "returncode": -1,
                    }

                byte = proc.stdout.read(1)
                if not byte:
                    break  # EOF — process finished

                chunks.append(byte)

                # Decode and send to callback for display
                if callback:
                    try:
                        char = byte.decode("utf-8", errors="replace")
                        callback(char)
                    except Exception:
                        pass

            proc.wait()
            duration_ms = int((time.time() - t0) * 1000)

            raw = b"".join(chunks).decode("utf-8", errors="replace")
            text = self._clean_output(raw, prompt)

            return {
                "ok": proc.returncode == 0,
                "text": text,
                "duration_ms": duration_ms,
                "returncode": proc.returncode,
            }

        except FileNotFoundError:
            return {
                "ok": False, "text": "",
                "error": f"llama-cli not found at: {self.llama_cli_path}",
                "duration_ms": 0, "returncode": -1,
            }
        except OSError as e:
            return {
                "ok": False, "text": "",
                "error": f"OS error: {e}",
                "duration_ms": 0, "returncode": -1,
            }
        finally:
            if proc and proc.poll() is None:
                proc.kill()
                proc.wait()
            try:
                os.unlink(prompt_path)
            except OSError:
                pass

    def _clean_output(self, raw: str, prompt: str) -> str:
        """Strip prompt echo, llama-cli artifacts, and chat template markers."""
        text = raw

        # Strategy 1: Exact prefix match (works when echo is byte-identical)
        if prompt and text.startswith(prompt):
            text = text[len(prompt):]
        else:
            # Strategy 2: Find the last generation prefix marker
            marker = self.generation_prefix
            idx = text.rfind(marker)
            if idx >= 0:
                text = text[idx + len(marker):]
            else:
                # Strategy 3: Bare "assistant\n" fallback
                idx = text.rfind("assistant\n")
                if idx >= 0:
                    text = text[idx + len("assistant\n"):]

        # Strip known artifacts
        for pattern, replacement in _CLEANUP_PATTERNS:
            text = pattern.sub(replacement, text)

        text = text.strip()
        return text
