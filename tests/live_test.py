"""Live integration test — full tool-calling loop against real 32B model.

Turn 1: User asks question → model emits tool call
Turn 2: Tool result injected → model generates final answer

Not interactive — runs automatically and reports results.
"""

import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_protocol import ToolRegistry
from core.model_interface import ModelInterface
from core.chat_templates import build_prompt as template_build_prompt, CHATML
from tools.glob_search import glob_search
from tools.file_read import file_read
from tools.bash_exec import bash_exec

# -- Config --
MODEL_PATH = r"C:\Users\Operator\Documents\R2_Core\Models\Coders\Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf"
LLAMA_CLI = r"C:\Users\Operator\Downloads\llama-b6963-bin-win-cuda-12.4-x64\llama-cli.exe"

# -- System prompt (matches yopj.py) --
SYSTEM_PROMPT = """You are Jean-Luc, a local AI coding agent. You help users with software engineering tasks.

You have tools. To call a tool, use EXACTLY this format:
::TOOL tool_name(arguments)::

Available tools:
::TOOL file_read(path, offset=0, limit=0):: — Read file with line numbers
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


def main():
    print("=" * 60)
    print("LIVE TEST — Full Tool Loop (Jean-Luc vs Qwen 32B)")
    print("=" * 60)

    # Build registry with REAL tool implementations
    reg = ToolRegistry()
    reg.register_tool("file_read", file_read, "Read file")
    reg.register_tool("glob_search", glob_search, "Find files")
    reg.register_tool("bash_exec", bash_exec, "Run command")

    # Build model
    model = ModelInterface(
        model_path=MODEL_PATH,
        llama_cli_path=LLAMA_CLI,
        ctx_size=4096,
        temp=0.2,
        n_predict=512,
        ngl=99,
        timeout_seconds=120,
    )

    # ============================================================
    # TURN 1: User prompt → model should emit a tool call
    # ============================================================
    user_msg = "List all Python files in the current directory."
    conversation = [{"role": "user", "content": user_msg}]
    prompt = template_build_prompt(conversation, CHATML, SYSTEM_PROMPT)

    print(f"\n--- TURN 1 ---")
    print(f"User: {user_msg}")
    print(f"Generating...", flush=True)

    t0 = time.time()
    result = model.generate(prompt)
    elapsed = time.time() - t0

    print(f"Done in {elapsed:.1f}s (ok={result['ok']})")

    model_text = result["text"]
    print(f"Model: {model_text[:500]}")

    # Parse tool calls
    calls = reg.parse_tool_calls(model_text)
    print(f"Tool calls: {len(calls)}")

    if not calls:
        print("\nFAIL: No tool calls parsed from model output.")
        print(f"Raw output: {model_text!r}")
        return

    call = calls[0]
    print(f"  -> {call['name']}({call['args_str']})")

    # ============================================================
    # EXECUTE TOOL
    # ============================================================
    print(f"\n--- TOOL EXECUTION ---")
    tr = reg.execute_tool(call["name"], call["args_str"])
    status = "ok" if tr["ok"] else "error"
    print(f"  {call['name']}: {status} ({tr['duration_ms']}ms)")

    formatted = reg.format_result(call["name"], tr)
    print(f"  Result preview: {formatted[:200]}...")

    # ============================================================
    # TURN 2: Inject result → model should generate final answer
    # ============================================================
    # Truncate model text to tool call boundary
    import re
    last_call_end = 0
    for m in re.finditer(r'::(TOOL\s+)?\w+\(.*?\)\s*::', model_text, re.DOTALL):
        last_call_end = m.end()
    if last_call_end > 0:
        model_text = model_text[:last_call_end]

    conversation.append({"role": "assistant", "content": model_text})
    conversation.append({"role": "tool_result", "content": formatted})
    prompt2 = template_build_prompt(conversation, CHATML, SYSTEM_PROMPT)

    print(f"\n--- TURN 2 ---")
    print(f"Prompt length: {len(prompt2)} chars")
    print(f"Generating...", flush=True)

    t0 = time.time()
    result2 = model.generate(prompt2)
    elapsed2 = time.time() - t0

    print(f"Done in {elapsed2:.1f}s (ok={result2['ok']})")

    model_text2 = result2["text"]
    print(f"\nModel response:")
    print(model_text2[:1000])

    # Check quality
    calls2 = reg.parse_tool_calls(model_text2)
    has_tool_calls = len(calls2) > 0
    has_content = len(model_text2.strip()) > 0
    has_echo = "CRITICAL RULES" in model_text2
    has_confab = "[TOOL_RESULT" in model_text2

    print(f"\n--- ANALYSIS ---")
    print(f"  Response length: {len(model_text2)} chars")
    print(f"  Contains text: {has_content}")
    print(f"  Additional tool calls: {len(calls2)}")
    print(f"  Prompt echo leaked: {has_echo}")
    print(f"  Confabulated results: {has_confab}")

    # Summary
    print(f"\n{'=' * 60}")
    if has_content and not has_echo and not has_confab:
        print("RESULT: FULL LOOP SUCCESS — tool called, result injected, model responded")
    elif has_echo:
        print("RESULT: PARTIAL — echo stripping failed on turn 2")
    elif has_confab:
        print("RESULT: PARTIAL — model confabulated tool results")
    elif not has_content:
        print("RESULT: FAIL — model produced empty response after tool result")
    else:
        print("RESULT: PARTIAL — see analysis above")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
