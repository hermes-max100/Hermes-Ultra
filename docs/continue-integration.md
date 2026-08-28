# Continue Integration

Continue is the VS Code front-end for manual Hermes model switching.

Hermes keeps routing authority in:

- `src/system/model.sh`
- `src/system/cloud-model-picker.sh`
- `src/system/hermes-run.sh --auto`

Continue consumes the local OpenAI-compatible gateway endpoints exposed by
9Router, OmniRoute, and Onith.

## Install Extension

Use the VS Code Marketplace extension:

- [Continue - open-source AI code agent](https://marketplace.visualstudio.com/items?itemName=Continue.continue)

If the `code` CLI is available:

```bash
code --install-extension Continue.continue
```

## Generate Hermes Config

```bash
src/system/continue-config.sh generate
src/system/continue-config.sh show
src/system/continue-config.sh doctor
```

The generated file is:

```bash
.hermes/continue/config.yaml
```

It exposes manual Continue model choices for:

- 9Router auto
- 9Router auto/coding
- Kimi Latest via 9Router
- Kimi K2.7 Code via 9Router
- GLM 5.2 via 9Router
- OmniRoute auto
- OmniRoute auto/coding
- GLM 5.2 via OmniRoute
- Onith 1.0 local

## Install Into Continue

```bash
src/system/continue-config.sh install
```

This backs up the existing `~/.continue/config.yaml`, writes the Hermes config,
and keeps file permissions private.

## Important Boundary

The Continue config does not embed real cloud provider keys. It points Continue
at local Hermes gateways with a local placeholder key. Provider keys stay in
`.env.cloud-models.local` or the shell environment, where the Hermes gateway
tools already expect them.

Use:

```bash
src/system/model.sh receipt
src/system/model.sh keys
src/system/ninerouter.sh status
src/system/omniroute.sh status
```

to verify the active route and gateway health.
