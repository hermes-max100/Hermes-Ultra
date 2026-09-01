# Progressive Capability Runtime and Executable Session Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add compact progressive capability discovery/dispatch and a durable rebuildable executable session environment without changing Hermes governance, Scout, approval, or routing authority.

**Architecture:** Reuse the existing `CapabilityCatalog`, `CapabilityProjector`, `CapabilityExpansionController`, `ActionContext`, `CapabilityResult`, and `EvidenceRecorder`. Add one compact progressive runtime facade plus one file-backed append-only session environment, then integrate session event recording through a thin `SessionAwareCapabilityContextOrchestrator` adapter that leaves the core `CapabilityContextOrchestrator` unchanged.

**Tech Stack:** Python 3.10+, stdlib dataclasses/hashlib/json/pathlib/os, pytest 8+, existing Hermes Ultra contracts/evidence/autonomy modules.

**Spec:** `docs/superpowers/specs/2026-09-01-progressive-capability-session-context-design.md`

## Global Constraints

- Scout remains discovery/proposal-only.
- Governance remains the only authority over trusted, installed, canary, active, and runtime-enabled states.
- Progressive discovery/dispatch cannot promote, install, enable, route, or mutate provider lifecycle state.
- Reversible local and already-authorized reversible remote work remains autonomous.
- Existing consequential approval boundaries remain unchanged.
- Session compute executes only trusted registered host operations; never arbitrary model-supplied source.
- Session state is rebuildable from append-only events plus content-addressed payloads.
- Existing evidence and memory authorities remain authoritative; the session environment is operational context only.
- No production deployment in this change.

---

### Task 1: Compact progressive capability facade

**Files:**
- Create: `tests/test_progressive_capabilities.py`
- Create: `src/hermes_ultra/progressive_capabilities.py`
- Modify: `src/hermes_ultra/__init__.py`

**Interfaces:**
- Consumes: `CapabilityCatalog`, `CapabilityProjector`, `CapabilityProjection`, `CapabilityExpansionController`, `ActionContext`, `CapabilityResult`, `FailureClass`.
- Produces: `CapabilityDiscoveryHit`, `CapabilityDiscoveryResult`, `CapabilityDescription`, `CapabilityDispatchResult`, `ProgressiveCapabilityRuntime`.

- [x] **Step 1: Write failing discovery/description tests** proving discovery is bounded, preserves catalog discoverability metadata, and description exposes full descriptor metadata including runtime availability.
- [x] **Step 2: Run focused tests** through the repository CI gate and confirm RED because the module does not exist.
- [x] **Step 3: Implement discovery and description** by reusing `CapabilityProjector` ranking semantics through a query-enriched task view. Do not add a second provider/routing policy.
- [x] **Step 4: Run focused/full tests** and require GREEN.
- [x] **Step 5: Add dispatch contracts** for unknown capability, unavailable capability, reversible omitted capability auto-expansion, consequential boundary non-execution, and executor failure propagation.
- [x] **Step 6: Verify dispatch behavior through CI.**
- [x] **Step 7: Implement `dispatch`** so runtime availability is checked before executor invocation, omitted reversible capabilities use `CapabilityExpansionController`, authority-required cases return recoverable `AUTHORITY_REQUIRED`, and executor `CapabilityResult` semantics are preserved.
- [x] **Step 8: Run the whole repository test workflow** and require GREEN.

---

### Task 2: Durable append-only session environment

**Files:**
- Create: `tests/test_session_environment.py`
- Create: `src/hermes_ultra/session_environment.py`
- Modify: `src/hermes_ultra/__init__.py`

**Interfaces:**
- Consumes: `redact_secrets`, `EvidenceEnvelope`, `EvidenceRecorder`.
- Produces: `SessionIntegrityError`, `SessionEvent`, `SessionProjection`, `SessionComputeRegistry`, `SessionEnvironment`.

- [x] **Step 1: Write failing persistence tests** proving append creates `events.jsonl`, payloads are content-addressed under `payloads/`, full payload bodies are not copied into events, and secret-like data is redacted before persistence.
- [x] **Step 2: Run focused tests** through the repository CI gate and confirm RED because the module does not exist.
- [x] **Step 3: Implement canonical serialization, fsync persistence, payload hashing, append-only events, and verified payload reads.**
- [x] **Step 4: Run persistence tests** and require GREEN.
- [x] **Step 5: Add rebuild/integrity tests** for workspace rebinding, reopen/rebuild equivalence, payload tamper detection, and event-sequence corruption detection.
- [x] **Step 6: Implement replay and integrity validation** so mutable workspace snapshots are unnecessary.
- [x] **Step 7: Run rebuild/integrity tests** and require GREEN.
- [x] **Step 8: Add compute/projection tests** proving registered trusted operations can compute over verified input refs, derived outputs contain operation/input provenance, projection is bounded, and derived bindings survive reopen.
- [x] **Step 9: Implement `SessionComputeRegistry`, `compute`, `select`, and `project`** without `eval`, shell, or arbitrary model-supplied source.
- [x] **Step 10: Run the whole repository test workflow** and require GREEN.

---

### Task 3: Orchestrator session wiring

**Files:**
- Create: `tests/test_session_orchestrator.py`
- Create: `src/hermes_ultra/session_orchestrator.py`
- Preserve unchanged: `src/hermes_ultra/capability_context.py`

**Interfaces:**
- Consumes: `SessionEnvironment`, the existing `CapabilityContextOrchestrator`, context sources, tool executor, and verifier interfaces.
- Produces: `SessionAwareCapabilityContextOrchestrator` with no changes to the base orchestrator's routing/tool public signatures or authority.

- [x] **Step 1: Add failing integration tests** proving base-orchestrator behavior is unchanged, the session-aware adapter records task/context/tool/outcome events, and task/session mismatch fails before execution.
- [x] **Step 2: Run the integration test in CI** and confirm RED because `hermes_ultra.session_orchestrator` does not exist.
- [x] **Step 3: Implement the isolated session adapter** by wrapping context sources, tool executor, and verifier. Session recording must not choose routes, authorize actions, alter escalation order, or replace the memory writer.
- [x] **Step 4: Run the repository test workflow** and require GREEN.

---

### Task 4: Verification, docs, and publication

**Files:**
- Modify: `src/hermes_ultra/__init__.py`
- Modify: `docs/superpowers/specs/2026-09-01-progressive-capability-session-context-design.md`
- Modify: `docs/superpowers/plans/2026-09-01-progressive-capability-session-context.md`

**Interfaces:**
- Public imports for the new progressive runtime, session environment, and session-aware orchestrator must be available from `hermes_ultra` without renaming existing exports.

- [x] **Step 1: Export the new public APIs** from `hermes_ultra.__init__`.
- [x] **Step 2: Align the design specification** with the isolated session-adapter architecture.
- [x] **Step 3: Eliminate persistent test-state leakage** by using pytest-managed temporary session roots.
- [ ] **Step 4: Require the final GitHub `test` workflow to pass** on the final branch head; this workflow includes source compilation, the full pytest suite, regression suites, and secret scans.
- [ ] **Step 5: Require the final `cloud-foundation-validate` workflow to pass** on the final branch head.
- [ ] **Step 6: Mark PR #37 ready and merge only after all final checks are green.**
- [x] **Step 7: Do not production-deploy from this change.**
