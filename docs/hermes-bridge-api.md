# Hermes Bridge API Integration

The uploaded MHT docs define the client-facing Hermes Bridge API: HTTP endpoints plus SSE streams for feature parity with the Hermes Web UI.

## Local Artifacts

- `bridge/hermes_bridge_manifest.json`: structured endpoint manifest extracted from the uploaded docs.
- `gateways/05_bridge_api_gateway.md`: gateway contract and policy.
- `src/system/bridge-client.sh`: dry-run capable helper for listing, validating, and generating Bridge API calls.
- `tests/test_bridge_client.sh`: manifest and client smoke tests.

## Auth

The docs specify a `hermes_session` cookie after login. Use the documented `/api/auth/login` flow or an approved client login flow. Do not reuse browser cookies, extract session tokens, or depend on undocumented internal endpoints.

Environment variables:

```bash
export HERMES_BRIDGE_BASE_URL="https://hermes.example.com"
export HERMES_BRIDGE_COOKIE_JAR="$HOME/.hermes-bridge-cookies.txt"
```

## Usage

```bash
src/system/bridge-client.sh --summary
src/system/bridge-client.sh --list chat_streaming
src/system/bridge-client.sh --find POST /api/chat/start
src/system/bridge-client.sh --curl POST /api/profile/switch '{"profile":"legal"}'
```

`--request` performs a real `curl` call and requires `HERMES_BRIDGE_BASE_URL`.

## Router Mapping

- Profile route -> `POST /api/profile/switch`
- Model route -> `POST /api/model/set`
- Reasoning level -> `POST /api/reasoning`
- Background task -> `POST /api/background`
- Cost monitoring -> `GET /api/insights`

## SSE Streams

- `GET /api/chat/stream`
- `GET /api/approval/stream`
- `GET /api/clarify/stream`

Clients should check `GET /api/chat/stream/status` after reconnects to avoid duplicate turns.
