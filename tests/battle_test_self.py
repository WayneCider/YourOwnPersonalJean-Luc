"""Self-referential battle test: YOPJ analyzes and modifies its own codebase.

More realistic than the toy calculator test — validates real-world readiness
by testing against a real Python project (YOPJ itself).

Tasks:
1. Explore the project structure
2. Count total lines of code
3. Find all tool implementations
4. Search for a specific pattern across the codebase
5. Read and understand a specific module
6. Create a new utility file

Uses llama-server HTTP backend.
"""

import os
import sys
import re
import time
import shutil
import tempfile

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

HOST = "127.0.0.1"
PORT = 8080

# Copy YOPJ source to a temp dir so file_write doesn't modify real source
YOPJ_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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


def run_task(server, registry, context, user_msg, max_rounds=8):
    """Run a single user task through the tool loop. Returns result dict."""
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
    print("YOPJ SELF-REFERENTIAL BATTLE TEST")
    print("Testing against YOPJ's own codebase")
    print("=" * 70)

    # Check server
    server = ServerInterface(host=HOST, port=PORT, temp=0.2, n_predict=1024, timeout_seconds=120)
    if not server.health_check():
        print(f"ERROR: No llama-server at http://{HOST}:{PORT}")
        sys.exit(1)
    print(f"Server: OK ({HOST}:{PORT})")

    # Create temp workspace with copy of YOPJ source
    work_dir = tempfile.mkdtemp(prefix="yopj_selftest_")
    for item in ("core", "tools", "learning", "ui", "yopj.py"):
        src = os.path.join(YOPJ_DIR, item)
        dst = os.path.join(work_dir, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    os.chdir(work_dir)
    print(f"Workspace: {work_dir}")

    # Build components
    registry = build_registry()
    context = ContextManager(max_tokens=8192, reserved_tokens=1024)
    context.set_system_prompt(SYSTEM_PROMPT)

    results = []
    total_t0 = time.time()

    # Task 1: Explore the project structure
    print(f"\n{'-' * 70}")
    print("TASK 1: Explore the project structure")
    r = run_task(server, registry, context,
                 "Find all Python files in this project recursively and tell me what this project does.")
    results.append(("explore", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  {'PASS' if r['success'] else 'FAIL'}: {r['response'][:200]}")

    # Task 2: Count lines of code
    print(f"\n{'-' * 70}")
    print("TASK 2: Count total lines of Python code")
    r = run_task(server, registry, context,
                 "Use bash to count total lines of Python code in this project. "
                 "Run: find . -name '*.py' -not -path './__pycache__/*' | xargs wc -l")
    results.append(("count_loc", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  {'PASS' if r['success'] else 'FAIL'}: {r['response'][:200]}")

    # Task 3: Find all tool implementations
    print(f"\n{'-' * 70}")
    print("TASK 3: Search for all def statements in the tools directory")
    r = run_task(server, registry, context,
                 "Search for all function definitions (lines starting with 'def ') in the tools/ directory. "
                 "List each function name and which file it's in.")
    results.append(("find_tools", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  {'PASS' if r['success'] else 'FAIL'}: {r['response'][:300]}")

    # Task 4: Search for a specific pattern
    print(f"\n{'-' * 70}")
    print("TASK 4: Find all uses of 'validate_path' across the codebase")
    r = run_task(server, registry, context,
                 "Search the entire project for all uses of 'validate_path'. "
                 "Tell me which files use it and on which lines.")
    results.append(("search_pattern", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  {'PASS' if r['success'] else 'FAIL'}: {r['response'][:300]}")

    # Task 5: Read and understand a module
    print(f"\n{'-' * 70}")
    print("TASK 5: Read and explain core/sandbox.py")
    r = run_task(server, registry, context,
                 "Read core/sandbox.py and explain what security measures it implements. "
                 "Be specific about the blocked command patterns.")
    results.append(("understand", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  {'PASS' if r['success'] else 'FAIL'}: {r['response'][:300]}")

    # Task 6: Create a new file
    print(f"\n{'-' * 70}")
    print("TASK 6: Create a version info module")
    r = run_task(server, registry, context,
                 "Create a new file core/version.py that contains VERSION = '0.6.0' "
                 "and a function get_version_info() that returns a dict with version, python_version, and platform.")
    results.append(("create_file", r))
    print(f"  Rounds: {r['rounds']}  Tools: {len(r['tool_calls'])}  Time: {r['duration_ms']}ms")
    print(f"  {'PASS' if r['success'] else 'FAIL'}: {r['response'][:200]}")

    # Verify file was created
    version_file = os.path.join(work_dir, "core", "version.py")
    file_created = os.path.exists(version_file)
    if file_created:
        with open(version_file, "r") as f:
            vcode = f.read()
        has_version = "0.6.0" in vcode
        has_function = "def get_version_info" in vcode
        print(f"  File created: YES, has VERSION: {has_version}, has function: {has_function}")
    else:
        has_version = has_function = False
        print(f"  File created: NO")

    # Summary
    total_ms = int((time.time() - total_t0) * 1000)
    total_rounds = sum(r["rounds"] for _, r in results)
    total_tools = sum(len(r["tool_calls"]) for _, r in results)
    tool_errors = sum(1 for _, r in results for tc in r["tool_calls"] if not tc["ok"])
    tasks_passed = sum(1 for _, r in results if r["success"])

    usage = context.get_token_usage()

    print(f"\n{'=' * 70}")
    print("SELF-REFERENTIAL BATTLE TEST RESULTS")
    print(f"{'=' * 70}")
    print(f"  Tasks:          {tasks_passed}/{len(results)} passed")
    print(f"  Total rounds:   {total_rounds}")
    print(f"  Tool calls:     {total_tools} ({tool_errors} errors)")
    print(f"  Total time:     {total_ms}ms ({total_ms/1000:.1f}s)")
    print(f"  Context tokens: {usage['total_tokens']} ({usage['compressed_count']} compressed)")
    print(f"  Context msgs:   {usage['message_count']}")

    print(f"\nPer-task breakdown:")
    for name, r in results:
        status = "PASS" if r["success"] else "FAIL"
        tools = ", ".join(tc["name"] for tc in r["tool_calls"]) if r["tool_calls"] else "none"
        print(f"  {name:15s}  [{status}]  {r['rounds']}r  {r['duration_ms']:>5}ms  tools: {tools}")

    print(f"\n{'=' * 70}")
    grade = "PASS" if tasks_passed >= 5 else "NEEDS WORK" if tasks_passed >= 3 else "FAIL"
    print(f"OVERALL: {grade} ({tasks_passed}/{len(results)} tasks)")
    print(f"{'=' * 70}")

    # Cleanup
    os.chdir(YOPJ_DIR)
    shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
