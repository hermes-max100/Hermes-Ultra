# Hermes MCP Capability Substrate

Hermes Ultra now treats MCP servers as governed capability providers rather than exposing every installed tool to every agent.

## Portable Agent Plugins

`AgentPluginLoader` implements the Agent Plugins 1.0.0 fixed package layout:

- `plugin.json`
- `skills/<name>/SKILL.md`
- `mcp.json`

Imports never grant trust or runtime authority. `to_candidate()` always creates a `LifecycleState.CANDIDATE`; promotion remains owned by the existing Hermes lifecycle controller.

Component failures are isolated according to the Agent Plugins failure boundaries. A fatal manifest failure rejects the package, while a bad skill or MCP server entry is skipped without destroying independently valid components.

## MCP 2026-07-28 gateway

`McpGateway` uses stateless MCP `2026-07-28` request metadata and Streamable HTTP routing headers. It supports:

- `server/discover`
- paginated `tools/list`
- `ttlMs` / `cacheScope` caching
- private cache partitioning by authorization context
- progressive tool exposure by active profile and requested capability
- temporary provider overrides for `/mcp call` and `/mcp force` style operator routing
- `x-mcp-header` validation and `Mcp-Param-*` mirroring for Streamable HTTP

A provider override changes profile visibility only. It cannot promote a candidate/untrusted provider to active state and cannot widen delegated identity authority.

## Delegated identity

`DelegatedIdentity` represents owner-to-agent-to-subagent authority without copying raw credentials into model context. Child delegations may narrow capabilities, profiles, providers, credential references, task scope, and expiry; they may not widen any of them.

Credential values remain outside the model boundary. The identity envelope carries only opaque credential references suitable for resolution by a future Hermes credential broker.

## Runtime layering

```text
Owner / Hermes Core
        |
DelegatedIdentity
        |
Current Profile
        |
Progressive Capability Router
        |
McpGateway
        |
ACTIVE MCP Provider
        |
External MCP / API
```

Scout remains discovery/proposal only. The existing Hermes lifecycle remains authoritative for trusted, installed, canary, and active states.
