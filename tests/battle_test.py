"""Battle test: YOPJ performs a real multi-step coding task autonomously.

Task: Given a project with a buggy calculator module and failing tests,
YOPJ must:
1. Discover the project structure (glob)
2. Run tests to find failures (bash)
3. Read the failing code (file_read)
4. Fix the bug (file_edit)
5. Run tests again to verify (bash)
6. Add a missing feature (modulo) (file_edit)
7. Final test run (bash)

Uses llama-server HTTP backend for speed.
Measures: correctness, tool usage, round count, total time, context quality.
"""

import os
import sys
import re
import time
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_protocol import ToolRegistry
from core.server_interface import ServerInterface
from core.context_manager import ContextManager
from core.chat_templates import CHATML, build_prompt as template_build_prompt
from tools.file_read import file_read
from tools.file_write import file_write
from tools.file_edit import file_edit
from tools.glob_search import glob_search
from tools.grep_search import grep_search
from tools.bash_exec import bash_exec
from learning.session_learner import SessionLearner

HOST = "127.0.0.1"
PORT = 8080
PROJECT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "battle_project")

SYSTEM_PROMPT = """You are Jean-Luc, a local AI coding agent. You help users with software engineering tasks.

You have tools. To call a tool, use EXACTLY this format:
::TOOL tool_name(arguments)::

Available tools:
::TOOL file_read(path, offset=0, limit=0):: — Read file with line numbers
::TOOL file_write(path, content):: — Write file, backup existing
::TOOL file_edit(path, old_string, new_string, replace_all=False):: — Find-and-replace in file
::TOOL glob_search(pattern, path="."):: — Find files by pattern
::TOOL grep_search(pattern, path=".", glob_filter=None, max_results=50):: — Search file contents
::TOOL bash_exec(command, timeout_seconds=120):: — Run shell command

CRITICAL RULES:
1. Tool calls MUST start with ::TOOL and end with :: — the word TOOL is required.
2. After emitting a tool call, STOP immediately. Do not write anything after the closing ::.
3. The runtime executes your tool and injects results as [TOOL_RESULT name]...[/TOOL_RESULT].
4. After receiving a [TOOL_RESULT], continue your response normally.
5. NEVER fabricate tool output. If you need information, call the tool and wait.

Be concise. Read files before modifying them. Prefer editing over rewriting."""


def build_registry():
    reg = ToolRegistry()
    reg.register_tool("file_read", file_read, "Read file")
    reg.register_tool("file_write", file_write, "Write file")
    reg.register_tool("file_edit", file_edit, "Edit file")
    reg.register_tool("glob_search", glob_search, "Find files")
    reg.register_tool("grep_search", grep_search, "Search contents")
    reg.register_tool("bash_exec", bash_exec, "Run command")
    return reg


def run_task(server, registry, context, learner, user_msg, max_rounds=8):
    """Run a single user task through the full tool loop.

    Returns dict with: response, rounds, tool_calls, duration_ms, success.
    """
    conversation = context.get_messages()
    conversation.append({"role": "user", "content": user_msg})
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
            learner.record_turn_complete(round_num + 1)
            return {
                "response": model_text,
                "rounds": round_num + 1,
                "tool_calls": all_tool_calls,
                "duration_ms": int((time.time() - t0) * 1000),
                "success": True,
            }

        # Truncate at last tool call
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
                "error": tr.get("error", ""),
            })
            learner.record_tool_call(
                call["name"], call["args_str"], tr["ok"],
                error=tr.get("error", ""), round_num=round_num,
            )
            formatted = registry.format_result(call["name"], tr)
            context.add_message("tool_result", formatted)

        # Rebuild for next round
        continue

    learner.record_turn_complete(max_rounds)
    return {
        "response": "Hit round limit",
        "rounds": max_rounds,
        "tool_calls": all_tool_calls,
        "duration_ms": int((time.time() - t0) * 1000),
        "success": False,
    }


def main():
    print("=" * 70)
    print("YOPJ BATTLE TEST — Real Multi-Step Coding Task")
    print("=" * 70)

    # Check server
    server = ServerInterface(host=HOST, port=PORT, temp=0.2, n_predict=1024, timeout_seconds=120)
    if not server.health_check():
        print(f"ERROR: No llama-server at http://{HOST}:{PORT}")
        sys.exit(1)
    print(f"Server: OK ({HOST}:{PORT})")

    # Make a working copy of the project so edits don't affect the original
    work_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "battle_workspace")
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
    shutil.copytree(PROJECT_DIR, work_dir)
    os.chdir(work_dir)
    print(f"Workspace: {work_dir}")

    # Build components
    registry = build_registry()
    context = ContextManager(max_tokens=8192, reserved_tokens=1024)
    context.set_system_prompt(SYSTEM_PROMPT)
    learner = SessionLearner(lessons_dir=os.path.join(work_dir, "lessons"))

    results = []
    total_t0 = time.time()

    # ========================================================
    # Task 1: Discover the project
    # ========================================================
    print(f"\n{'-' * 70}")
    print("TASK 1: Discover the project structure")
    print(f"{'-' * 70}")

    r = run_task(server, registry, context, learner,
                 "List all Python files in the current directory and tell me what this project is.")
    results.append(("discover", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  Response: {r['response'][:200]}")
    print(f"  Result: {'PASS' if r['success'] else 'FAIL'}")

    # ========================================================
    # Task 2: Run tests, find the bug
    # ========================================================
    print(f"\n{'-' * 70}")
    print("TASK 2: Run tests and identify what's failing")
    print(f"{'-' * 70}")

    r = run_task(server, registry, context, learner,
                 "Run the tests with 'python test_calculator.py' and tell me which test fails and why.")
    results.append(("run_tests", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  Response: {r['response'][:300]}")
    print(f"  Result: {'PASS' if r['success'] else 'FAIL'}")

    # ========================================================
    # Task 3: Read the buggy code and fix it
    # ========================================================
    print(f"\n{'-' * 70}")
    print("TASK 3: Read the buggy divide function and fix it")
    print(f"{'-' * 70}")

    r = run_task(server, registry, context, learner,
                 "Read calculator.py, find the bug in the divide function, and fix it. "
                 "The divide function should raise ZeroDivisionError when dividing by zero, not return 0.")
    results.append(("fix_bug", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  Response: {r['response'][:300]}")
    print(f"  Result: {'PASS' if r['success'] else 'FAIL'}")

    # Verify the fix was applied
    try:
        with open(os.path.join(work_dir, "calculator.py"), "r") as f:
            code = f.read()
        bug_fixed = "return 0" not in code or "raise" in code
        print(f"  Bug fixed in file: {'YES' if bug_fixed else 'NO'}")
    except Exception as e:
        bug_fixed = False
        print(f"  Could not verify: {e}")

    # ========================================================
    # Task 4: Run tests again to verify fix
    # ========================================================
    print(f"\n{'-' * 70}")
    print("TASK 4: Run tests again to verify the fix")
    print(f"{'-' * 70}")

    r = run_task(server, registry, context, learner,
                 "Run the tests again with 'python test_calculator.py' to verify the fix worked.")
    results.append(("verify_fix", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  Response: {r['response'][:300]}")
    print(f"  Result: {'PASS' if r['success'] else 'FAIL'}")

    # ========================================================
    # Task 5: Add a missing feature (modulo)
    # ========================================================
    print(f"\n{'-' * 70}")
    print("TASK 5: Add modulo operation to the calculator")
    print(f"{'-' * 70}")

    r = run_task(server, registry, context, learner,
                 "Add a modulo function to calculator.py and wire it into the calculate() function "
                 "with the '%' operator. Then add a test for it in test_calculator.py.")
    results.append(("add_feature", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  Response: {r['response'][:300]}")
    print(f"  Result: {'PASS' if r['success'] else 'FAIL'}")

    # ========================================================
    # Task 6: Final test run
    # ========================================================
    print(f"\n{'-' * 70}")
    print("TASK 6: Final test run — all tests should pass")
    print(f"{'-' * 70}")

    r = run_task(server, registry, context, learner,
                 "Run the tests one final time to confirm everything passes.")
    results.append(("final_tests", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  Response: {r['response'][:300]}")
    print(f"  Result: {'PASS' if r['success'] else 'FAIL'}")

    # ========================================================
    # Summary
    # ========================================================
    total_ms = int((time.time() - total_t0) * 1000)
    total_rounds = sum(r["rounds"] for _, r in results)
    total_tools = sum(len(r["tool_calls"]) for _, r in results)
    tool_errors = sum(1 for _, r in results for tc in r["tool_calls"] if not tc["ok"])
    tasks_passed = sum(1 for _, r in results if r["success"])

    stats = learner.get_session_stats()
    patterns = learner.detect_patterns()
    usage = context.get_token_usage()

    print(f"\n{'=' * 70}")
    print("BATTLE TEST RESULTS")
    print(f"{'=' * 70}")
    print(f"  Tasks:          {tasks_passed}/{len(results)} passed")
    print(f"  Total rounds:   {total_rounds}")
    print(f"  Tool calls:     {total_tools} ({tool_errors} errors)")
    print(f"  Total time:     {total_ms}ms ({total_ms/1000:.1f}s)")
    print(f"  Avg per task:   {total_ms//len(results)}ms")
    print(f"  Bug fixed:      {'YES' if bug_fixed else 'NO'}")
    print(f"  Context tokens: {usage['total_tokens']} ({usage['compressed_count']} compressed)")
    print(f"  Context msgs:   {usage['message_count']}")
    print(f"  Patterns:       {len(patterns)}")

    print(f"\nPer-task breakdown:")
    for name, r in results:
        status = "PASS" if r["success"] else "FAIL"
        tools = ", ".join(tc["name"] for tc in r["tool_calls"]) if r["tool_calls"] else "none"
        print(f"  {name:15s}  [{status}]  {r['rounds']}r  {r['duration_ms']:>5}ms  tools: {tools}")

    if patterns:
        print(f"\nDetected patterns:")
        for p in patterns:
            print(f"  [{p['type']}] {p['detail'][:80]}")

    # Verify final state
    print(f"\nFinal file verification:")
    try:
        with open(os.path.join(work_dir, "calculator.py"), "r") as f:
            calc_code = f.read()
        has_modulo = "def modulo" in calc_code or "def mod(" in calc_code or "%" in calc_code.split("ops")[1] if "ops" in calc_code else False
        has_raise = "raise" in calc_code and "ZeroDivision" in calc_code
        print(f"  divide() raises ZeroDivisionError: {'YES' if has_raise else 'NO'}")
        print(f"  modulo operation added: {'YES' if has_modulo else 'NO'}")
    except Exception as e:
        print(f"  Could not verify: {e}")

    print(f"\n{'=' * 70}")
    grade = "PASS" if tasks_passed >= 4 and bug_fixed else "NEEDS WORK" if tasks_passed >= 2 else "FAIL"
    print(f"OVERALL: {grade} ({tasks_passed}/{len(results)} tasks, bug_fixed={bug_fixed})")
    print(f"{'=' * 70}")

    # Cleanup
    os.chdir(os.path.dirname(work_dir))


if __name__ == "__main__":
    main()
