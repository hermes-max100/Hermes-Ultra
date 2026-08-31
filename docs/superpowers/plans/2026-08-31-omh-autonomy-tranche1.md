# OMH Autonomy Tranche 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add task-scoped capability projection, autonomous reversible capability expansion, action-level consequence classification, and diagnostic/verification hooks without reducing Hermes Ultra authority or replacing OmniRoute.

**Architecture:** Add immutable runtime-capability records beside the existing coarse `Capability` classifier. `CapabilityContextOrchestrator` consumes an optional projector/expander and forwards projection metadata only through `TaskRequirements`, so the existing router remains authoritative. Expansion decisions reuse `ApprovalRegistry` and `EvidenceRecorder`; no second policy engine, router, or durable memory store is introduced.

**Tech Stack:** Python 3.10+, dataclasses/enums/stdlib JSON, pytest 8+, existing Hermes Ultra `CapabilityResult`, `ApprovalRegistry`, `EvidenceRecorder`.

**Spec:** `docs/superpowers/specs/2026-08-31-oh-my-hermes-autonomy-integration-design.md`

## Global Constraints

- Projection narrows context, not authority.
- Omitted capabilities remain discoverable and may be expanded on demand.
- Low-consequence reversible expansion is autonomous and auditable.
- `REVERSIBLE_REMOTE` is autonomous only inside existing authorization scope.
- Action consequence is derived from concrete reversibility/effect, never tool power alone.
- Existing exact-match high-consequence categories remain the approval authority.
- OmniRoute remains the sole production model-routing authority.
- Evidence controls completion claims, not general capability availability.
- No second durable memory authority.
- No wholesale `omh setup` runtime installation.
- OMH provenance is pinned as research/upstream metadata only.

---

### Task 1: Deterministic capability catalog and budgeted projection

**Files:**
- Create: `src/hermes_ultra/capability_projection.py`
- Create: `tests/test_capability_projection.py`
- Modify: `src/hermes_ultra/__init__.py`

**Interfaces:**
- `CapabilityProjector.project(task) -> CapabilityProjection`
- `CapabilityProjection.to_router_metadata() -> dict[str, object]`
- `CapabilityProjection.include_on_demand(...) -> CapabilityProjection`

- [ ] Write tests proving summaries are preferred before discoverability loss, unavailable capabilities remain discoverable with an explicit exclusion reason, and omitted capabilities can be added immutably on demand.
- [ ] Run the tests and confirm RED because `hermes_ultra.capability_projection` is absent.
- [ ] Implement `ConsequenceClass`, `EvidenceState`, `ProjectionExclusionReason`, `RuntimeCapabilityDescriptor`, `ProjectedCapability`, `CapabilityExclusion`, `CapabilityProjection`, `CapabilityCatalog`, `CapabilityProjector`, and `default_runtime_capability_catalog()`.
- [ ] Use a two-pass budget: allocate summaries by relevance first, then upgrade the highest-relevance summaries to details with remaining budget.
- [ ] Run focused tests and commit only after GREEN.

### Task 2: Action-level consequence classification and auditable expansion

**Files:**
- Modify: `src/hermes_ultra/autonomy.py`
- Create: `src/hermes_ultra/capability_expansion.py`
- Create: `tests/test_capability_expansion.py`
- Modify: `tests/test_autonomy.py`
- Modify: `src/hermes_ultra/__init__.py`

**Interfaces:**
- `ActionContext`
- `ActionConsequenceClassifier.classify(action) -> ConsequenceClass`
- `ApprovalRegistry.evaluate_action(action, classifier=None) -> AutonomyDecision`
- `CapabilityExpansionController.request(...) -> CapabilityResult[CapabilityExpansionDecision]`

- [ ] Write tests proving powerful tool labels do not make reversible local work consequential, omitted reversible capabilities expand without approval, and registered consequential actions produce an approval-boundary event.
- [ ] Confirm RED before production edits.
- [ ] Implement consequence classification from explicit reversibility/effect only.
- [ ] Preserve exact-match approval categories and existing authorization scope.
- [ ] Record expansion events through the shared `EvidenceRecorder`, not a second durable ledger.
- [ ] Run focused tests and commit after GREEN.

### Task 3: Wire projection and expansion into the existing capability orchestrator

**Files:**
- Modify: `src/hermes_ultra/capability_context.py`
- Modify: `tests/test_capability_context.py`

**Interfaces:**
- Add `TaskRequirements.advisory_metadata`.
- Add `OrchestrationResult.capability_projection`.
- Add optional `capability_projector` and `capability_expander` constructor dependencies.
- Keep the router call signature unchanged.

- [ ] Write integration tests proving projection is advisory metadata and router selection remains authoritative.
- [ ] Write an integration test proving an escalation capability omitted by the initial projection can be expanded autonomously.
- [ ] Confirm RED before production edits.
- [ ] Map existing escalation steps to stable runtime capability IDs.
- [ ] If a capability is omitted, request expansion before the tool call; if an existing consequential boundary is hit, skip only that step and continue technically independent work.
- [ ] Refresh router advisory metadata after allowed expansion.
- [ ] Run focused regression tests and commit after GREEN.

### Task 4: Diagnostics, verification hooks, and pinned OMH provenance

**Files:**
- Create: `src/hermes_ultra/capability_diagnostics.py`
- Create: `tests/test_capability_diagnostics.py`
- Create: `config/omh-upstream.json`
- Create: `tests/test_omh_upstream.py`
- Modify: `src/hermes_ultra/__init__.py`

**Interfaces:**
- `RuntimeCapabilityObservation`
- `CapabilityDiagnostic`, `CapabilityDiagnosticReport`
- `VerificationHookResult`, `VerificationHookRegistry`
- `CapabilityDoctor.inspect(...)`
- `CapabilityDoctor.repair(...)`

- [ ] Write diagnostics/provenance tests first and confirm RED.
- [ ] Implement immutable diagnostic observations and surface-specific verification hooks.
- [ ] Autonomous repair may run only when the concrete repair action is allowed by the existing authority boundary.
- [ ] Add exact OMH v2.0.0 wheel SHA-256 `302ef2e629d99159a5e059c754a13e93c3435088b518af69a378da902ee45725` and research snapshot `06df4eac8f300d9aa27290661f9edb0fb61e9b9d` as concepts-only provenance.
- [ ] Run focused tests and commit after GREEN.

### Task 5: Full verification and publication

- [ ] Run the complete Python suite with `GIT_TEMPLATE_DIR=/tmp/empty-git-template` and `PYTHONPATH=src`.
- [ ] Run `bash tests/test_secret_scan_production.sh`.
- [ ] Run `git diff --check` and Python compile checks.
- [ ] Explicitly rerun autonomy/projection/expansion/context/diagnostics tests.
- [ ] Open a PR against current `main`, wait for all triggered CI, and do not merge failed CI.
- [ ] Merge with expected-head SHA protection only after clean CI.
