---
name: codebase-memory-mcp
description: Use the staged Codebase Memory MCP source for code-intelligence MCP planning, configuration review, and gated local indexing design.
---

# Codebase Memory MCP

Use this skill when a task involves evaluating, configuring, or planning use of
the staged Codebase Memory MCP source at:

`/root/Documents/Codex/2026-05-20/the-uploaded-file-folder-is-not/New Project (1)/Hermes Max/.skill-sources/DeusData__codebase-memory-mcp`

## Operating Rules

- Treat Codebase Memory MCP as a standalone MCP server, not as an already
  installed or trusted Hermes runtime component.
- Do not run its installer, start its daemon, index a repository, modify MCP
  client configs, or write agent settings unless the user explicitly approves
  that action in the current turn.
- Before any runtime activation, produce a short plan covering binary source,
  install location, cache path, resource limits, config changes, rollback, and
  validation.
- Keep indexing read-only unless the user explicitly asks to write ADRs,
  metadata, or configuration.
- Do not index secrets, credential stores, browser profiles, `.env` files, SSH
  directories, or app-private data.
- For large repositories, propose scope limits before indexing.

## Useful Source Files

- `README.md`: install modes, MCP tools, and daemon behavior.
- `LICENSE`: license terms.
- `docs/`: architecture and usage details.
- `scripts/license-gate.sh`: license review helper.
- `go.mod`: native build metadata.

## Output Patterns

- MCP activation plan
- config diff review
- indexing scope plan
- resource and cache policy
- rollback checklist
- security notes for secret exclusion
