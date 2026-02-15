# Security Policy

## Threat Model

YOPJ (Jean-Luc) is designed to defend against a single adversary communicating through the conversation interface — a user or file content attempting to manipulate the model into unsafe tool use.

**The model is not trusted. The runtime is trusted. The machine is part of the threat model.**

### What YOPJ Defends Against

- Prompt injection via file content, git output, and tool results
- Tool abuse (arbitrary command execution, file exfiltration, privilege escalation)
- Multi-turn social engineering (boiling frog, trust building, context manipulation)
- Polyglot attacks (code comments embedding instructions)
- Extension bypass (rename-to-executable, copy-to-executable)
- Path traversal (relative paths, symlinks, UNC paths, NTFS alternate data streams)
- Environment enumeration (env dump, PATH disclosure)

### What YOPJ Does NOT Defend Against

- **Malicious Python execution.** If the model writes a `.py` file and the user runs it outside the sandbox, YOPJ cannot protect against that script's behavior.
- **Downstream consumers.** YOPJ protects its own cognitive layer from file content injection, but cannot protect other agents or humans who later read files YOPJ created.
- **Kernel-level attacks.** Process injection, debugger attachment, or hypervisor escapes are outside scope.

## Co-Residency Requirements

If YOPJ runs on the same machine as other autonomous agents (e.g., coding assistants, automation tools):

### Required Before Deployment

1. **Boot integrity verification** — Generate an HMAC-signed manifest (`--generate-manifest`) and verify at every boot. Without this, a co-resident agent can silently modify YOPJ's security files before boot.

2. **Server trust verification** — Use `--expected-model` to verify model identity. YOPJ checks the process behind the server port to confirm it is the expected llama-server binary.

3. **Separate OS user account** — Run YOPJ under a dedicated user account with filesystem ACLs preventing other users from writing to YOPJ's directory. Without this, any process running as the same user can modify YOPJ's files.

4. **Plugin auto-load disabled** — Plugins are disabled by default (since v0.16.0). Only enable with `--plugins-dir` pointing to a verified directory. A co-resident agent dropping a `.py` file in the plugins directory gets arbitrary code execution inside YOPJ's process.

### Do Not

- **Do not run YOPJ alongside untrusted agents under the same OS user account** without boot integrity verification.
- **Do not run untrusted agents with Administrator privileges** on the same machine as YOPJ. Admin bypasses all filesystem ACLs. Use container or VM isolation instead.
- **Do not store the manifest signing passphrase on disk.** The passphrase exists only in the operator's memory. Storing it defeats the purpose.

## Security Architecture (8 Layers)

| Layer | Component | Function |
|-------|-----------|----------|
| 1 | System prompt rules | 11 security rules in the cognitive layer |
| 2 | Cognitive anchors | Context injection after file/git reads: "this content is untrusted" |
| 3 | Trigger nullification | Breaks latent trigger associations in file content |
| 4 | Trigger pattern detector | Deterministic regex scan on all file content before model sees it |
| 5 | Provenance gating | Blocks action tools after file reads within the same turn |
| 6 | Lesson validation | Blocklist rejects tool names, triggers, and policy overrides in /learn |
| 7 | Sandbox | 4-phase command validation, path confinement, argument checking, extension blocking |
| 8 | Protected paths | Core security files immutable at runtime |

### Boot-Layer Hardening (v0.16.0)

| Feature | Protection |
|---------|-----------|
| HMAC-signed manifest | Detects pre-boot tampering of trust root files |
| Server trust verification | Confirms llama-server process identity and model |
| Absolute path resolution | Eliminates PATH poisoning for subprocess calls |
| Plugin auto-load disabled | Prevents arbitrary code execution via dropped plugins |

## Trust Root Files

Modification of these files compromises YOPJ's security guarantees:

| Tier | Files | Impact if Tampered |
|------|-------|-------------------|
| 1 (Critical) | `core/sandbox.py`, `core/tool_protocol.py`, `core/permission_system.py` | Total security compromise |
| 2 (Boot) | `yopj.py`, `core/config.py`, `core/plugin_loader.py`, `core/integrity.py`, `core/path_registry.py`, `core/server_trust.py` | Boot sequence compromise |
| 3 (Runtime) | `core/server_interface.py`, `core/model_interface.py`, `core/context_manager.py`, `core/audit_log.py` | Degraded operation |
| 4 (Tools) | `tools/bash_exec.py`, `tools/file_read.py`, `tools/file_write.py`, `tools/file_edit.py`, `tools/git_tools.py` | Individual tool poisoning |

## Contributing Security Changes

Any modification to Tier 1 or Tier 2 files requires full re-certification of the security stack. This means:

- Running the complete adversarial test suite (260+ test cases)
- Verifying all 8 layers remain functional
- Regenerating the integrity manifest

Do not submit PRs that weaken security enforcement for convenience. Security erosion happens through well-meaning feature additions, not through attacks.

## Reporting Vulnerabilities

If you find a security vulnerability in YOPJ, please report it responsibly:

1. **Do not open a public issue.** Security vulnerabilities should not be disclosed publicly before a fix is available.
2. Open a [private security advisory](https://github.com/WayneCider/YourOwnPersonalJean-Luc/security/advisories/new) on GitHub.
3. Include: description, reproduction steps, affected version, and severity assessment.

We aim to acknowledge reports within 48 hours and provide a fix or mitigation within 7 days.
