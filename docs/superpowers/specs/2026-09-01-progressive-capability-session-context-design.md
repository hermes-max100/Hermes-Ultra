# Progressive Capability Runtime and Executable Session Context

## Status

Approved and implemented on the feature branch on 2026-09-01. This design covers the two approved Hermes/JARVIS upgrades: progressive capability discovery/compact dispatch and rebuildable executable session context. The implementation also includes the MCP integration required to make progressive discovery the real model-facing path for governed MCP tools.

## Goals

1. Keep the model-facing capability surface compact while preserving access to the governed capability catalog.
2. Allow autonomous on-demand expansion of reversible capabilities through the existing `CapabilityExpansionController` and approval registry.
3. Route governed MCP tools through progressive discovery/description/dispatch without weakening the existing MCP gateway's lifecycle, profile, delegated-identity, or capability-scope checks.
4. Never let discovery, description, or dispatch promote, install, enable, activate, or reroute a provider.
5. Keep Scout discovery/proposal-only. Governance remains the sole authority over trusted, installed, canary, active, and runtime-enabled states.
6. Add durable append-only task/session state that keeps large payloads outside model context and lets trusted runtime code search, bind, retrieve, and compute over prior state.
7. Make the executable workspace disposable and rebuildable from the append-only session log and content-addressed payload store.
8. Preserve existing approval boundaries only for explicit consequential actions, authorization-scope violations, irreversible deployment/deletion, spending, and other already-governed categories.

## Non-goals

- No new provider router. Existing provider/model routing remains authoritative.
- No second skill/provider governance database.
- No Scout promotion authority.
- No arbitrary `eval`, shell execution, or model-supplied Python in the session environment.
- No new routine human approval step for reversible local or already-authorized reversible remote work.
- No replacement of the existing evidence recorder or durable memory authority.
- No production deployment in this change.

## Part 1 — Progressive capability runtime

### Generic model-facing surface

`src/hermes_ultra/progressive_capabilities.py` exposes:

- `discover(task, query, limit)` — deterministic progressive retrieval over an injected `CapabilityCatalog`; returns compact summaries plus complete discoverability metadata.
- `describe(capability_id)` — returns the complete `RuntimeCapabilityDescriptor` metadata for one known capability.
- `dispatch(...)` — dispatches exactly one capability to an injected executor after runtime-availability checks and, when required, the existing capability-expansion/approval boundary.

Discovery reuses `CapabilityProjector` ranking semantics rather than adding a second ranking policy. Omission from a shortlist therefore never becomes loss of discoverability.

If a descriptor is known but `available=False`, it may be discovered/described but is not dispatchable. The progressive runtime never mutates provider, lifecycle, registry, approval, Scout, or routing state.

### Dispatch behavior

`ProgressiveCapabilityRuntime.dispatch` accepts a concrete `ActionContext`. If the current task projection omitted the capability, it uses the existing `CapabilityExpansionController`.

- Reversible local work expands autonomously.
- Reversible remote work within existing authorization scope expands autonomously.
- Existing consequential categories and explicit irreversible/destructive/spend effects return recoverable `AUTHORITY_REQUIRED` before execution.
- Missing authorization scope returns recoverable `AUTHORITY_REQUIRED` before execution.
- Unknown capability returns recoverable `DEPENDENCY_MISSING`.
- Executor failure semantics are preserved through `CapabilityResult`.

The injected executor remains responsible for actual provider/model/tool routing.

## Part 1A — Governed progressive MCP facade

`src/hermes_ultra/mcp_progressive.py` exposes `McpProgressiveCapabilityFacade` and `McpCapabilityBinding`.

The facade is the MCP-specific bridge that makes the compact capability surface operational instead of merely library-level.

### Catalog construction

For every request, the facade builds a transient `CapabilityCatalog` exclusively from `McpGateway.visible_tools(...)`.

That means existing gateway authority is applied **before** a capability becomes model-visible:

- provider must already be `LifecycleState.ACTIVE`,
- profile visibility or an allowed temporary provider override must pass,
- delegated identity must allow the provider and profile,
- delegated capability grants must match the tool,
- requested capability narrowing remains in force.

Candidate, quarantined, installed-but-inactive, or otherwise non-active providers never enter progressive discovery. Scout candidates therefore remain proposals and cannot become runtime tools through this facade.

Capability IDs use the stable form:

`mcp:<provider_id>:<tool_name>`

Descriptors preserve MCP provider/tool provenance and tool annotations. A destructive MCP annotation maps to an explicit consequential effect; ordinary non-destructive MCP calls remain reversible remote work unless the caller supplies a more specific `ActionContext` such as `spend_money`.

### MCP dispatch

Actual MCP execution still flows through `McpGateway.call_tool(...)`. The gateway therefore performs its normal defensive advertised-tool refresh and delegated-capability checks immediately before `tools/call`.

The facade does not cache around, bypass, or replace those checks. It translates gateway errors into the existing `CapabilityResult` failure taxonomy:

- permission/authority failure -> `AUTHORITY_REQUIRED`,
- missing governed binding -> `DEPENDENCY_MISSING`,
- MCP upstream failure -> `UPSTREAM_UNAVAILABLE`.

## Part 2 — Executable session context

### Storage model

`src/hermes_ultra/session_environment.py` implements a file-backed `SessionEnvironment` using stdlib plus existing evidence redaction/recording utilities.

Per task/session directory:

- `events.jsonl` — append-only canonical JSON records with monotonically increasing sequence numbers.
- `payloads/<sha256>.json` — content-addressed, redacted payload bodies stored outside the event log.

Every payload reference is `sha256:<hex>` over canonical UTF-8 JSON. Reads verify the digest and raise `SessionIntegrityError` on tampering, corruption, malformed event records, or sequence discontinuity.

The event log stores only event metadata, payload reference, sequence, timestamp, and optional binding name. Large payload bodies are not copied into the event stream.

### Concurrent append semantics

Hermes may have multiple autonomous workers operating on the same long-running task. Session append therefore serializes writers:

- an in-process `threading.RLock` prevents same-process writer races,
- POSIX `fcntl.flock` provides cross-process shared/exclusive locking,
- event sequence allocation occurs while the exclusive event-log lock is held,
- event writes are flushed and `fsync`ed before the lock is released.

This prevents parallel workers from allocating duplicate sequence numbers or interleaving records. On non-POSIX systems the implementation retains thread safety; the production Hermes target is POSIX/Linux where process-level locking is active.

### Events and rebuildable workspace

`SessionEnvironment.append(...)` records an event and may bind its payload to a stable workspace name. `rebuild_workspace()` replays the event stream and reconstructs current bindings without trusting a mutable snapshot.

Bindings point to content-addressed payloads. Rebinding a name creates another append-only event, preserving history.

### Search and projection

`select(...)` returns a bounded set of records filtered by event type, binding, or simple text query over canonical payload JSON. `project(...)` materializes only selected payloads.

This provides the long-horizon pattern Hermes needs:

`lossless external state -> bounded search/select -> minimal context projection`

rather than repeatedly serializing an ever-growing task history back into the model prompt.

### Programmatic computation

`SessionComputeRegistry` contains trusted host-side operations. The model/runtime may select a registered operation by name and structured parameters but cannot supply arbitrary executable source.

`SessionEnvironment.compute(...)`:

1. verifies each input payload digest,
2. materializes the verified inputs,
3. invokes a registered trusted operation,
4. stores the derived output content-addressed,
5. appends a `compute` event with operation/input provenance,
6. optionally binds the result into the rebuildable workspace.

This preserves executable-context capability without adding a general arbitrary-code surface.

### Evidence integration

When an existing `EvidenceRecorder` is injected, append/compute operations record a compact evidence envelope containing event metadata and payload digest, not the full payload. Session context is operational state, not a replacement governance/evidence authority.

## Part 2A — Orchestrator integration

`src/hermes_ultra/session_orchestrator.py` provides `SessionAwareCapabilityContextOrchestrator`, a thin adapter/subclass around the existing `CapabilityContextOrchestrator`.

The base orchestrator is intentionally unchanged and remains authoritative for:

- capability classification,
- provider/model routing,
- tool escalation,
- capability expansion,
- approval boundaries,
- verification semantics,
- memory writes.

The session adapter only records:

1. one canonical task initialization event,
2. successful context-source items,
3. successful tool-result items,
4. accepted outcomes.

Task initialization is idempotent across resumed runs. A session cannot be rebound to a different task ID, and a different objective for an already-initialized session returns recoverable `ADAPTER_REJECTED` before model/tool execution.

## Authority invariants

The implementation must preserve all of the following:

- Scout may discover/propose candidates but cannot make them runtime-visible.
- Governance remains the sole authority over trusted/installed/canary/active/runtime-enabled lifecycle states.
- Progressive discovery does not grant permission.
- Progressive dispatch does not activate or promote providers.
- MCP progressive discovery includes only tools already visible through the governed gateway.
- Reversible in-scope work remains autonomous.
- Existing explicit consequential/spend/irreversible/authorization boundaries remain intact.
- Session compute never accepts arbitrary model-supplied executable code.
- Session state does not replace the evidence ledger or durable memory authority.

## Verification requirements

### Progressive runtime

- bounded discovery while preserving full discoverability metadata,
- full description metadata,
- unknown/unavailable capabilities never execute,
- omitted reversible capability expands autonomously,
- consequential/authorization-bound work does not execute,
- executor failures retain taxonomy.

### MCP facade

- only active governed MCP providers/tools enter discovery,
- delegated identity filtering occurs before progressive discovery,
- ordinary read/reversible MCP tools dispatch autonomously,
- destructive MCP annotations hit the existing consequential boundary before `tools/call`,
- explicit spend `ActionContext` preserves the existing spend boundary,
- actual execution goes through `McpGateway.call_tool` and retains its defensive tool-advertisement recheck.

### Session environment

- content-addressed external payload storage,
- secret redaction before persistence,
- exact reopen/rebuild behavior,
- payload tamper detection,
- event-sequence corruption detection,
- deterministic concurrent append serialization,
- trusted compute provenance,
- bounded select/project behavior.

### Session orchestrator

- base orchestrator behavior unchanged without the adapter,
- task/context/tool/outcome events recorded with adapter,
- task/session mismatch fails before execution,
- resumed runs initialize the task exactly once.

## Acceptance criteria

- Full repository test workflow passes on the PR merge-ref against current `main`.
- Cloud foundation validation passes on the same final PR head.
- Source compilation, regression suites, and secret scans remain green.
- No production deployment is performed.
- No new routine approval boundary is introduced.
- Scout/governance authority separation is preserved.
