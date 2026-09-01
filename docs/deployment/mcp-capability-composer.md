# Hermes MCP Capability Composer

## Purpose

Hermes Capability Composer creates focused, profile-scoped **virtual MCP toolkits** from capabilities that already exist in the canonical Hermes MCP provider registry.

It is deliberately **not** a second trust store, provider router, approval engine, credential store, or execution gateway.

The authority chain is:

```text
Scout / discovery sources
        |
        v
canonical MCP provider registry
(lifecycle + profiles + capabilities + effects + provenance)
        |
        v
Hermes Capability Composer
(selection + aliases + deterministic manifest)
        |
        v
backend provisioning plan
(MCP Market first)
        |
        v
profile-scoped composite MCP endpoint
```

The composer can narrow existing authority. It cannot expand it.

## Invariants

1. `config/mcp-provider-registry.json` remains authoritative for provider lifecycle, profiles, capabilities, effects, runtime state, and provenance.
2. `DISCOVERED` and `CANDIDATE` providers cannot be composed.
3. Composition never changes a provider lifecycle state or `runtime_enabled` flag.
4. A selected provider must already advertise the toolkit profile, requested capability, and requested effect.
5. A selected effect must also be explicitly allowed by the toolkit.
6. Aliases are unique within a toolkit.
7. A toolkit is runtime-ready only when the toolkit is enabled **and every selected source is already runtime-ready** (`CANARY` or `ACTIVE` plus `runtime_enabled=true`).
8. Backend rendering contains no provider auth configuration, secret environment names, transport credentials, or secret values.
9. The provider router remains the routing authority. The composer sets `composition_can_route=false`.
10. The composer cannot promote trust. It sets `composition_can_promote=false`.

## Files

- `config/mcp-provider-registry.json` — canonical provider authority.
- `config/mcp-toolkit-registry.json` — declarative composite-toolkit definitions.
- `src/system/mcp-capability-composer.py` — validation, deterministic composition, backend rendering, and CLI.
- `tests/test_mcp_capability_composer.py` — trust/profile/effect/collision/determinism/runtime/backend contract tests.

## Default toolkits

### `hermes_development`

Profile: `coding`

Focused development capabilities from GitHub, Context7, Sentry, Supabase, and Playwright. External writes are permitted only where the selected provider already advertises `external_write`. The toolkit can be requested for runtime use, but it remains `runtime_ready=false` until every selected source is independently active and enabled.

### `hermes_production_readonly`

Profile: `research`

Read-only production-observation composition. `allowed_effects` is exactly `read`, and the toolkit is disabled by default.

### `hermes_security_lab`

Profile: `security_research`

Combines approved security-research capabilities. It allows only `read` and `authorized_security_execution`, and is disabled by default. Candidate providers such as an unpromoted community pentest server are rejected by the composer even if they advertise matching capabilities.

### `hermes_revenue`

Profile: `revenue`

Combines research, browser capture, workflow execution, and publishing capabilities. It is disabled by default; composition does not authorize or activate any external write.

## MCP Market backend

MCP Market Toolkits support selecting tools from multiple connected MCP server sources, assigning unique aliases, and exposing the result through one Toolkit endpoint. The current Hermes backend mirrors those semantics as a **provisioning plan**.

The backend does **not** call an assumed toolkit-creation API. MCP Market documents API tokens for programmatic access, but the public Toolkit creation documentation currently describes the Toolkit UI workflow rather than a public Toolkit CRUD endpoint. Until a documented Toolkit API contract is available and verified, Hermes emits a credential-free plan and requires a documented vendor workflow for provisioning.

This boundary prevents vendor coupling and prevents Hermes from inventing a private API contract.

References:

- https://docs.mcpmarket.com/docs/toolkits/what-are-toolkits
- https://docs.mcpmarket.com/docs/toolkits/creating-a-toolkit
- https://docs.mcpmarket.com/docs/api-tokens/creating-api-tokens

## CLI

Validate all configured toolkits against the canonical provider registry:

```bash
python3 src/system/mcp-capability-composer.py validate
```

Compose one vendor-neutral manifest:

```bash
python3 src/system/mcp-capability-composer.py compose hermes_development
```

Render the configured backend plan:

```bash
python3 src/system/mcp-capability-composer.py render hermes_development
```

Compose all manifests:

```bash
python3 src/system/mcp-capability-composer.py compose-all
```

Each manifest includes a deterministic `sha256:` digest. The digest changes when any governed selection, effect, alias, runtime state, or source provenance included in the manifest changes.

## Adding a capability to a toolkit

1. Verify the provider exists in `config/mcp-provider-registry.json`.
2. Verify its lifecycle state is `TRUSTED`, `INSTALLED_DISABLED`, `CANARY`, or `ACTIVE`.
3. Verify the target profile is already listed by that provider.
4. Select a capability the provider advertises.
5. Select an effect the provider advertises.
6. Ensure the toolkit explicitly allows that effect.
7. Give the selection a unique alias.
8. Run the composer test suite and validation command.

Do **not** add a candidate to a toolkit as a shortcut around promotion review. Promote it through the existing provenance/governance path first.

## Adding another backend

Backend adapters consume the vendor-neutral manifest. They do not receive provider credentials and they do not get authority to promote, activate, approve, or route capabilities.

A new backend must:

- have an explicit schema/version;
- preserve provider provenance;
- preserve aliases and effects;
- contain no raw secrets or credential templates unless a separately reviewed contract explicitly requires them;
- fail closed when its documented contract is unavailable;
- never modify the canonical provider registry as a side effect of rendering.

## Security rationale

The key failure mode in MCP composition is **authority laundering**: a low-trust or disabled provider gets wrapped in a friendly composite endpoint and appears safer or more authorized than its source. Hermes blocks that by carrying source lifecycle/runtime/provenance into every composed tool and deriving readiness from the underlying source state.

A composite endpoint therefore cannot make a candidate trusted, cannot make an installed-disabled provider active, and cannot turn a read-only toolkit into a write-capable one.
