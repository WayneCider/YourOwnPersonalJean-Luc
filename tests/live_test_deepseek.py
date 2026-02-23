"""Live test against DeepSeek-Coder-V2-Lite (11.8GB Q5_K_M).

Tests whether a different model family works with the same tool protocol.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_protocol import ToolRegistry
from core.model_interface import ModelInterface
from ui.cli import _build_prompt
from tools.glob_search import glob_search
from tools.file_read import file_read

MODEL_PATH = r"C:\Users\Operator\Documents\R2_Core\Models\Coders\DeepSeek-Coder-V2-Lite-Instruct-Q5_K_M.gguf"
LLAMA_CLI = r"C:\Users\Operator\Downloads\llama-b6963-bin-win-cuda-12.4-x64\llama-cli.exe"

SYSTEM_PROMPT = """You are Jean-Luc, a local AI coding agent. You help users with software engineering tasks.

You have tools. To call a tool, use EXACTLY this format:
::TOOL tool_name(arguments)::

Available tools:
::TOOL file_read(path, offset=0, limit=0):: — Read file with line numbers
::TOOL glob_search(pattern, path="."):: — Find files by pattern
::TOOL bash_exec(command, timeout_seconds=120):: — Run shell command

CRITICAL RULES:
1. Tool calls MUST start with ::TOOL and end with :: — the word TOOL is required.
2. After emitting a tool call, STOP immediately. Do not write anything after the closing ::.
3. The runtime executes your tool and injects results as [TOOL_RESULT name]...[/TOOL_RESULT].
4. After receiving a [TOOL_RESULT], continue your response normally.
5. NEVER fabricate tool output. If you need information, call the tool and wait.

Be concise."""


def main():
    print("=" * 60)
    print("LIVE TEST — DeepSeek-Coder-V2-Lite (Q5_K_M)")
    print("=" * 60)

    if not os.path.exists(MODEL_PATH):
        print(f"Model not found: {MODEL_PATH}")
        return

    reg = ToolRegistry()
    reg.register_tool("file_read", file_read, "Read file")
    reg.register_tool("glob_search", glob_search, "Find files")

    model = ModelInterface(
        model_path=MODEL_PATH,
        llama_cli_path=LLAMA_CLI,
        ctx_size=4096,
        temp=0.2,
        n_predict=512,
        ngl=99,
        timeout_seconds=120,
    )

    user_msg = "List all Python files in the current directory."
    messages = [{"role": "user", "content": user_msg}]
    prompt = _build_prompt(messages, SYSTEM_PROMPT)

    print(f"\nUser: {user_msg}")
    print(f"Prompt length: {len(prompt)} chars")
    print(f"\nGenerating...", flush=True)

    t0 = time.time()
    result = model.generate(prompt)
    elapsed = time.time() - t0

    print(f"Done in {elapsed:.1f}s (ok={result['ok']}, rc={result['returncode']})")

    model_text = result["text"]
    print(f"\n--- OUTPUT ({len(model_text)} chars) ---")
    print(model_text[:1000])
    print("--- END ---")

    calls = reg.parse_tool_calls(model_text)
    print(f"\nTool calls: {len(calls)}")
    for c in calls:
        print(f"  {c['name']}({c['args_str'][:60]})")

    has_echo = "CRITICAL RULES" in model_text
    has_confab = "[TOOL_RESULT" in model_text

    print(f"\nEcho leaked: {has_echo}")
    print(f"Confabulated: {has_confab}")

    print(f"\n{'=' * 60}")
    if calls and not has_echo:
        print("RESULT: DeepSeek-Coder-V2-Lite COMPATIBLE")
    elif has_echo:
        print("RESULT: Echo stripping issue")
    else:
        print(f"RESULT: No tool calls parsed — model may use different format")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
