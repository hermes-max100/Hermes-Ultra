# Progressive Capability Runtime and Executable Session Context

## Status

Approved for implementation on 2026-09-01. This design implements the two approved Hermes/JARVIS upgrades: progressive capability discovery/compact dispatch and a rebuildable executable session-context layer.

## Goals

1. Keep the model-facing capability surface compact while preserving access to the full governed capability catalog.
2. Allow autonomous, on-demand expansion of reversible capabilities through the existing `CapabilityExpansionController` and approval registry.
3. Never let discovery, description, or dispatch promote, install, enable, or route a provider.
4. Keep Scout discovery/proposal-only. Governance remains the sole authority over trusted, installed, canary, active, and runtime-enabled states.
5. Add durable, append-only task/session state that keeps large payloads outside model context and lets trusted runtime code search, bind, retrieve, and compute over prior state.
6. Make the executable workspace disposable and rebuildable from the append-only session log and content-addressed payload store.
7. Preserve existing approval boundaries only for explicit consequential actions, authorization-scope violations, irreversible deployment/deletion, spending, and other already-governed categories.

## Non-goals

- No new provider router. OmniRoute and existing injected executors remain authoritative for provider/model routing.
- No second skill/provider governance database.
- No Scout promotion authority.
- No arbitrary `eval`, shell execution, or model-supplied Python in the session environment.
- No new routine human approval step for reversible local or already-authorized reversible remote work.
- No replacement of the existing evidence recorder or durable memory authority.

## Part 1 — Progressive capability runtime

### Model-facing surface

Add `src/hermes_ultra/progressive_capabilities.py` with a deliberately small public surface:

- `discover(task, query, limit)` — deterministic progressive retrieval over the existing `CapabilityCatalog`; returns compact summaries and catalog/discoverability metadata.
- `describe(capability_id)` — returns the complete `RuntimeCapabilityDescriptor` metadata for one known capability.
- `dispatch(...)` — dispatches exactly one capability to an injected executor after verifying that the descriptor is runtime-available and after applying the existing expansion/approval boundary when the task projection omitted it.

The runtime never changes lifecycle state, provider state, registry state, approval state, or routing state.

### Discovery

Discovery reuses the existing `CapabilityProjector` ranking semantics by creating a query-enriched task view. It does not duplicate a second ranking policy. Results expose compact summaries plus `discoverable_ids`, so omission from a shortlist never becomes loss of capability.

Unavailable descriptors may be discoverable and describable but are never dispatchable. This lets Hermes know that a capability exists without silently activating it.

### Dispatch

`ProgressiveCapabilityRuntime.dispatch` accepts:

- `task_id`
- `capability_id`
- structured `arguments`
- concrete `ActionContext`
- optional current `CapabilityProjection`
- `reason`
- `expected_utility`

If the descriptor is unknown, return `DEPENDENCY_MISSING`. If it exists but is not runtime-available, return recoverable `AUTHORITY_REQUIRED`; do not execute and do not attempt promotion. If a projection is present and omitted the requested capability, use the existing `CapabilityExpansionController`. Reversible local and already-authorized reversible remote actions expand autonomously and audibly. Existing consequential boundaries return `AUTHORITY_REQUIRED` and do not execute.

The injected executor is responsible for actual capability execution and existing routing. The progressive runtime preserves `CapabilityResult` semantics from that executor.

### Authority invariants

- Catalog construction is upstream of this runtime.
- `available=False` means discovery/description only.
- Expansion changes task working context only; it does not change governance state.
- No method may mutate the provider registry, toolkit registry, Scout candidate state, or routing configuration.

## Part 2 — Executable session context

### Storage model

Add `src/hermes_ultra/session_environment.py` implementing a file-backed `SessionEnvironment` using only stdlib and the existing evidence redaction/recording utilities.

Per task/session directory:

- `events.jsonl` — append-only canonical JSON records with monotonically increasing sequence numbers.
- `payloads/<sha256>.json` — content-addressed, redacted payload bodies stored outside the event log.

Every payload reference is a `sha256:<hex>` digest of canonical UTF-8 JSON bytes. Reads verify the digest and raise `SessionIntegrityError` on tampering or corruption.

The event log stores only event metadata, payload reference, sequence, timestamp, and optional binding name. Large payload bodies do not get copied into each event record.

### Events and workspace

`SessionEnvironment.append(...)` records an event and optionally binds its payload to a stable workspace name. `rebuild_workspace()` replays the append-only event stream and reconstructs current bindings without trusting any mutable snapshot.

Workspace bindings are pointers to content-addressed payloads, not mutable payload copies. Rebinding a name produces another append-only event; history remains intact.

### Search and projection

`select(...)` returns a bounded tuple of session records filtered by event type, binding, or simple text query over canonical payload JSON. `project(...)` materializes only selected payloads for model/runtime use. This is the mechanism for keeping the default prompt small while retaining exact historical state out of band.

### Programmatic computation

Add `SessionComputeRegistry`, a registry of trusted host-side operations. The model may select a registered operation by name and structured parameters, but may not provide arbitrary executable source.

`SessionEnvironment.compute(operation, input_refs, params, bind_as=None)`:

1. verifies every input payload digest,
2. invokes the registered trusted operation,
3. stores the derived result as a new content-addressed payload,
4. appends a `compute` event with provenance linking input refs and operation name,
5. optionally binds the result into the rebuildable workspace.

This preserves the key capability of executable context—programmatic filtering/joining/computation over long-lived state—without creating a new arbitrary-code execution surface.

### Evidence integration

If an existing `EvidenceRecorder` is injected, each append/compute operation records a compact evidence envelope containing the event metadata and payload digest, not the full payload. The session environment is operational context, not a replacement evidence or governance authority.

## Orchestrator integration

Add `src/hermes_ultra/session_orchestrator.py` with `SessionAwareCapabilityContextOrchestrator`, a thin adapter/subclass around the existing `CapabilityContextOrchestrator` rather than modifying the core routing loop.

The adapter wraps the already-injected context sources, tool executor, and verifier so it can record:

1. the task objective once at run start,
2. successful context-source `ContextItem`s,
3. successful tool-result `ContextItem`s,
4. the accepted final verification/outcome metadata.

The base `CapabilityContextOrchestrator` remains authoritative for classification, routing, tool escalation, capability expansion, approval boundaries, verification semantics, and memory writes. The session adapter records operational context only. A task/session ID mismatch fails recoverably before model or tool execution.

This isolation keeps the existing orchestrator unchanged for consumers that do not opt into long-horizon session state, while making the environment immediately usable by loops that do. `SessionEnvironment` exposes bounded projection/search APIs so future loops can replace repeated prompt replay with targeted projections without another storage-interface change.

## Failure behavior

- Unknown capability: recoverable `DEPENDENCY_MISSING`.
- Known but inactive/unavailable capability: recoverable `AUTHORITY_REQUIRED`; never auto-promote.
- Existing consequential boundary: recoverable `AUTHORITY_REQUIRED`; never execute.
- Executor failure: propagate the existing `CapabilityResult` failure unchanged where possible.
- Session payload corruption/hash mismatch: raise `SessionIntegrityError` before returning data to the model/runtime.
- Malformed session log record or sequence discontinuity: raise `SessionIntegrityError`.
- Task/session mismatch: recoverable `ADAPTER_REJECTED` before model or tool execution.
- Evidence-recorder failure must not mutate already-written session data.

## Testing requirements

### Progressive capability runtime

- Discovery returns a bounded compact shortlist while preserving full discoverability metadata.
- Description returns full descriptor metadata.
- Unknown and unavailable capabilities never call the executor.
- Omitted reversible capability expands autonomously and executes.
- Consequential or authorization-scope-bound capability does not execute.
- Dispatch preserves executor failure semantics.

### Session environment

- Payload bodies are stored content-addressed and outside `events.jsonl`.
- Secret-like values are redacted before persistence.
- Reopening the same session rebuilds bindings exactly from the event log.
- Payload tampering is detected.
- Sequence corruption is detected.
- Trusted compute operations create derived payloads with input/operation provenance and survive reopen/rebuild.
- Bounded selection/projection returns only requested records.

### Integration

- `CapabilityContextOrchestrator` works unchanged when the session adapter is not used.
- `SessionAwareCapabilityContextOrchestrator` records task/context/tool/outcome events without changing router selection or approval behavior.
- A task/session mismatch fails before execution and writes no session event.

## Acceptance criteria

- Focused tests pass.
- Full Python suite passes in CI.
- Secret scan and repository contract checks remain green.
- No production deployment is performed by this change.
- No new approval boundary is introduced for ordinary reversible autonomous work.
- Scout remains discovery/proposal-only and governance remains lifecycle authority.
