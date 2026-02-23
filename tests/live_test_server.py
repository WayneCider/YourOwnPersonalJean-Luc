"""Live test: YOPJ tool loop via llama-server HTTP backend.

Requires a running llama-server:
    llama-server -m model.gguf --port 8080 --ctx-size 4096 -ngl 99

Tests:
1. Health check
2. Single-turn generation (no tools)
3. Full tool loop: user asks a question → model calls tool → result injected → final answer
"""

import os, sys, re, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_protocol import ToolRegistry
from core.server_interface import ServerInterface
from ui.cli import _build_prompt
from tools.glob_search import glob_search
from tools.file_read import file_read

HOST = "127.0.0.1"
PORT = 8080

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
    print("YOPJ — llama-server HTTP Backend Live Test")
    print("=" * 60)

    server = ServerInterface(host=HOST, port=PORT, temp=0.2, n_predict=512, timeout_seconds=120)

    # Test 1: Health check
    print("\n[1] Health check...", end=" ", flush=True)
    if not server.health_check():
        print(f"FAILED — no server at http://{HOST}:{PORT}")
        print(f"Start with: llama-server -m model.gguf --port {PORT}")
        sys.exit(1)
    print("OK")

    # Test 2: Simple generation (no tools)
    print("\n[2] Simple generation (no tools)...")
    prompt = _build_prompt([{"role": "user", "content": "What is 2+2? Answer in one word."}], SYSTEM_PROMPT)
    t0 = time.time()
    result = server.generate(prompt)
    elapsed = time.time() - t0
    if not result["ok"]:
        print(f"  FAILED: {result.get('error')}")
        sys.exit(1)
    print(f"  Response ({result['duration_ms']}ms): {result['text'][:100]}")
    print(f"  OK")

    # Test 3: Streaming generation
    print("\n[3] Streaming generation...")
    chunks_received = [0]
    def on_chunk(token):
        chunks_received[0] += 1
        if chunks_received[0] <= 5:
            sys.stdout.write(token)
            sys.stdout.flush()

    prompt = _build_prompt([{"role": "user", "content": "Say hello in exactly 3 words."}], SYSTEM_PROMPT)
    result = server.generate_stream(prompt, callback=on_chunk)
    print()
    if not result["ok"]:
        print(f"  FAILED: {result.get('error')}")
        sys.exit(1)
    print(f"  Chunks: {chunks_received[0]}, Text: {result['text'][:100]}")
    print(f"  OK ({result['duration_ms']}ms)")

    # Test 4: Full tool loop
    print("\n[4] Full tool loop (glob_search)...")
    reg = ToolRegistry()
    reg.register_tool("file_read", file_read, "Read file")
    reg.register_tool("glob_search", glob_search, "Find files")

    user_msg = "List all Python files in the current directory."
    conversation = [{"role": "user", "content": user_msg}]
    print(f"  User: {user_msg}")

    for round_num in range(5):
        prompt = _build_prompt(conversation, SYSTEM_PROMPT)
        result = server.generate(prompt)
        if not result["ok"]:
            print(f"  ERROR: {result.get('error')}")
            break

        model_text = result["text"]
        calls = reg.parse_tool_calls(model_text)

        if not calls:
            print(f"  Final response ({result['duration_ms']}ms):")
            print(f"    {model_text[:300]}")
            print(f"\n  RESULT: SUCCESS in {round_num + 1} rounds")
            break

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
    else:
        print("  Hit round limit.")

    print("\n" + "=" * 60)
    print("All tests complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
