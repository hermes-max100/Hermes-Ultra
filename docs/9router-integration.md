# 9Router Integration

Hermes treats 9Router as a local OpenAI-compatible gateway. Hermes still owns
profile selection, skill selection, thinking level, project context, receipts,
manual/auto selection, and safety boundaries. 9Router owns provider fallback,
RTK/token-saving, quota tracking, format translation, and backend provider pools
behind its local endpoint.

## Why It Fits

9Router exposes an OpenAI-compatible `/v1` API and is designed to sit between
coding tools and multiple upstream providers. Its public README describes the
standard endpoint as `http://localhost:20128/v1`, with provider fallback and
token-saving features for tools such as Codex, Claude Code, Cursor, Cline, and
OpenClaw.

Hermes already speaks OpenAI-compatible providers, so the integration is:

```text
Hermes task/profile/skill router
  -> selected provider: 9router
  -> http://127.0.0.1:20127/v1/chat/completions
  -> 9Router provider pool/fallback/token saver
  -> upstream model
```

Hermes defaults 9Router to port `20127` so it can run beside OmniRoute, which
commonly uses `20128`. Override with `NINEROUTER_PORT` or
`NINEROUTER_BASE_URL` if your local 9Router is on another port.

## Local Endpoint

```text
Dashboard: http://127.0.0.1:20127
API:       http://127.0.0.1:20127/v1
```

## Hermes Commands

```bash
src/system/ninerouter.sh status
src/system/ninerouter.sh doctor
src/system/ninerouter.sh install
src/system/ninerouter.sh start-bg
src/system/ninerouter.sh sync
src/system/ninerouter.sh select auto
src/system/ninerouter.sh select auto/coding
src/system/ninerouter.sh select nvidia/glm-5.2
src/system/ninerouter.sh receipt
```

Quick picker shortcuts:

```bash
src/system/model.sh nine
src/system/model.sh 9router
src/system/model.sh nine-glm
```

## First-Time Flow

1. Install and start 9Router:

```bash
src/system/ninerouter.sh install
src/system/ninerouter.sh start-bg
```

2. Open the dashboard:

```text
http://127.0.0.1:20127
```

3. Add provider connections in 9Router and create/copy a local API key if your
9Router instance requires one.

4. Put the key in the private Hermes env file:

```bash
src/system/cloud-model-picker.sh setup
```

Then edit `.env.cloud-models.local`:

```bash
export NINEROUTER_API_KEY="local-9router-placeholder"
export NINEROUTER_BASE_URL="http://127.0.0.1:20127/v1"
```

Use a real 9Router key if the dashboard provides one. Use a local placeholder
only if your local 9Router accepts `/v1` calls without authentication.

5. Select and verify:

```bash
src/system/ninerouter.sh select auto/coding
src/system/hermes-run.sh --dry-run "verify 9Router route"
src/system/hermes-run.sh "send this prompt through 9Router"
```

## Boundaries

9Router is an execution gateway, not the top-level Hermes brain. Keep the
responsibilities split:

- Hermes chooses task profile, dynamic skills, manual/auto provider selection,
  receipts, and safety boundaries.
- 9Router handles lower-level provider fallback, token compression, quota
  tracking, and upstream translation.
- Daily refresh validates both the Hermes side and the gateway availability.

