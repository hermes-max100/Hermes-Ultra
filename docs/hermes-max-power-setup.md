# Hermes Max Power Setup

This is the consolidated strongest local Hermes setup assembled from the local
Hermes Max, Hermes Legal, and SimpleLLMs workspaces.

## What Is Included

- Gateway pack: Oracle, Forge, Atlas, Model Provider, Bridge API.
- Profile councils: legal, trading, security research, direct.
- Dynamic skill engine: registry, TF-IDF retrieval, local listwise reranking,
  dashboard, score snapshots, proposal-based evolution.
- Model control: quick picker, manual picker, live provider `/models` sync,
  receipt output, local Onith 1.0, NVIDIA GLM 5.2, OpenRouter, Gemini,
  Perplexity, Venice, ZenMux, OmniRoute.
- OmniRoute local gateway wrapper: status, install, start, sync, select, MCP/A2A
  endpoint metadata.
- JARVIS Tool Armory wrapper: verified uploaded archive, local config template,
  local HUD at `127.0.0.1:4700`, approval-gated Google/GitHub/browser/MCP tools.
- Promptfoo eval pack: dynamic prompt, model route, skill route, JARVIS approval,
  and mobile app control policy regression tests.
- Legal pack: templates and workflows copied from the Hermes Legal workspace.
- Runtime tools: dispatch, live runner, bridge client, OBLITERATUS local runner.
- Operating controls: cost policy, direct-mode policy, restore installer,
  Termux bootstrap, portable exporter.

## Front Door Commands

```bash
src/system/model.sh
src/system/model.sh onith
src/system/model.sh glm
src/system/model.sh receipt
```

```bash
src/system/hermes-dispatch.sh --profile direct "plan this task"
src/system/hermes-run.sh --dry-run "test the selected model route"
src/system/hermes-run.sh "send this prompt to the selected model"
```

```bash
src/system/omniroute.sh doctor
src/system/omniroute.sh select auto
```

```bash
src/system/jarvis-armory.sh status
src/system/jarvis-armory.sh verify-artifacts
src/system/jarvis-armory.sh install
src/system/jarvis-armory.sh start
src/system/jarvis-armory.sh doctor
```

```bash
src/system/promptfoo-evals.sh check
src/system/promptfoo-evals.sh run
```

## Power-Up Commands

```bash
src/system/hermes-power-up.sh status
src/system/hermes-power-up.sh refresh
src/system/hermes-power-up.sh verify
src/system/hermes-power-up.sh export
src/system/hermes-power-up.sh all
```

`all` runs status, provider-model sync, skill snapshots/dashboard, full tests,
and a portable export.

## Workspace Inventory

```bash
src/system/workspace-inventory.sh
```

The inventory command prints candidate workspaces and key files without reading
or emitting API keys.

## Legal Pack

The Hermes Legal workspace contributed reusable legal templates and SOPs:

```text
packs/legal/templates/
packs/legal/workflows/
```

Use these with the legal profile and dynamic skills:

```bash
src/system/hermes-dispatch.sh --profile legal "review this NDA using the legal pack"
src/system/skill-router.sh bundle amazon-appeal --limit 3 "build evidence matrix"
```

## Model Strategy

Local/private default:

```bash
src/system/model.sh onith
```

High-reasoning cloud default:

```bash
src/system/model.sh glm
```

Provider model discovery:

```bash
src/system/model.sh sync all
src/system/cloud-model-picker.sh list nvidia
src/system/cloud-model-picker.sh select nvidia <model-id>
```

Receipts never print secrets:

```bash
src/system/model.sh receipt
src/system/model.sh keys
```

## Verification

```bash
src/system/hermes-power-up.sh verify
```

The verification suite covers model picking, dispatch, direct policy, dynamic
skills, SkillRouter v3, cost controls, bridge client, JARVIS Tool Armory,
Promptfoo dynamic-prompt evals, OBLITERATUS runner, and restore installer
behavior.

## JARVIS Tool Armory

JARVIS is kept as a separate autonomy/tool layer, not folded into the installer
or model router. Hermes chooses skills and models; JARVIS validates tool calls,
enforces approval for mutating actions, and records its execution ledger.

```bash
src/system/jarvis-armory.sh configure
src/system/jarvis-armory.sh start
curl -s http://127.0.0.1:4700/api/health
```

The generated JARVIS config uses:

```text
9Router:   http://127.0.0.1:20127/v1  kimi/kimi-latest
Coding:    http://127.0.0.1:20127/v1  moonshotai/kimi-k3
OmniRoute: http://127.0.0.1:20128/v1  auto
GLM:       http://127.0.0.1:20128/v1  nvidia/glm-5.2
```

Secrets are read from environment variables only.

## Boundaries

Hermes Max uses official APIs, approved connectors, local runtimes, or manual
handoff. It does not reuse browser sessions, scrape provider UIs, bypass rate
limits, expose secrets, or remove security boundaries from defensive tooling.
