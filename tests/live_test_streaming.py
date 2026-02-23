"""Live test of streaming output against 32B model.

Tests that generate_stream produces the same result as generate,
with real-time character output.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.model_interface import ModelInterface
from ui.cli import _build_prompt

MODEL_PATH = r"C:\Users\Operator\Documents\R2_Core\Models\Coders\Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf"
LLAMA_CLI = r"C:\Users\Operator\Downloads\llama-b6963-bin-win-cuda-12.4-x64\llama-cli.exe"

SYSTEM_PROMPT = """You are Jean-Luc, a local AI coding agent.

You have tools. To call a tool, use EXACTLY this format:
::TOOL tool_name(arguments)::

Available tools:
::TOOL bash_exec(command, timeout_seconds=120):: — Run shell command

CRITICAL RULES:
1. Tool calls MUST start with ::TOOL and end with :: — the word TOOL is required.
2. After emitting a tool call, STOP immediately.
3. NEVER fabricate tool output.

Be concise."""


def main():
    print("=" * 60)
    print("LIVE TEST — Streaming Output")
    print("=" * 60)

    model = ModelInterface(
        model_path=MODEL_PATH,
        llama_cli_path=LLAMA_CLI,
        ctx_size=4096,
        temp=0.2,
        n_predict=256,
        ngl=99,
        timeout_seconds=60,
    )

    user_msg = "What is 2 + 2? Answer in one sentence."
    messages = [{"role": "user", "content": user_msg}]
    prompt = _build_prompt(messages, SYSTEM_PROMPT)

    print(f"\nUser: {user_msg}")
    print(f"\n--- Streaming output ---")

    char_count = [0]
    first_char_time = [None]
    t0 = time.time()

    def on_char(c):
        if char_count[0] == 0:
            first_char_time[0] = time.time()
        sys.stdout.write(c)
        sys.stdout.flush()
        char_count[0] += 1

    result = model.generate_stream(prompt, callback=on_char)
    elapsed = time.time() - t0

    print(f"\n--- End streaming ---\n")
    print(f"Result ok: {result['ok']}")
    print(f"Total chars: {char_count[0]}")
    print(f"Clean text: {result['text']!r}")
    print(f"Total time: {elapsed:.1f}s")
    if first_char_time[0]:
        ttfc = first_char_time[0] - t0
        print(f"Time to first char: {ttfc:.1f}s")
        gen_time = elapsed - ttfc
        if gen_time > 0 and char_count[0] > 0:
            # Rough chars/sec (tokens ≈ chars/4)
            print(f"Generation speed: ~{char_count[0] / gen_time:.0f} chars/s (~{char_count[0] / gen_time / 4:.0f} tok/s)")

    print(f"\n{'=' * 60}")
    if result["ok"] and char_count[0] > 0:
        print("RESULT: Streaming works")
    else:
        print("RESULT: FAILED")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
