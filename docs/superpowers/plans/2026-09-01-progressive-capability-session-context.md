# Progressive Capability Runtime and Executable Session Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add compact progressive capability discovery/dispatch, make it the governed MCP-facing capability path, and add a durable rebuildable executable session environment without changing Hermes governance, Scout, approval, or routing authority.

**Architecture:** Reuse the existing `CapabilityCatalog`, `CapabilityProjector`, `CapabilityExpansionController`, `ActionContext`, `CapabilityResult`, `EvidenceRecorder`, and `McpGateway`. Add a generic progressive runtime, an MCP-specific governed facade, a file-backed append-only session environment, and a thin session-aware orchestrator adapter that leaves the core `CapabilityContextOrchestrator` unchanged.

**Spec:** `docs/superpowers/specs/2026-09-01-progressive-capability-session-context-design.md`

## Global Constraints

- Scout remains discovery/proposal-only.
- Governance remains the only authority over trusted, installed, canary, active, and runtime-enabled states.
- Progressive discovery/dispatch cannot promote, install, enable, route, or mutate provider lifecycle state.
- MCP discovery must begin from `McpGateway.visible_tools`, not raw provider catalogs.
- Reversible local and already-authorized reversible remote work remains autonomous.
- Existing consequential, irreversible, spend, destructive, and authorization-scope boundaries remain unchanged.
- Session compute executes only trusted registered host operations; never arbitrary model-supplied source.
- Session state is rebuildable from append-only events plus content-addressed payloads.
- Existing evidence and memory authorities remain authoritative; the session environment is operational context only.
- No production deployment in this change.

---

## Task 1 — Generic progressive capability runtime

**Files:**
- `tests/test_progressive_capabilities.py`
- `src/hermes_ultra/progressive_capabilities.py`

- [x] Write RED contracts for bounded discovery, complete discoverability metadata, description, unavailable/unknown non-execution, reversible expansion, consequential boundaries, and executor failure propagation.
- [x] Prove RED in CI because the new module did not exist.
- [x] Implement `ProgressiveCapabilityRuntime` using the existing projector and expansion controller.
- [x] Preserve routing/execution authority in the injected executor.
- [x] Verify the implementation through the repository test workflow.

---

## Task 2 — Durable executable session environment

**Files:**
- `tests/test_session_environment.py`
- `src/hermes_ultra/session_environment.py`

- [x] Write RED contracts for externalized content-addressed payloads and secret redaction.
- [x] Prove RED in CI because the module did not exist.
- [x] Implement canonical JSON, payload hashing, append-only events, `fsync`, verified reads, replayable bindings, `select`, and `project`.
- [x] Implement `SessionComputeRegistry` and trusted registered compute with operation/input provenance.
- [x] Test tamper detection and event-sequence corruption.
- [x] Add deterministic concurrent-writer coverage.
- [x] Serialize append sequence allocation with an in-process lock plus POSIX `flock`, while keeping a non-POSIX thread-safe fallback.

---

## Task 3 — Session-aware orchestrator integration

**Files:**
- `tests/test_session_orchestrator.py`
- `src/hermes_ultra/session_orchestrator.py`
- Preserve unchanged: `src/hermes_ultra/capability_context.py`

- [x] Write RED integration contracts proving base orchestrator behavior is unchanged and session-aware execution records task/context/tool/outcome events.
- [x] Prove RED in CI because the adapter module did not exist.
- [x] Implement the thin adapter around existing context sources, tool executor, and verifier.
- [x] Reject task/session mismatch before model/tool execution.
- [x] Make task initialization idempotent across resumed runs and reject objective rebinding.
- [x] Preserve the base orchestrator as routing, escalation, approval, verification, and memory authority.

---

## Task 4 — Governed progressive MCP integration

**Files:**
- `tests/test_mcp_progressive.py`
- `src/hermes_ultra/mcp_progressive.py`

- [x] Write RED contracts for active-only discovery, delegated identity filtering, autonomous read/reversible dispatch, destructive-boundary blocking, and explicit spend-boundary preservation.
- [x] Prove RED in CI because `hermes_ultra.mcp_progressive` did not exist.
- [x] Implement `McpProgressiveCapabilityFacade` using only `McpGateway.visible_tools(...)` to construct its transient catalog.
- [x] Preserve candidate/inactive provider exclusion and delegated provider/profile/capability filtering before model visibility.
- [x] Route actual execution through `McpGateway.call_tool(...)` so the gateway retains its defensive advertised-tool refresh and delegated-capability checks.
- [x] Correct the dispatch contract to treat the gateway's defensive second `tools/list` as expected behavior while requiring exactly one final `tools/call`.

---

## Task 5 — Public API and documentation

**Files:**
- `src/hermes_ultra/__init__.py`
- `docs/superpowers/specs/2026-09-01-progressive-capability-session-context-design.md`
- this plan

- [x] Export progressive runtime, MCP facade, session environment, and session-aware orchestrator from `hermes_ultra`.
- [x] Document the actual governed MCP path.
- [x] Document concurrent session-write semantics and idempotent task initialization.
- [x] Preserve no-production-deploy scope.

---

## Task 6 — Final verification and publication

- [ ] Require the final GitHub `test` workflow to pass on the final PR merge-ref against current `main`. This must include source compilation, full pytest, regression suites, and secret scans.
- [ ] Require `cloud-foundation-validate` to pass on the same final PR head/merge-ref.
- [ ] Verify current `main` immediately before completion and verify GitHub's PR merge-ref is built from the final feature head plus that current `main`.
- [ ] Update PR #37 body with final architecture and verification evidence; remove the obsolete intentional-RED status.
- [ ] Mark PR #37 ready for review only after both final workflows are green.
- [x] Do not merge automatically; retain the feature branch/PR for the user's integration decision.
- [x] Do not production-deploy from this change.
