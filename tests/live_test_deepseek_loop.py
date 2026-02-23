"""Full tool loop test with DeepSeek-Coder-V2-Lite."""

import os, sys, re, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_protocol import ToolRegistry
from core.model_interface import ModelInterface
from ui.cli import _build_prompt
from tools.glob_search import glob_search
from tools.file_read import file_read

MODEL_PATH = r"C:\Users\Operator\Documents\R2_Core\Models\Coders\DeepSeek-Coder-V2-Lite-Instruct-Q5_K_M.gguf"
LLAMA_CLI = r"C:\Users\Operator\Downloads\llama-b6963-bin-win-cuda-12.4-x64\llama-cli.exe"

SYSTEM_PROMPT = """You are Jean-Luc, a local AI coding agent.

You have tools. To call a tool, use EXACTLY this format:
::TOOL tool_name(arguments)::

Available tools:
::TOOL file_read(path, offset=0, limit=0):: — Read file with line numbers
::TOOL glob_search(pattern, path="."):: — Find files by pattern

CRITICAL RULES:
1. Tool calls MUST start with ::TOOL and end with :: — the word TOOL is required.
2. After emitting a tool call, STOP immediately.
3. The runtime executes your tool and injects results as [TOOL_RESULT name]...[/TOOL_RESULT].
4. After receiving a [TOOL_RESULT], continue your response normally.
5. NEVER fabricate tool output.

Be concise."""


def main():
    print("=" * 60)
    print("DeepSeek-Coder-V2-Lite — Full Tool Loop")
    print("=" * 60)

    reg = ToolRegistry()
    reg.register_tool("file_read", file_read, "Read file")
    reg.register_tool("glob_search", glob_search, "Find files")

    model = ModelInterface(
        model_path=MODEL_PATH, llama_cli_path=LLAMA_CLI,
        ctx_size=4096, temp=0.2, n_predict=512, ngl=99, timeout_seconds=120,
    )

    user_msg = "Read yopj.py and tell me the first 3 imports."
    conversation = [{"role": "user", "content": user_msg}]

    print(f"\nUser: {user_msg}\n")

    for round_num in range(5):
        prompt = _build_prompt(conversation, SYSTEM_PROMPT)
        print(f"Round {round_num+1} ({len(prompt)} chars)...", flush=True)

        result = model.generate(prompt)
        if not result["ok"]:
            print(f"ERROR: {result.get('error')}")
            break

        model_text = result["text"]
        calls = reg.parse_tool_calls(model_text)

        if not calls:
            print(f"Response ({result['duration_ms']}ms):")
            print(model_text[:500])
            print(f"\n{'='*60}")
            print(f"RESULT: {'SUCCESS' if len(model_text.strip()) > 10 else 'EMPTY'} in {round_num+1} rounds")
            print(f"{'='*60}")
            return

        # Truncate at last tool call
        last_end = 0
        for m in re.finditer(r'::(TOOL\s+)?\w+\(.*?\)\s*::', model_text, re.DOTALL):
            last_end = m.end()
        if last_end > 0:
            model_text = model_text[:last_end]

        conversation.append({"role": "assistant", "content": model_text})

        for call in calls:
            print(f"  Tool: {call['name']}({call['args_str'][:50]})")
            tr = reg.execute_tool(call["name"], call["args_str"])
            print(f"    -> {'ok' if tr['ok'] else 'error'} ({tr['duration_ms']}ms)")
            conversation.append({"role": "tool_result", "content": reg.format_result(call["name"], tr)})

    print("Hit round limit.")


if __name__ == "__main__":
    main()
