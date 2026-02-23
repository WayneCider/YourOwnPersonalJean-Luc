"""Battle test: YOPJ against R2_Core — a real production codebase.

Tests YOPJ's ability to navigate and understand a complex Python project
with plugins, event loops, config files, and domain-specific architecture.

Uses llama-server HTTP backend (must be running on port 8080).
"""

import os
import sys
import re
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_protocol import ToolRegistry
from core.server_interface import ServerInterface
from core.context_manager import ContextManager
from core.chat_templates import CHATML, build_prompt as template_build_prompt
from tools.file_read import file_read
from tools.glob_search import glob_search
from tools.grep_search import grep_search
from tools.bash_exec import bash_exec

HOST = "127.0.0.1"
PORT = 8080

R2_CORE = r"C:\Users\Operator\Documents\R2_Core"

SYSTEM_PROMPT = """You are Jean-Luc, a local AI coding agent. You help users with software engineering tasks.

You have tools. To call a tool, use EXACTLY this format:
::TOOL tool_name(arguments)::

Available tools:
::TOOL file_read(path, offset=0, limit=0):: — Read file with line numbers
::TOOL glob_search(pattern, path="."):: — Find files by pattern
::TOOL grep_search(pattern, path=".", glob_filter=None, max_results=50):: — Search file contents
::TOOL bash_exec(command, timeout_seconds=120):: — Run shell command

CRITICAL RULES:
1. Tool calls MUST start with ::TOOL and end with :: — the word TOOL is required.
2. After emitting a tool call, STOP immediately. Do not write anything after the closing ::.
3. The runtime executes your tool and injects results as [TOOL_RESULT name]...[/TOOL_RESULT].
4. After receiving a [TOOL_RESULT], continue your response normally.
5. NEVER fabricate tool output. If you need information, call the tool and wait.

Be concise. Read files before answering questions about them."""


def build_registry():
    reg = ToolRegistry()
    reg.register_tool("file_read", file_read, "Read file")
    reg.register_tool("glob_search", glob_search, "Find files")
    reg.register_tool("grep_search", grep_search, "Search contents")
    reg.register_tool("bash_exec", bash_exec, "Run command")
    return reg


def run_task(server, registry, context, user_msg, max_rounds=8):
    """Run a single user task through the tool loop."""
    context.add_message("user", user_msg)
    all_tool_calls = []
    t0 = time.time()

    for round_num in range(max_rounds):
        max_chars = (context.max_tokens - context.reserved_tokens) * 4
        prompt = template_build_prompt(context.get_messages(), CHATML, SYSTEM_PROMPT, max_chars=max_chars)

        result = server.generate(prompt)
        if not result["ok"]:
            return {
                "response": f"ERROR: {result.get('error', 'unknown')}",
                "rounds": round_num + 1,
                "tool_calls": all_tool_calls,
                "duration_ms": int((time.time() - t0) * 1000),
                "success": False,
            }

        model_text = result["text"]
        calls = registry.parse_tool_calls(model_text)

        if not calls:
            context.add_message("assistant", model_text)
            return {
                "response": model_text,
                "rounds": round_num + 1,
                "tool_calls": all_tool_calls,
                "duration_ms": int((time.time() - t0) * 1000),
                "success": True,
            }

        last_end = 0
        for m in re.finditer(r'::(TOOL\s+)?\w+\(.*?\)\s*::', model_text, re.DOTALL):
            last_end = m.end()
        if last_end > 0:
            model_text = model_text[:last_end]

        context.add_message("assistant", model_text)

        for call in calls:
            tr = registry.execute_tool(call["name"], call["args_str"])
            all_tool_calls.append({
                "name": call["name"],
                "args": call["args_str"][:100],
                "ok": tr["ok"],
            })
            formatted = registry.format_result(call["name"], tr)
            context.add_message("tool_result", formatted)

    return {
        "response": "Hit round limit",
        "rounds": max_rounds,
        "tool_calls": all_tool_calls,
        "duration_ms": int((time.time() - t0) * 1000),
        "success": False,
    }


def main():
    print("=" * 70)
    print("YOPJ R2_CORE BATTLE TEST")
    print(f"Target: {R2_CORE}")
    print("=" * 70)

    server = ServerInterface(host=HOST, port=PORT, temp=0.2, n_predict=1024, timeout_seconds=120)
    if not server.health_check():
        print(f"ERROR: No llama-server at http://{HOST}:{PORT}")
        sys.exit(1)
    print(f"Server: OK ({HOST}:{PORT})")

    os.chdir(R2_CORE)
    registry = build_registry()

    results = []
    total_t0 = time.time()

    # Each task gets a fresh context to avoid bleed-through
    def fresh_context():
        ctx = ContextManager(max_tokens=8192, reserved_tokens=1024)
        ctx.set_system_prompt(SYSTEM_PROMPT)
        return ctx

    # Task 1: Find the plugin architecture
    print(f"\n{'-' * 70}")
    print("TASK 1: Find the plugin system entry point")
    ctx = fresh_context()
    r = run_task(server, registry, ctx,
                 f"In {R2_CORE}, find the plugin manager. "
                 "What file is it in and how does it load plugins?")
    results.append(("find_plugins", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  {'PASS' if r['success'] else 'FAIL'}: {r['response'][:300]}")

    # Task 2: Count plugins
    print(f"\n{'-' * 70}")
    print("TASK 2: Count all plugin files")
    ctx = fresh_context()
    r = run_task(server, registry, ctx,
                 f"Find all plugin Python files in {R2_CORE}/System/modules/plugins/. "
                 "Count them and list their names.")
    results.append(("count_plugins", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  {'PASS' if r['success'] else 'FAIL'}: {r['response'][:300]}")

    # Task 3: Find the event loop
    print(f"\n{'-' * 70}")
    print("TASK 3: Find and explain the event loop")
    ctx = fresh_context()
    r = run_task(server, registry, ctx,
                 f"Find the main event loop in {R2_CORE}/System/. "
                 "Read it and explain how it processes model output.")
    results.append(("event_loop", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  {'PASS' if r['success'] else 'FAIL'}: {r['response'][:300]}")

    # Task 4: Find SEAL lesson handling
    print(f"\n{'-' * 70}")
    print("TASK 4: Find how SEAL lessons are loaded at boot")
    ctx = fresh_context()
    r = run_task(server, registry, ctx,
                 f"Search for 'seal_boot_loader' or 'load_boot_lessons' in {R2_CORE}/System/. "
                 "Read the file and explain how lessons are filtered.")
    results.append(("seal_loader", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  {'PASS' if r['success'] else 'FAIL'}: {r['response'][:300]}")

    # Task 5: Find the bypass command system
    print(f"\n{'-' * 70}")
    print("TASK 5: Find ::CMD:: pattern handling in event loop")
    ctx = fresh_context()
    r = run_task(server, registry, ctx,
                 f"Search for 'CMD' regex patterns in {R2_CORE}/System/. "
                 "Which file handles bypass commands and what regex does it use?")
    results.append(("cmd_regex", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  {'PASS' if r['success'] else 'FAIL'}: {r['response'][:300]}")

    # Task 6: Read the config and identify model parameters
    print(f"\n{'-' * 70}")
    print("TASK 6: Read R2 config and find model parameters")
    ctx = fresh_context()
    r = run_task(server, registry, ctx,
                 f"Find and read the R2 config file (YAML) in {R2_CORE}/System/. "
                 "What model path is configured and what are the generation parameters?")
    results.append(("config", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  {'PASS' if r['success'] else 'FAIL'}: {r['response'][:300]}")

    # Summary
    total_ms = int((time.time() - total_t0) * 1000)
    total_rounds = sum(r["rounds"] for _, r in results)
    total_tools = sum(len(r["tool_calls"]) for _, r in results)
    tool_errors = sum(1 for _, r in results for tc in r["tool_calls"] if not tc["ok"])
    tasks_passed = sum(1 for _, r in results if r["success"])

    print(f"\n{'=' * 70}")
    print("R2_CORE BATTLE TEST RESULTS")
    print(f"{'=' * 70}")
    print(f"  Tasks:          {tasks_passed}/{len(results)} passed")
    print(f"  Total rounds:   {total_rounds}")
    print(f"  Tool calls:     {total_tools} ({tool_errors} errors)")
    print(f"  Total time:     {total_ms}ms ({total_ms/1000:.1f}s)")

    print(f"\nPer-task breakdown:")
    for name, r in results:
        status = "PASS" if r["success"] else "FAIL"
        tools = ", ".join(tc["name"] for tc in r["tool_calls"]) if r["tool_calls"] else "none"
        print(f"  {name:15s}  [{status}]  {r['rounds']}r  {r['duration_ms']:>5}ms  tools: {tools}")

    print(f"\n{'=' * 70}")
    grade = "PASS" if tasks_passed >= 5 else "NEEDS WORK" if tasks_passed >= 3 else "FAIL"
    print(f"OVERALL: {grade} ({tasks_passed}/{len(results)} tasks)")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
