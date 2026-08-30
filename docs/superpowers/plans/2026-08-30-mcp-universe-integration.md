# MCP Universe Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the requested MCP universe into Hermes Ultra as a provenance-backed provider catalog, profile/capability router, native Hermes runtime renderer, and AWS-deployable configuration without exposing credentials or weakening existing consequential-action boundaries.

**Architecture:** `config/mcp-provider-registry.json` is the canonical catalog. `src/system/mcp-provider-registry.py` validates it, resolves profile/capability/effect candidates, and renders secret-reference-only native Hermes `mcp_servers` entries. The stateless MCP gateway consumes the same registry for progressive provider selection. A sync script applies only Hermes-managed MCP entries while preserving unrelated user-configured servers.

**Tech Stack:** Python 3.12 stdlib, JSON, existing Hermes MCP 2026-07-28 gateway, Hermes Agent 0.20.5 native MCP manager, Bash, GitHub Actions.

**Spec:** User-requested MCP list in `Hidden mcp_connector_setup_guide.md`, cross-checked against current provider documentation on 2026-08-30.

## Global Constraints

- Scout remains discovery/proposal only; it cannot promote lifecycle state.
- Existing lifecycle states remain authoritative: DISCOVERED, CANDIDATE, TRUSTED, INSTALLED_DISABLED, CANARY, ACTIVE.
- Never commit raw API keys, OAuth tokens, wallet credentials, broker secrets, Telegram credentials, or endpoint secrets.
- Quality/reliability first; pin executable third-party packages before automatic activation.
- `mcpc` is integrated as deferred platform tooling, never as a second MCP control plane.
- Kubernetes remains runtime-disabled unless Hermes actually adopts Kubernetes.
- Live trade/payment/spending and irreversible production effects retain their existing authority requirements.
- Security execution remains scoped to the `security_research` profile and authorized targets; threat-intelligence reads are separable from scan/exploit capabilities.
- Profile membership controls visibility, not authority.

---

### Task 1: Canonical provider registry

**Files:**
- Create: `config/mcp-provider-registry.json`
- Create: `tests/test_mcp_provider_registry.py`

**Interfaces:**
- Consumes: existing profile IDs and lifecycle vocabulary.
- Produces: one catalog covering 23 MCP providers plus deferred `mcpc` platform tooling.

- [ ] Write tests requiring exact provider coverage, unique IDs, HTTPS remote endpoints, secret-reference-only auth, provenance, profiles, capabilities, effects, lifecycle state, and Scout discovery-only semantics.
- [ ] Run the test and verify it fails because the registry/loader does not exist.
- [ ] Add the catalog with current verified endpoints/packages where available; uncertain endpoints/packages remain candidate/disabled instead of being invented.
- [ ] Re-run the registry tests.

### Task 2: Registry validator and native Hermes renderer

**Files:**
- Create: `src/system/mcp-provider-registry.py`
- Test: `tests/test_mcp_provider_registry.py`

**Interfaces:**
- Produces: `load_registry`, `validate_registry`, `render_hermes_servers`, `select_candidates`, and CLI `validate|render|status` commands.

- [ ] Add failing tests for Exa/Playwright active rendering; OAuth/header/stdio secret references; missing vendor endpoint handling; Kubernetes/mcpc deferral; and no secret-bearing query URLs.
- [ ] Implement the minimal dependency-free validator/renderer.
- [ ] Re-run tests and refactor only while green.

### Task 3: Progressive gateway selection

**Files:**
- Modify: `src/system/mcp-stateless-gateway.py`
- Test: `tests/test_mcp_provider_registry.py`

**Interfaces:**
- Consumes: canonical registry.
- Produces: `select_registry_providers(profile, capability, effect, registry_path=...)`.

- [ ] Add a failing integration test proving the gateway uses profile/capability/effect selection and does not surface inactive providers by default.
- [ ] Implement the registry bridge without adding session state.
- [ ] Run existing stateless MCP regressions plus new tests.

### Task 4: Native Hermes configuration sync

**Files:**
- Create: `scripts/sync-mcp-provider-registry.sh`
- Create: `tests/test_mcp_provider_sync.sh`

**Interfaces:**
- Consumes: renderer JSON and Hermes Agent native `_get_mcp_servers` / `_replace_mcp_servers` helpers.
- Produces: idempotent merge of managed MCP entries while preserving unrelated user entries.

- [ ] Write a shell test with a fake Hermes helper proving idempotence, preservation of unmanaged servers, disabled unresolved providers, and zero secret material written to config.
- [ ] Implement sync script with dry-run and apply modes.
- [ ] Run shell test and syntax checks.

### Task 5: CI, docs, and release verification

**Files:**
- Create: `.github/workflows/mcp-universe-validate.yml`
- Create: `docs/deployment/mcp-provider-universe.md`
- Modify: `config/tool-registry.json`

- [ ] Add CI for registry/gateway/sync tests, JSON validation, Python compile, shell syntax, and existing discovery/plugin/MCP regressions.
- [ ] Document provider states, credential environment names, OAuth activation commands, and profile mappings.
- [ ] Run cloud-foundation/release/secret-scan gates and `git diff --check`.

### Task 6: Production activation

- [ ] Merge only after CI passes.
- [ ] Build a checksummed release from the full release branch.
- [ ] Deploy through the existing atomic installer with rollback preserved.
- [ ] Apply the MCP registry to Hermes Agent.
- [ ] Test Exa and Playwright live.
- [ ] Report OAuth/credential-required providers as integrated-but-auth-pending rather than pretending they are active.
- [ ] Verify Hermes health, Tailscale Serve, active release provenance, and rollback target.
