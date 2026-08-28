# Bridge API Gateway

## Purpose
The Bridge API Gateway maps Hermes profile and router decisions to the official client-facing Hermes Bridge API surface. It is for native clients, local scripts, dashboards, and controller apps that need Web UI parity without using private browser sessions.

## Source
- `bridge/hermes_bridge_manifest.json`
- Uploaded docs:
  - `/tmp/codex-web-uploads/f-BXyYbL/Hermes Bridge API.mht`
  - `/tmp/codex-web-uploads/f-QNpGrm/All endpoints - Hermes Bridge API.mht`

## Access Policy
- Base URL comes from `HERMES_BRIDGE_BASE_URL`.
- Auth uses the documented `hermes_session` cookie after login.
- Cookie jar path comes from `HERMES_BRIDGE_COOKIE_JAR` or a caller-provided curl option.
- Do not reuse browser cookies, extract session tokens, bypass rate limits, or depend on undocumented internal endpoints.

## Primary Workflows
1. Check auth with `GET /api/auth/status`.
2. Login with `POST /api/auth/login` when needed.
3. Create or select a session through `/api/session/*`.
4. Start work with `POST /api/chat/start`.
5. Stream output through `GET /api/chat/stream`.
6. Handle approvals and clarifications through `/api/approval/*` and `/api/clarify/*`.
7. Use `/api/settings`, `/api/model/set`, `/api/reasoning`, and `/api/profile/switch` to align Hermes with router decisions.

## Router Integration
When `src/system/dynamic-router.sh` selects a profile, model route, thinking level, and cost policy, Bridge clients should translate that metadata into Bridge calls:

- Profile route -> `POST /api/profile/switch`
- Model route -> `POST /api/model/set`
- Reasoning level -> `POST /api/reasoning`
- Background task -> `POST /api/background`
- Cost monitoring -> `GET /api/insights`

## Streaming
SSE endpoints:

- `GET /api/chat/stream`
- `GET /api/approval/stream`
- `GET /api/clarify/stream`

Clients should reconnect carefully, avoid duplicate turns, and check `/api/chat/stream/status` when a connection drops.

## Hermes System Prompt
You are the Hermes Bridge API Gateway. Use the documented HTTP and SSE endpoints to control a Hermes server through approved API calls. Never use private browser sessions, undocumented internals, browser cookies, or token extraction. Prefer dry-run command generation until the user explicitly configures a base URL and cookie jar.
