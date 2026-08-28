---
name: obliteratus-runner
description: >
  Run the local OBLITERATUS install through Hermes using the controlled
  wrapper. Use for OBLITERATUS status checks, dependency doctor checks,
  model/preset/strategy listings, GPU estimates, smoke tests, and local UI
  start/stop. Model-editing commands require explicit operator opt-in.
argument-hint: "status | doctor | models [--tier tiny] | presets | strategies | gpu-calc ... | ui-start [--port 7860] | ui-stop"
---

# OBLITERATUS Runner

Use this skill when the user asks Hermes to run, inspect, or manage the local
OBLITERATUS clone.

Always call the wrapper:

```bash
src/system/obliteratus-runner.sh <command> [args...]
```

Do not call `OBLITERATUS/.venv/bin/obliteratus` directly from Hermes. The
wrapper centralizes path handling, local-only UI defaults, dependency checks,
and command gating.

## Default Safe Commands

- `status`: print configured paths, package version, and UI PID/log locations.
- `doctor`: import OBLITERATUS dependencies and run `pip check`.
- `help`: show the OBLITERATUS CLI help.
- `models [--tier tiny|small|medium|large|frontier]`: list curated models.
- `presets`: list presets.
- `strategies`: list available strategies.
- `gpu-calc ...`: estimate hardware requirements.
- `test-smoke`: run lightweight config/import tests.
- `ui-command [--port N]`: print the local UI command without starting it.
- `ui-start [--port N]`: start the Gradio UI locally on `127.0.0.1`.
- `ui-stop`: stop the background UI process started by the wrapper.

## Guarded Commands

- `info` requires `--allow-download` because it may fetch HuggingFace model
  metadata or weights.
- `run`, `obliterate`, `abliterate`, `self-improve`, and `tourney` require
  `--allow-model-edit`.

Only use guarded flags when the user explicitly asks for that specific action
and supplies the model/config target. Do not infer consent from a broad phrase
like "run it."

## UI Policy

The wrapper forces safe UI defaults:

- host: `127.0.0.1`
- browser: `--no-browser`
- public share links: disabled

If auth is needed:

```bash
src/system/obliteratus-runner.sh ui-start --port 7860 --auth user:pass
```

## Expected Result Format

Return:

- command run
- whether it succeeded
- key output lines
- local URL for UI starts
- log path for UI starts

Do not claim a model was edited unless the guarded command completed and the
output path is known.
