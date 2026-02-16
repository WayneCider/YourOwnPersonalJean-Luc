# YOPJ — Your Own Personal Jean-Luc

A local AI coding agent that runs entirely on your machine. No cloud, no API keys, no telemetry. Just you, a local LLM, and a set of tools.

YOPJ connects to any GGUF model via [llama.cpp](https://github.com/ggerganov/llama.cpp) and gives it tool-calling capabilities: read files, edit code, search projects, run commands, and learn from experience.

## What Makes YOPJ Different

- **Runs locally.** Your code never leaves your machine.
- **Multi-model support.** 9 chat templates with auto-detection. Works with Qwen, Llama 3, Mistral, Gemma, Phi-3, and more.
- **Think-block stripping.** Automatically strips `<think>...</think>` blocks from reasoning models (DeepSeek R1, QwQ) — both in batch and streaming mode.
- **Learns from experience.** SEAL (Self Evolving Adaptive Learning) captures reusable patterns from sessions and loads them into future conversations.
- **Detects confabulation.** Built-in heuristics flag when the model is making things up.
- **Detects degenerate output.** Warns on repetition loops, encoding garbage, and empty responses.
- **Security sandbox.** Command blocklist, path confinement, output limits, and audit logging.
- **Permission system.** Tools are classified as allow/ask/deny. You control what the agent can do.
- **Plugin system.** Drop Python files into a plugins directory to add custom tools.
- **Config files.** Project-level `.yopj.toml` — no more long CLI commands.
- **Multi-line input.** Paste code blocks using `"""` delimiters or `\` line continuation.
- **Direct user commands.** `/read`, `/run`, `/grep` execute without a model round-trip.
- **Auto-compaction.** Context window is automatically compressed when nearly full.

## Quick Start

### Install

```bash
pip install -e .    # from source
yopj --help         # verify installation
```

### Prerequisites

- Python 3.10+ (stdlib only — no external dependencies)
- [llama.cpp](https://github.com/ggerganov/llama.cpp) (`llama-server` and/or `llama-cli`)
- A GGUF model file (e.g., [Qwen2.5-Coder-32B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct-GGUF))

### Server Mode (Recommended)

Server mode keeps the model loaded in GPU memory between turns. ~20x faster than subprocess mode.

```bash
# Terminal 1: Start the model server
llama-server -m path/to/model.gguf --port 8080 --ctx-size 8192 -ngl 99

# Terminal 2: Start YOPJ
yopj --server --port 8080
```

### Subprocess Mode

Spawns a new llama-cli process per turn. Slower (~7-10s per turn) but no persistent server needed.

```bash
yopj --model path/to/model.gguf
```

### With a Config File

```bash
yopj --init-config   # creates .yopj.toml with default settings
# Edit .yopj.toml, then just:
yopj                 # reads settings from .yopj.toml
```

### With Learning Enabled

```bash
yopj --server --port 8080 --lessons-dir ./lessons --memory-dir .
```

YOPJ loads previous SEAL lessons and MEMORY.md into its system prompt, improving over time. Session summaries are auto-saved to MEMORY.md on exit.

## Supported Models

YOPJ auto-detects the chat template from the model filename. You can also set it manually with `--template`.

| Template | Models | Auto-detected from |
|----------|--------|-------------------|
| `chatml` | Qwen, DeepSeek, OpenHermes, Nous, Yi | `qwen`, `deepseek`, `openhermes` |
| `llama3` | Llama 3 / 3.1 / 3.2 / 3.3 | `llama-3`, `llama3` |
| `llama2` | Llama 2, CodeLlama | `llama-2`, `codellama` |
| `mistral` | Mistral, Mixtral | `mistral`, `mixtral` |
| `gemma` | Gemma, Gemma 2, CodeGemma | `gemma`, `codegemma` |
| `phi3` | Phi-3, Phi-3.5 | `phi-3`, `phi3` |
| `command-r` | Command-R, Command-R+ | `command-r` |
| `zephyr` | Zephyr, StableLM-Zephyr | `zephyr`, `stablelm` |
| `alpaca` | Alpaca, Vicuna | `alpaca`, `vicuna` |

List all templates: `yopj --list-templates`

## Tools

YOPJ comes with 12 built-in tools:

| Tool | Description |
|------|-------------|
| `file_read` | Read files with line numbers, offset/limit |
| `file_write` | Write files with automatic backup |
| `file_edit` | Find-and-replace editing with inline diff preview |
| `glob_search` | Find files by glob pattern |
| `grep_search` | Search file contents by regex |
| `bash_exec` | Run shell commands (with security validation) |
| `git_status` | Show working tree status |
| `git_diff` | Show changes |
| `git_log` | Show recent commits |
| `git_add` | Stage files |
| `git_commit` | Create commits |
| `git_branch` | List branches |
| `web_fetch` | Fetch URL content for research (public docs only) |

### Custom Plugins

Add your own tools by dropping Python files into a `plugins/` directory:

```python
# plugins/my_tool.py
def word_count(text):
    """Count words in text."""
    words = text.split()
    return {"ok": True, "count": len(words)}

def register_tools(registry):
    registry.register_tool("word_count", word_count, "Count words in text")
```

Plugins are loaded only when explicitly enabled with `--plugins-dir ./plugins`.

## Commands

Type these during a session:

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/tools` | List registered tools (built-in + plugins) |
| `/tokens` | Show token usage and headroom |
| `/prompt` | Show system prompt info and token budget |
| `/retry` | Retry the last failed generation |
| `/undo` | Revert the last file write or edit |
| `/save [file]` | Save conversation to JSON |
| `/load [file]` | Load a saved conversation |
| `/export [file]` | Export conversation as human-readable markdown |
| `/changes` | Files modified this session |
| `/diff` | Show git diff of working directory |
| `/search keyword` | Search conversation history |
| `/tree [path]` | Show project directory tree |
| `/compact` | Compress conversation to free tokens |
| `/clear` | Clear conversation, keep system prompt |
| `/add path [...]` | Add file(s) to context as reference |
| `/context` | Show context window contents |
| `/read path` | Read a file directly (no model round-trip) |
| `/run command` | Run a shell command directly |
| `/grep pattern [path]` | Search files directly |
| `/stats` | Session statistics (tool calls, error rate) |
| `/patterns` | Detected learning patterns |
| `/learn topic \| insight` | Create a SEAL lesson |
| `/model` | Show model and backend info |
| `/config` | Show active configuration |
| `/resume` | Resume from auto-checkpoint (crash recovery) |
| `/exit` | Quit (Ctrl+C also works) |

### Multi-line Input

Paste code blocks using triple quotes:

```
> """
. def hello():
.     print("world")
. """
```

Or use backslash continuation:

```
> Tell me about \
. this function
```

## Configuration

YOPJ searches for `.yopj.toml` in the current directory, then your home directory. CLI flags override config file values.

```bash
yopj --init-config   # generate a sample .yopj.toml
yopj --no-config     # ignore config files, use only CLI flags
yopj --config path   # use a specific config file
```

Sample `.yopj.toml`:

```toml
server = true
host = "127.0.0.1"
port = 8080
ctx_size = 8192
temp = 0.2
n_predict = 4096
lessons_dir = "./lessons"
memory_dir = "."
# plugins_dir = "./plugins"
```

## CLI Options

```
--model PATH         GGUF model file (required unless --server)
--server             Use llama-server HTTP backend
--host HOST          Server host (default: 127.0.0.1)
--port PORT          Server port (default: 8080)
--llama-cli PATH     Path to llama-cli executable
--template NAME      Chat template (auto-detected if omitted)
--list-templates     Show all available templates and exit
--ctx-size N         Context window size (default: 8192)
--temp FLOAT         Sampling temperature (default: 0.2)
--n-predict N        Max tokens per turn (default: 4096)
--ngl N              GPU layers to offload (default: 99)
--timeout N          Generation timeout in seconds (default: 300)
--lessons-dir PATH   SEAL lesson storage directory (enables learning)
--memory-dir PATH    Directory for MEMORY.md persistent memory
--cwd PATH           Working directory for file operations
--plugins-dir PATH   Plugin directory (default: ./plugins)
--config PATH        Config file path (default: auto-detect .yopj.toml)
--no-config          Ignore config files
--init-config        Generate a sample .yopj.toml and exit
--strict-sandbox     Confine all file operations to --cwd
--dangerously-skip-permissions  Auto-allow all tool calls
```

## Architecture

```
yopj/
├── core/
│   ├── tool_protocol.py      — Tool calling protocol (parse, execute, format)
│   ├── model_interface.py     — llama-cli subprocess backend
│   ├── server_interface.py    — llama-server HTTP backend
│   ├── chat_templates.py      — Multi-model prompt formatting (9 templates)
│   ├── context_manager.py     — Token budget + smart 3-phase compression
│   ├── permission_system.py   — Per-tool access control
│   ├── sandbox.py             — Security sandbox (command blocklist, path confinement)
│   ├── config.py              — .yopj.toml configuration file support
│   ├── plugin_loader.py       — User-extensible plugin system
│   ├── audit_log.py           — Structured JSONL event logging
│   └── project_detect.py      — Auto-detect project type from markers
├── tools/                     — Built-in tool implementations (8 files)
├── learning/
│   ├── seal_store.py          — SEAL lesson persistence + quality gates
│   ├── session_learner.py     — Session pattern detection
│   ├── memory.py              — Cross-session markdown memory
│   └── confab_detector.py     — Confabulation heuristics (H1/H2/H5/H6)
├── ui/
│   └── cli.py                 — Terminal conversation loop with streaming
├── yopj.py                    — Entry point
├── pyproject.toml             — Package configuration (pip install)
├── knowledge/                 — Attack pattern reference library (read-only)
└── tests/
    └── test_tools.py          — Test suite (197 tests)
```

## SEAL Learning

SEAL (Self Evolving Adaptive Learning) captures reusable patterns from coding sessions:

- **Auto-detection:** Identifies tool-failure-then-success sequences, high-round-count questions, and repeated errors.
- **Manual capture:** Use `/learn topic | insight` to save specific knowledge.
- **Self-improvement:** Lessons are loaded into the system prompt at session start, so Jean-Luc gets better over time.
- **Confidence scoring:** Each lesson has a confidence level. Low-confidence lessons are excluded from the prompt.
- **Quality gates:** Lesson validation, confidence decay (unvalidated lessons lose confidence over time), revalidation, and conflict detection.
- **Memory auto-save:** Session summaries are automatically appended to MEMORY.md on exit.

## Context Management

YOPJ automatically manages the context window to prevent overflow:

- **3-phase compression:** (1) compress consumed tool results, (2) truncate middle messages, (3) summarize and drop oldest.
- **Auto-compaction:** When context is nearly full (<200 tokens remaining), automatic compression triggers before generation.
- **Running summary:** Dropped messages are summarized and kept as context.
- **Tool result caps:** Large tool results are truncated at 50K characters.
- **File reference pre-loading:** Use `/add` to load files into context without a model round-trip.
- **Auto-checkpoint:** Every 5 turns, conversation is saved to `.yopj-checkpoint.json` for crash recovery.

## Security

> Jean-Luc is hardened against prompt injection and tool abuse in local single-agent environments.
> Co-residency with other autonomous agents requires boot integrity verification and server trust checks.
> See [SECURITY.md](SECURITY.md) for the full threat model, isolation requirements, and reporting policy.

YOPJ includes an 8-layer security stack independently certified by two AI assessors (9.7/10 and 9.5/10, 260+ adversarial test cases, 0 exploitable breaches):

1. **System prompt rules** — 11 security rules embedded in the cognitive layer
2. **Cognitive anchors** — context injection after file reads reminding the model that content is untrusted
3. **Trigger nullification** — breaks latent trigger associations in file content
4. **Trigger pattern detector** — deterministic regex scan on all file content
5. **Provenance gating** — blocks action tools after file reads within the same turn
6. **Lesson validation** — blocklist rejects tool names, triggers, and policy overrides in `/learn`
7. **Sandbox** — 4-phase command validation, path confinement, argument path checking, extension blocking, env-dump blocklist
8. **Protected paths** — core security files are immutable at runtime

### Boot Integrity (Co-Residency Hardening)

For environments where YOPJ runs alongside other autonomous agents:

```bash
yopj --generate-manifest    # Create HMAC-signed integrity manifest
yopj --verify-only           # Verify boot integrity without starting
yopj --expected-model codestral  # Verify model identity at boot
```

- HMAC-signed manifest with PBKDF2 key derivation (operator passphrase, never stored)
- SHA-256 verification of all trust root files at boot
- Process-level server verification (confirms llama-server identity via PID)
- Absolute path resolution for all subprocess calls (eliminates PATH poisoning)
- Plugin auto-load disabled by default (opt-in with `--plugins-dir`)

## License

Copyright 2026 The YOPJ Project

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.

---

*Named after Jean-Luc Picard — because the best agents act on principle, not just capability.*
