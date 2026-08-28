---
name: defuddle
description: Use the staged Defuddle source for readable web-content extraction planning, CLI usage guidance, and local integration design without silently installing or executing it.
---

# Defuddle

Use this skill when a task needs main-content extraction from web pages, HTML,
or saved pages using the staged Defuddle source at:

`/root/Documents/Codex/2026-05-20/the-uploaded-file-folder-is-not/New Project (1)/Hermes Max/.skill-sources/kepano__defuddle`

## Operating Rules

- Treat Defuddle as a standalone JavaScript library and CLI, not as an already
  installed Hermes runtime tool.
- Prefer read-only analysis, integration design, command drafting, and test
  planning.
- Do not run `npm install`, `npx defuddle`, network fetches, or package-manager
  commands unless the user explicitly asks for execution in the current turn.
- Do not process secrets, browser cookies, session databases, credential files,
  or private app data.
- If the input is a live URL, state whether network access is required before
  fetching it.
- If output will be saved to disk, ask before overwriting an existing file.

## Useful Source Files

- `README.md`: usage, CLI examples, and API examples.
- `package.json`: package scripts and module entry points.
- `src/`: parser implementation.
- `tests/`: examples of expected behavior.

## Output Patterns

- CLI usage plan
- Node integration snippet
- extraction test plan
- readable-content pipeline design
- risk notes for network, cookies, and private pages
