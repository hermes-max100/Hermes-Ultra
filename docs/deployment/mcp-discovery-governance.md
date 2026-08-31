# MCP Discovery Federation Governance

Hermes Ultra separates **discovery** from **trust, installation, and activation**.
A directory listing can propose a capability; it cannot make that capability
trusted or executable.

## Source authority order

`config/mcp-discovery-sources.json` is the canonical source-policy file.
`src/system/mcp-discovery-governance.py` validates and applies it.

| Priority | Source | Authority | Trust treatment |
| --- | --- | --- | --- |
| 1000 | Official MCP Registry | canonical | `CANONICAL_DISCOVERY` |
| 900 | Vendor repositories/docs | provenance verification | `VERIFICATION_SOURCE` |
| 600 | Docker MCP Catalog | supplemental discovery | `UNTRUSTED_DISCOVERY` |
| 500 | allMCPservers.com | supplemental discovery | `UNTRUSTED_DISCOVERY_ONLY` |
| 300 | GitHub search | long-tail discovery | `UNTRUSTED_DISCOVERY_ONLY` |
| 100 | Curated MCP lists | weak discovery | `UNTRUSTED_DISCOVERY_ONLY` |

The Official MCP Registry is the canonical public discovery source. Vendor
repositories/documentation provide provenance evidence. Supplemental catalogs
and lists are discovery inputs only.

## Hard boundary

Every configured discovery source must have:

```text
can_discover=true
can_promote=false
can_install=false
can_activate=false
```

Only the vendor-provenance class may set `can_verify=true`, and even that means
"can contribute provenance evidence," not "can approve activation."

`allmcpservers` has an additional fail-closed invariant:

```text
trust=UNTRUSTED_DISCOVERY_ONLY
authority=supplemental_discovery
can_verify=false
can_promote=false
can_install=false
can_activate=false
```

Changing any of those control fields makes registry validation fail.

## Candidate normalization

A discovery result is normalized before it can enter the existing Hermes
candidate/trust workflow. The normalized artifact always begins with:

```json
{
  "lifecycle_state": "DISCOVERED",
  "runtime_enabled": false,
  "verification_required": true,
  "can_promote": false,
  "can_install": false,
  "can_activate": false
}
```

Candidate homepage/repository URLs must be credential-free HTTPS URLs without a
fragment. Unknown discovery-source IDs fail closed.

The existing Hermes Trust Gate and MCP provider registry remain authoritative
for promotion and runtime state. This discovery layer does not modify provider
lifecycle state.

## Interface selection

Hermes does not assume that MCP is the best interface. The governed preference
order is:

1. `native`
2. `cli_skill`
3. `official_api`
4. `official_mcp`
5. `verified_community_mcp`
6. `browser_automation`

The first available interface in that ordered set is returned as a **selection
hint**. Profile visibility, effect classification, credentials, authority, and
runtime policy still control whether that interface may actually be used.

Examples:

```bash
python3 src/system/mcp-discovery-governance.py validate
python3 src/system/mcp-discovery-governance.py sources
python3 src/system/mcp-discovery-governance.py choose-interface official_mcp cli_skill
```

The last command returns `cli_skill`, not `official_mcp`.

## Scout / Agent Reach surface

Scout consumes the same policy through Agent Reach:

```bash
src/system/agent-reach.sh mcp-sources
src/system/agent-reach.sh mcp-interface official_mcp cli_skill
```

These commands are local policy reads only. They do not contact, install,
configure, authenticate to, promote, or activate an MCP server.

External discovery itself continues to use Agent Reach's bounded public-search,
public-GitHub, and SSRF-safe read paths. Retrieved material remains untrusted
content and cannot act as instructions.

## Promotion path

```text
Discovery source
    -> normalized DISCOVERED candidate
    -> canonical-registry check
    -> vendor provenance verification
    -> Trust Gate review
    -> CANDIDATE / TRUSTED
    -> INSTALLED_DISABLED
    -> CANARY
    -> ACTIVE
```

No discovery source can skip a state or directly write runtime activation.
Consequential capabilities retain the existing profile/effect/authority gates.

## Verification

The regression suite is `tests/test_mcp_discovery_governance.py`. It asserts:

- Official MCP Registry remains canonical and highest priority.
- Vendor repositories remain provenance-only.
- allMCPservers.com remains `UNTRUSTED_DISCOVERY_ONLY`.
- no discovery source can promote, install, or activate.
- source ordering is deterministic.
- untrusted candidates cannot escalate lifecycle/runtime state.
- non-HTTPS and unknown-source candidate metadata fails closed.
- best-fit interface selection is not MCP-first.
- Agent Reach exposes the governed source list and interface selector without
  provisioning or activation side effects.

`.github/workflows/mcp-universe-validate.yml` executes the regression and static
JSON/Python/shell validation on relevant pull requests.
