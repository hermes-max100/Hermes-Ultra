# Hermes Discovery, Plugin Intake, and Stateless MCP Design

**Date:** 2026-08-19
**Base:** `hermes-max-setup`
**Branch:** `ai/hermes-discovery-plugin-mcp-v2`

## Goal
Implement three bounded upgrades without creating a second router, memory authority, approval system, or execution boundary: progressive eligibility-first tool discovery; Agent Plugins 1.0 package intake that never activates code; and MCP 2026-07-28 stateless validation that maps into existing containment.

## Tool discovery
`tool-discovery.py` consumes strict `hermes-tool-registry-v1`. Data-class, mutation, and capability eligibility are evaluated before scoring or schema exposure. Results are deterministic and return only selected schemas/hashes. `hermes-dispatch.sh` records selected tools in existing OTel and Memory/Trajectory metadata. Discovery never authorizes execution.

## Plugin intake
`plugin-intake.py` validates local `plugin.json`, fixed `skills/` discovery, and root `mcp.json`; resolves plugin-relative paths inside the plugin root; fingerprints content; performs bounded static capability scanning; writes create-only reports; and always outputs `DISCOVERED`, `activation_allowed=false`, `next_gate=trust-gate`. Trust Gate and later sandbox/evaluator promotion remain authoritative.

## Stateless MCP gateway
`mcp-stateless-gateway.py` validates protocol `2026-07-28`, self-describing routing headers, JSON-RPC/body consistency and client identity in `_meta`; rejects `Mcp-Session-Id` and retired initialization; normalizes cache hints/list ordering; maps MRTR `input_required` to Hermes approval envelopes; validates issuer identity; and derives containment scope from routing metadata, never tool arguments. Legacy input is denied by default and only labeled for a separate adapter behind an explicit flag.

## Security invariants
- No plugin activation from intake.
- No secret-bearing configured remote MCP headers.
- No plugin-relative path or symlink escape.
- No mutating/capability-gated tool schema exposure without explicit eligibility.
- No MCP session state in stateless mode.
- Tool arguments cannot alter containment principal/tool/resource scope.
- Existing HMAC capability verification, kill switch, canonical data classifications, approvals, Trust Gate and Memory/Trajectory authority remain unchanged.
- GitHub Actions references remain immutable SHAs.

## Acceptance
New tests must demonstrate RED before production modules exist, then pass with implementation. Existing dispatch/OTel, skill router, Trust Gate, Memory/Trajectory, containment, and workflow-supply-chain regressions must remain green. Python compilation and Bash syntax must pass.
