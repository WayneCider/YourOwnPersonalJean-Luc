# YOPJ — Your Own Personal Jean-Luc — Blueprint

**What:** A local AI coding agent with experiential learning, anti-confabulation, and ethical guardrails.
**Who builds it:** R2 (architect + reviewer) via the self-improvement pipeline. DevMarvin scaffolds specs. 32B generates code.
**Where:** `C:\DevMarvin\yopj\`

---

## Architecture

```
yopj/
├── core/
│   ├── tool_protocol.py      # Tool calling: parse, execute, return results
│   ├── context_manager.py    # Track conversation + loaded files
│   ├── model_interface.py    # llama.cpp integration via subprocess
│   └── permission_system.py  # Allow/deny tool calls
├── tools/
│   ├── file_read.py          # Read files
│   ├── file_write.py         # Write files
│   ├── file_edit.py          # String replacement edits
│   ├── glob_search.py        # Find files by pattern
│   ├── grep_search.py        # Search file contents
│   ├── bash_exec.py          # Run shell commands
│   └── git_tools.py          # Git operations
├── learning/
│   ├── seal_store.py         # SEAL lesson persistence
│   ├── memory.py             # Cross-session memory (MEMORY.md files)
│   └── confab_detector.py    # Anti-confabulation on generated code
├── ui/
│   └── cli.py                # Terminal interface
├── tests/
│   └── test_*.py             # Test suites
├── BLUEPRINT.md              # This file
└── yopj.py                   # Entry point
```

---

## Tool Protocol

The core of YOPJ. The model outputs structured tool calls, the runtime executes them, results go back to the model.

**Format** (reuses R2's proven ::CMD:: pattern):
```
::TOOL tool_name(arg1, arg2, key=value)::
```

**Runtime loop:**
1. Send user prompt to model
2. Model generates response (may include ::TOOL:: calls)
3. Runtime parses ::TOOL:: calls from output
4. Execute each tool, collect results
5. Inject results back to model context
6. Model continues generating (may make more tool calls)
7. When model produces final text with no tool calls, display to user

**Tool result injection format:**
```
[TOOL_RESULT tool_name]
{"ok": true, "data": "..."}
[/TOOL_RESULT]
```

---

## Build Order (Pipeline Tasks)

Each task is one file, under 200 lines, self-contained, concrete.

1. **tool_protocol.py** — Tool registration, call parsing, result formatting, execution with timeout
2. **file_read.py** — Read file contents with line numbers, offset/limit support
3. **file_write.py** — Write content to file, create parent dirs
4. **file_edit.py** — Find-and-replace string editing (like Claude Code's Edit)
5. **glob_search.py** — Find files by glob pattern
6. **grep_search.py** — Search file contents by regex
7. **bash_exec.py** — Execute shell commands with timeout and sandboxing
8. **model_interface.py** — Spawn llama-cli, send prompts, capture output
9. **cli.py** — Terminal conversation loop
10. **yopj.py** — Entry point that wires everything together

Tasks 1-7 have no dependencies on each other. Tasks 8-10 depend on 1.

---

## Pipeline Task Format

Each task dispatched to R2 via:
```
::CMD code_task_autopilot_file("goal", "output_path")::
```

Goals must be concrete with named functions, parameter types, and return types.
No abstract comparisons. No embedded ::CMD:: patterns in text.
