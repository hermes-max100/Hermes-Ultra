# Hermes OBLITERATUS Runner

Hermes can run the local OBLITERATUS clone through:

```bash
src/system/obliteratus-runner.sh <command> [args...]
```

The wrapper uses:

- repo: `OBLITERATUS`
- virtualenv: `OBLITERATUS/.venv`
- CLI: `OBLITERATUS/.venv/bin/obliteratus`
- Hermes skill: `.agents/skills/obliteratus-runner/SKILL.md`

## Safe Commands

```bash
src/system/obliteratus-runner.sh status
src/system/obliteratus-runner.sh doctor
src/system/obliteratus-runner.sh help
src/system/obliteratus-runner.sh models --tier tiny
src/system/obliteratus-runner.sh presets
src/system/obliteratus-runner.sh strategies
src/system/obliteratus-runner.sh gpu-calc --help
src/system/obliteratus-runner.sh test-smoke
```

## Local UI

Start the UI locally:

```bash
src/system/obliteratus-runner.sh ui-start --port 7860
```

Stop it:

```bash
src/system/obliteratus-runner.sh ui-stop
```

The UI is bound to `127.0.0.1` by default and public Gradio share links are
blocked.

## Guarded Commands

The wrapper blocks model-download and model-editing commands unless the operator
explicitly opts in.

Commands that may download model files:

```bash
src/system/obliteratus-runner.sh --allow-download info <model>
```

Commands that edit or generate model artifacts:

```bash
src/system/obliteratus-runner.sh --allow-model-edit run <config.yaml>
src/system/obliteratus-runner.sh --allow-model-edit obliterate <args...>
src/system/obliteratus-runner.sh --allow-model-edit self-improve <args...>
```

Hermes should not infer consent for guarded commands from broad requests. The
user should name the model/config target and the intended action.
