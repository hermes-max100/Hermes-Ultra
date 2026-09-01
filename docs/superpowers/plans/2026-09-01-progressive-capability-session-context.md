# Progressive Capability Runtime and Executable Session Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add compact progressive capability discovery/dispatch and a durable rebuildable executable session environment without changing Hermes governance, Scout, approval, or routing authority.

**Architecture:** Reuse the existing `CapabilityCatalog`, `CapabilityProjector`, `CapabilityExpansionController`, `ActionContext`, `CapabilityResult`, and `EvidenceRecorder`. Add one compact progressive runtime facade plus one file-backed append-only session environment, then wire session event recording into the existing `CapabilityContextOrchestrator` through an optional dependency.

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

- [ ] **Step 1: Write failing discovery/description tests** proving discovery is bounded, preserves catalog discoverability metadata, and description exposes full descriptor metadata including runtime availability.
- [ ] **Step 2: Run focused tests** with `PYTHONPATH=src pytest tests/test_progressive_capabilities.py -q`; expected RED because the module does not exist.
- [ ] **Step 3: Implement discovery and description** by reusing `CapabilityProjector` ranking semantics through a query-enriched task view. Do not add a second provider/routing policy.
- [ ] **Step 4: Run focused tests** and require GREEN.
- [ ] **Step 5: Add failing dispatch tests** for unknown capability, unavailable capability, reversible omitted capability auto-expansion, consequential boundary non-execution, and executor failure propagation.
- [ ] **Step 6: Run dispatch tests** and confirm RED for missing behavior.
- [ ] **Step 7: Implement `dispatch`** so runtime availability is checked before executor invocation, omitted reversible capabilities use `CapabilityExpansionController`, authority-required cases return recoverable `AUTHORITY_REQUIRED`, and executor `CapabilityResult` semantics are preserved.
- [ ] **Step 8: Run the whole focused file** and require GREEN.

---

### Task 2: Durable append-only session environment

**Files:**
- Create: `tests/test_session_environment.py`
- Create: `src/hermes_ultra/session_environment.py`
- Modify: `src/hermes_ultra/__init__.py`

**Interfaces:**
- Consumes: `redact_secrets`, `EvidenceEnvelope`, `EvidenceRecorder`.
- Produces: `SessionIntegrityError`, `SessionEvent`, `SessionProjection`, `SessionComputeRegistry`, `SessionEnvironment`.

- [ ] **Step 1: Write failing persistence tests** proving append creates `events.jsonl`, payloads are content-addressed under `payloads/`, full payload bodies are not copied into events, and secret-like data is redacted before persistence.
- [ ] **Step 2: Run focused tests** with `PYTHONPATH=src pytest tests/test_session_environment.py -q`; expected RED because the module does not exist.
- [ ] **Step 3: Implement canonical serialization, fsync persistence, payload hashing, append-only events, and verified payload reads.**
- [ ] **Step 4: Run persistence tests** and require GREEN.
- [ ] **Step 5: Add failing rebuild/integrity tests** for workspace rebinding, reopen/rebuild equivalence, payload tamper detection, and event-sequence corruption detection.
- [ ] **Step 6: Implement replay and integrity validation** so mutable workspace snapshots are unnecessary.
- [ ] **Step 7: Run rebuild/integrity tests** and require GREEN.
- [ ] **Step 8: Add failing compute/projection tests** proving registered trusted operations can compute over verified input refs, derived outputs contain operation/input provenance, projection is bounded, and derived bindings survive reopen.
- [ ] **Step 9: Implement `SessionComputeRegistry`, `compute`, `select`, and `project`** without `eval`, shell, or arbitrary model-supplied source.
- [ ] **Step 10: Run the whole focused file** and require GREEN.

---

### Task 3: Orchestrator session wiring

**Files:**
- Modify: `tests/test_capability_context.py`
- Modify: `src/hermes_ultra/capability_context.py`

**Interfaces:**
- Consumes: optional `SessionEnvironment`-compatible object exposing `append(event_type, payload, metadata=None, bind_as=None)`.
- Produces: no router/tool public signature changes; adds optional constructor dependency only.

- [ ] **Step 1: Add failing integration tests** proving no-session behavior is unchanged and a supplied session environment records task, context-source items, successful tool-result items, and accepted final outcome.
- [ ] **Step 2: Run focused orchestrator tests** and confirm RED for the new optional dependency behavior.
- [ ] **Step 3: Implement minimal session recording hooks** at run start, after source retrieval, after successful tool evidence, and on accepted completion. Session recording must not choose routes, authorize actions, alter escalation order, or replace the memory writer.
- [ ] **Step 4: Run focused orchestrator tests** and require GREEN.

---

### Task 4: Verification, docs, and publication

**Files:**
- Modify if needed: `src/hermes_ultra/__init__.py`
- Existing design/plan docs remain canonical.

**Interfaces:**
- Public imports for the new progressive runtime and session environment must be available from `hermes_ultra` without renaming existing exports.

- [ ] **Step 1: Run focused suite**: `PYTHONPATH=src pytest tests/test_progressive_capabilities.py tests/test_session_environment.py tests/test_capability_projection.py tests/test_capability_expansion.py tests/test_capability_context.py tests/test_autonomy.py -q`.
- [ ] **Step 2: Run Python compile checks** over changed modules.
- [ ] **Step 3: Run `git diff --check` equivalent checks** on generated patches and ensure no placeholder/TODO text was introduced.
- [ ] **Step 4: Push branch and open a pull request** against current `main` with a summary of authority invariants and verification evidence.
- [ ] **Step 5: Use GitHub Actions as the full-repository integration gate.** Do not merge if any required workflow/check fails.
- [ ] **Step 6: Do not production-deploy from this change.**
