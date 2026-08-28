# OmniRoute Integration

Hermes treats OmniRoute as a local OpenAI-compatible gateway. Hermes still owns
profile selection, skill selection, thinking level, project context, receipts,
and safety boundaries. OmniRoute owns provider fallback and model/backend pools
behind its local endpoint.

## Local Endpoint

```text
Dashboard: http://127.0.0.1:20128
API:       http://127.0.0.1:20128/v1
```

## Hermes Commands

```bash
src/system/omniroute.sh status
src/system/omniroute.sh doctor
src/system/omniroute.sh install
src/system/omniroute.sh start-bg
src/system/omniroute.sh sync
src/system/omniroute.sh select
src/system/omniroute.sh receipt
```

Quick model shortcut:

```bash
src/system/model.sh omni
src/system/model.sh omni-glm
```

## First-Time Flow

1. Install and start OmniRoute:

```bash
src/system/omniroute.sh install
src/system/omniroute.sh start-bg
```

2. Open the dashboard:

```text
http://127.0.0.1:20128
```

3. Add provider connections and create/copy an API key from the dashboard.

4. Put the API key in the private Hermes env file:

```bash
src/system/cloud-model-picker.sh setup
```

Then edit `.env.cloud-models.local`:

```bash
export OMNIROUTE_API_KEY="..."
export OMNIROUTE_BASE_URL="http://127.0.0.1:20128/v1"
```

5. Sync and select:

```bash
src/system/omniroute.sh sync
src/system/omniroute.sh select auto
src/system/omniroute.sh select nvidia/glm-5.2
src/system/hermes-run.sh --dry-run "verify OmniRoute route"
```

`nvidia/glm-5.2` is registered as an explicit OmniRoute model target. Use it
when you want Hermes to route through the local OmniRoute gateway but force the
backend model selection to GLM 5.2 instead of `auto`.

## MCP and A2A

OmniRoute also exposes MCP and A2A surfaces:

```bash
src/system/omniroute.sh mcp
```

API reference alignment:

- Chat completions: `POST /v1/chat/completions`
- Models: `GET /v1/models`
- MCP status/tools/transports: `/api/mcp/status`, `/api/mcp/tools`, `/api/mcp/sse`, `/api/mcp/stream`
- A2A JSON-RPC: `POST /a2a`
- A2A REST inspection: `/api/a2a/status`, `/api/a2a/tasks`
- A2A agent card: `/.well-known/agent.json`

Hermes records these endpoints but does not auto-bind external MCP tools by
default. Keep scopes narrow when creating OmniRoute API keys.

## Boundaries

Hermes uses OmniRoute through the documented local gateway/API-key flow:

- OpenAI-compatible `/v1` endpoint
- local dashboard/API keys
- optional MCP/A2A endpoint metadata

Hermes does not wire browser sessions, ChatGPT/Codex OAuth tunnels, provider UI
scraping, or tokenized compatibility URLs by default. Header auth remains the
preferred mode.
