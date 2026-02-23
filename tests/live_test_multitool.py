"""Live integration test — multi-tool loop against real 32B model.

Tests a harder task requiring multiple tool calls:
"Read yopj.py and tell me how many tools are registered."
Expected: model calls file_read, then answers from the content.
"""

import os
import sys
import re
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_protocol import ToolRegistry
from core.model_interface import ModelInterface
from ui.cli import _build_prompt
from tools.glob_search import glob_search
from tools.file_read import file_read
from tools.grep_search import grep_search
from tools.bash_exec import bash_exec

# -- Config --
MODEL_PATH = r"C:\Users\Operator\Documents\R2_Core\Models\Coders\Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf"
LLAMA_CLI = r"C:\Users\Operator\Downloads\llama-b6963-bin-win-cuda-12.4-x64\llama-cli.exe"

SYSTEM_PROMPT = """You are Jean-Luc, a local AI coding agent. You help users with software engineering tasks.

You have tools. To call a tool, use EXACTLY this format:
::TOOL tool_name(arguments)::

Available tools:
::TOOL file_read(path, offset=0, limit=0):: — Read file with line numbers
::TOOL file_write(path, content):: — Write file, backup existing
::TOOL file_edit(path, old_string, new_string, replace_all=False):: — Find-and-replace
::TOOL glob_search(pattern, path="."):: — Find files by pattern
::TOOL grep_search(pattern, path=".", glob_filter=None, max_results=50):: — Search contents
::TOOL bash_exec(command, timeout_seconds=120):: — Run shell command

CRITICAL RULES:
1. Tool calls MUST start with ::TOOL and end with :: — the word TOOL is required.
2. After emitting a tool call, STOP immediately. Do not write anything after the closing ::.
3. The runtime executes your tool and injects results as [TOOL_RESULT name]...[/TOOL_RESULT].
4. After receiving a [TOOL_RESULT], continue your response normally.
5. NEVER fabricate tool output. If you need information, call the tool and wait.

Be concise. Read files before modifying them. Prefer editing over rewriting."""

MAX_ROUNDS = 5


def main():
    print("=" * 60)
    print("LIVE TEST — Multi-Tool Loop (Jean-Luc vs Qwen 32B)")
    print("=" * 60)

    # Real tool implementations
    reg = ToolRegistry()
    reg.register_tool("file_read", file_read, "Read file")
    reg.register_tool("glob_search", glob_search, "Find files")
    reg.register_tool("grep_search", grep_search, "Search contents")
    reg.register_tool("bash_exec", bash_exec, "Run command")

    model = ModelInterface(
        model_path=MODEL_PATH,
        llama_cli_path=LLAMA_CLI,
        ctx_size=8192,
        temp=0.2,
        n_predict=1024,
        ngl=99,
        timeout_seconds=180,
    )

    user_msg = "Read yopj.py and tell me how many tools are registered in the build_registry function."
    conversation = [{"role": "user", "content": user_msg}]

    print(f"\nUser: {user_msg}\n")

    for round_num in range(MAX_ROUNDS):
        prompt = _build_prompt(conversation, SYSTEM_PROMPT)
        print(f"--- ROUND {round_num + 1} (prompt: {len(prompt)} chars) ---")
        print(f"Generating...", flush=True)

        t0 = time.time()
        result = model.generate(prompt)
        elapsed = time.time() - t0

        if not result["ok"]:
            print(f"ERROR: {result.get('error', 'unknown')} ({elapsed:.1f}s)")
            break

        model_text = result["text"]
        calls = reg.parse_tool_calls(model_text)

        if not calls:
            # Final response — no more tool calls
            print(f"Model response ({elapsed:.1f}s, {len(model_text)} chars):")
            print(model_text[:1500])
            conversation.append({"role": "assistant", "content": model_text})

            # Validate
            print(f"\n--- VALIDATION ---")
            has_echo = "CRITICAL RULES" in model_text
            has_confab = "[TOOL_RESULT" in model_text
            mentions_count = any(str(n) in model_text for n in range(8, 15))
            print(f"  Echo leaked: {has_echo}")
            print(f"  Confabulated: {has_confab}")
            print(f"  Mentions a number 8-14: {mentions_count}")
            print(f"  Total rounds: {round_num + 1}")
            print(f"\n{'=' * 60}")
            if not has_echo and not has_confab and mentions_count:
                print("RESULT: SUCCESS — model read file and answered correctly")
            elif not has_echo and not has_confab:
                print("RESULT: PARTIAL — model responded but may not have the right answer")
            else:
                print("RESULT: ISSUES — see validation above")
            print(f"{'=' * 60}")
            return

        # Truncate model text at last tool call boundary
        last_call_end = 0
        for m in re.finditer(r'::(TOOL\s+)?\w+\(.*?\)\s*::', model_text, re.DOTALL):
            last_call_end = m.end()
        if last_call_end > 0:
            model_text = model_text[:last_call_end]

        # Show what model said before tool call
        first_call = re.search(r'::(TOOL\s+)?\w+\(', model_text)
        text_before = model_text[:first_call.start()].strip() if first_call else ""
        if text_before:
            print(f"Model: {text_before}")

        # Execute tool calls
        conversation.append({"role": "assistant", "content": model_text})

        for call in calls:
            print(f"  Tool: {call['name']}({call['args_str'][:60]})")
            tr = reg.execute_tool(call["name"], call["args_str"])
            status = "ok" if tr["ok"] else "error"
            formatted = reg.format_result(call["name"], tr)

            # Truncate large results for display
            data_preview = json.dumps(tr.get("data", tr.get("error", "")))
            if len(data_preview) > 200:
                data_preview = data_preview[:200] + "..."
            print(f"    -> {status} ({tr['duration_ms']}ms): {data_preview}")

            conversation.append({"role": "tool_result", "content": formatted})

        print(f"  ({elapsed:.1f}s)\n")

    else:
        print(f"\nHit round limit ({MAX_ROUNDS}). Loop did not converge.")


if __name__ == "__main__":
    main()
