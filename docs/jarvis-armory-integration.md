# JARVIS Tool Armory Integration

JARVIS is the approval-gated tool layer for Hermes Max. Hermes keeps model
routing, project context, skill routing, and policy. JARVIS exposes the hands:
Gmail, Calendar, Drive, read-only GitHub, browser harness, and optional MCP
servers.

## Local Contract

```text
Hermes Max
  -> 9Router http://127.0.0.1:20127/v1
  -> OmniRoute http://127.0.0.1:20128/v1
  -> JARVIS Tool Armory http://127.0.0.1:4700
```

Secrets stay in environment variables. Do not put provider API keys, OAuth
client secrets, or service tokens in `config.local.json`.

## Commands

```bash
src/system/jarvis-armory.sh status
src/system/jarvis-armory.sh verify-artifacts
src/system/jarvis-armory.sh unpack
src/system/jarvis-armory.sh configure
src/system/jarvis-armory.sh install
src/system/jarvis-armory.sh start
src/system/jarvis-armory.sh doctor
```

The default archive paths point at the uploaded files for this Codex session.
Override them when running elsewhere:

```bash
export JARVIS_ARMORY_ARCHIVE=/sdcard/Download/JARVIS-OS-v1.2.0-tool-armory.zip
export JARVIS_ARMORY_ARCHIVE_SHA=/sdcard/Download/JARVIS-OS-v1.2.0-tool-armory.zip.sha256
export JARVIS_ARMORY_WHEEL=/sdcard/Download/jarvis_os-1.2.0-py3-none-any.whl
export JARVIS_ARMORY_WHEEL_SHA=/sdcard/Download/jarvis_os-1.2.0-py3-none-any.whl.sha256
```

## Runtime Env

```bash
export JARVIS_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export NINEROUTER_API_KEY="..."
export OMNIROUTE_API_KEY="..."
```

Optional integrations:

```bash
export GOOGLE_OAUTH_CLIENT_ID="..."
export GOOGLE_OAUTH_CLIENT_SECRET="..."
export GITHUB_TOKEN="..."
export TAVILY_API_KEY="..."
export FIRECRAWL_API_KEY="..."
```

## Provider Setup

Hermes writes JARVIS config from:

```text
config/jarvis-armory.config.local.example.json
```

That template sets:

- `default_provider=ninerouter`
- `ninerouter -> kimi/kimi-latest`
- `ninerouter_coding -> moonshotai/kimi-k3`
- `omniroute -> auto`
- `omniroute_glm -> nvidia/glm-5.2`
- browser private-network access disabled by default

## Approval Boundary

JARVIS may execute read-only tools directly after schema validation. Mutating
actions route through its approval ledger. Keep the same Hermes mobile boundary:

- drafts are allowed
- sending/posting/deleting/purchasing/security changes require approval
- credentials and one-time codes are entered by the user

## Verification

```bash
src/system/jarvis-armory.sh doctor
curl -s http://127.0.0.1:4700/api/health
```

Expected health:

```json
{"ok": true, "version": "1.2.0"}
```

If `doctor` reports missing keys, add only the relevant env vars to a private
shell profile or Termux session. Do not store them in shared storage or repo
files.
