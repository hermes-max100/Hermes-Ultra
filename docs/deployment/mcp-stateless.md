# Hermes MCP 2026-07-28 Stateless Compatibility

Hermes exposes MCP 2026-07-28 through `src/system/mcp-stateless-gateway.py`. The adapter is a protocol boundary only: durable Hermes state remains in Memory Fabric, evidence ledgers, approvals, and other governed stores.

## Stateless request requirements

For the 2026-07-28 path, every request must carry:

- `MCP-Protocol-Version: 2026-07-28`
- `Mcp-Method`
- `Mcp-Name`
- JSON-RPC 2.0 body whose method/name agree with those headers
- `params._meta.io.modelcontextprotocol/clientInfo`

`Mcp-Session-Id`, `initialize`, and `notifications/initialized` are rejected in stateless mode.

## Containment

Tool arguments do not define authorization scope. Hermes derives containment scope from the validated client identity and routing metadata:

- principal: `mcp:<client-name>`
- tool: `mcp:<Mcp-Name>`
- resource: `mcp:<Mcp-Method>:<Mcp-Name>`
- destination/data class: supplied by the trusted gateway configuration

`authorize` then passes the provided single-use capability token to the existing `containment-gateway.py` verifier. The existing HMAC secret, TTL policy, replay markers, revocation, and kill switch remain authoritative.

## Authorization issuer

When an OAuth/OIDC authorization flow supplies an issuer, compare it with the configured expected authorization server using `validate_issuer` before token exchange or credential use. Hermes requires HTTPS and an exact canonical issuer match.

## Cache hints

`tools/list`, `prompts/list`, `resources/list`, and `resources/read` results may be normalized with a bounded `ttlMs` and `cacheScope`. Hermes sorts returned list entries deterministically before caching. Configure a local maximum TTL; do not accept an upstream TTL above that policy.

## MRTR / input-required

A `resultType: input_required` response maps to an internal `hermes-mcp-input-required-v1` approval envelope. It does not create protocol session state. The caller must resume the operation with a new self-describing MCP request after the required Hermes approval/input step.

## Legacy migration

Legacy MCP protocol versions are denied by default. `allow_legacy=True` or CLI `--allow-legacy` only returns `migration_action=legacy_adapter_required`; it does not silently treat an older request as stateless.

Canary migration order:

1. Validate current clients can emit 2026-07-28 headers and client metadata.
2. Route a read-only tool corpus through stateless validation.
3. Add containment-token verification for tool calls.
4. Test worker restart/failover between independent requests.
5. Test issuer mismatch, replayed capability, and kill-switch failures.
6. Enable a bounded traffic percentage for stateless routing.
7. Preserve the legacy adapter separately until parity is proven; remove it only through the normal governed release process.

Rollback is routing-only: disable the stateless feature flag and return traffic to the existing legacy adapter. Do not roll back or rewrite Memory Fabric, approval, or evidence state.
