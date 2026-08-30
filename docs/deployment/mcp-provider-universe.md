# Hermes MCP Provider Universe

Hermes uses `config/mcp-provider-registry.json` as the canonical provider catalog. The registry describes transport, provenance, profiles, capabilities, effect classes, lifecycle state, and secret references. It does not contain raw credentials.

## Runtime model

```text
Scout discovery/proposal
        ↓
MCP provider registry
        ↓
profile + capability + effect selection
        ↓
Hermes Agent native mcp_servers
        ↓
provider transport
```

Scout can propose candidates but cannot promote them. `DISCOVERED`, `CANDIDATE`, `TRUSTED`, `INSTALLED_DISABLED`, `CANARY`, and `ACTIVE` remain authoritative lifecycle states.

`src/system/mcp-provider-router.py` performs selection only. `scripts/sync-mcp-provider-registry.sh` renders and merges managed entries into Hermes Agent while preserving unrelated user MCP servers.

## Automatic baseline

Only credential-free providers that are pinned or stable enough for unattended use start enabled:

| Provider | State | Profiles | Purpose |
|---|---|---|---|
| Exa | ACTIVE | research, coding, revenue, direct | web/research retrieval |
| Playwright MCP 0.0.79 | ACTIVE | coding, revenue, creator, direct | isolated headless browser automation |

Playwright uses `--headless --isolated`. It does not reuse a persistent browser profile.

## Integrated but activation-pending

| Provider | Default state | Activation prerequisite |
|---|---|---|
| GitHub | INSTALLED_DISABLED | OAuth/PAT through supported Hermes auth path |
| Composio | INSTALLED_DISABLED | `COMPOSIO_API_KEY` |
| Context7 | INSTALLED_DISABLED | OAuth |
| Sentry | INSTALLED_DISABLED | OAuth |
| Supabase | INSTALLED_DISABLED | OAuth; default route is read-only with docs/database/debugging features |
| Bright Data | INSTALLED_DISABLED | `BRIGHTDATA_API_TOKEN` |
| Kubernetes | INSTALLED_DISABLED | Hermes actually adopts Kubernetes + `KUBECONFIG` |
| Malware Patrol | INSTALLED_DISABLED | vendor MCP URL + API credential |
| WhoisXML API | INSTALLED_DISABLED | OAuth |
| Pentest-Tools | INSTALLED_DISABLED | API credential + authorized security execution context |
| Coinrule | INSTALLED_DISABLED | OAuth; begin with read scope |
| Alpaca | INSTALLED_DISABLED | brokerage API credentials; default configured toolsets are account + stock-data |
| MoltPe | INSTALLED_DISABLED | wallet/API credentials + spending authority |
| Upload-Post | INSTALLED_DISABLED | `UPLOAD_POST_API_KEY` |
| SocialBu | INSTALLED_DISABLED | OAuth |

## Candidate providers

The following are represented in the catalog but remain `CANDIDATE` until provenance/package/operational validation is complete:

- darknet-mcp-server
- PentestMCP
- Tasty Agent / Tastytrade
- Bundle.social
- Telegram MCP (`telegram-mcp-ts`)
- DevOps MCP

Candidate status is not a permanent exclusion. It means Scout/provenance work is still required before promotion.

## Platform tooling

`mcpc` is represented under `platform_tools`, not `providers`. It remains runtime-disabled and may later be used for CLI/CI MCP inspection or scripted invocation through the Hermes gateway. It must never become a parallel control plane that bypasses Hermes capability, credential, or evidence boundaries.

## Effect classes

Provider visibility is separate from authority. The registry uses effects including:

- `read`
- `external_write`
- `production_change`
- `delete`
- `authorized_security_execution`
- `live_trade`
- `spend_money`

A provider can be present in a profile while an individual effect remains unavailable to the current task authority.

## Secret handling

Committed configuration contains references only, for example:

```text
${COMPOSIO_API_KEY}
${BRIGHTDATA_API_TOKEN}
${ALPACA_API_KEY}
${ALPACA_SECRET_KEY}
${UPLOAD_POST_API_KEY}
```

Never place a token in a committed remote MCP URL. Dynamic vendor endpoints use environment references such as `MALWARE_PATROL_MCP_URL`.

## Commands

Validate the registry:

```bash
python3 src/system/mcp-provider-registry.py validate
```

Show current automatic readiness:

```bash
python3 src/system/mcp-provider-registry.py status
```

Render native Hermes MCP definitions without applying them:

```bash
bash scripts/sync-mcp-provider-registry.sh dry-run
```

Apply on the Hermes host as the `hermes` service user:

```bash
bash scripts/sync-mcp-provider-registry.sh apply
```

Then inspect native state:

```bash
hermes mcp list
hermes mcp test exa
hermes mcp test playwright
```

OAuth providers are authenticated with the native Hermes MCP OAuth flow after their registry state is promoted for activation. Credentials remain outside the committed release.

## Provenance policy

Official vendor documentation/repositories are preferred. Community providers remain candidates when provenance, package ownership, hosted endpoint, or effect semantics are not yet strong enough for unattended production activation. The provider registry records a provenance URL for every entry and is validated in CI.
