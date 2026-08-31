# Autonomy-First Oh My Hermes Integration

**Date:** 2026-08-31  
**Status:** Design approved in principle; implementation pending written-spec review  
**Target:** `hermes-max100/Hermes-Ultra`  
**External research source:** `rlaope/oh-my-hermes`

## 1. Decision

Hermes Ultra will selectively and deeply integrate useful operating-layer concepts from Oh My Hermes (OMH) while preserving Hermes Ultra as the authoritative autonomous runtime.

This is **not** a wholesale OMH installation and **not** a new policy layer above Hermes Ultra.

The integration must increase practical capability, context efficiency, observability, verification quality, and self-repair without turning normal reversible work into approval-driven execution.

The core rule is:

> **Capability is preserved by default. Projection narrows context, not authority. Low-consequence reversible capability expansion is autonomous and auditable. Governance remains concentrated at genuinely consequential boundaries.**

## 2. Design Principles

### 2.1 Autonomy first

A capability omitted from the initial task projection is not automatically forbidden.

If Hermes discovers during execution that another capability is useful and the action remains low-consequence and reversible, Hermes may add that capability to the task scope and continue without a new human approval round trip.

The system records the expansion as evidence rather than using a frozen grant as a universal stop gate.

### 2.2 Governance is a consequence boundary, not a blanket permission filter

Existing narrow approval boundaries remain for materially consequential operations such as:

- destructive or difficult-to-reverse production changes;
- credential, identity, authentication, or security-boundary changes;
- material spending outside an already authorized allowance;
- actions whose external consequences cannot reasonably be reversed.

Normal research, planning, local file work, tests, skill/tool discovery, reversible configuration work, isolated worktree operations, diagnostics, and other bounded low-consequence actions should not acquire new approval friction from this integration.

### 2.3 Evidence informs execution; it does not paralyze it

Hermes Ultra should retain OMH's useful distinction between:

- **prepared** — a plan, route, configuration, or capability is available;
- **observed** — execution or runtime behavior was actually seen;
- **verified** — an explicit verification gate produced supporting evidence.

These evidence states affect confidence and completion claims. They do not automatically make a reversible capability unusable.

### 2.4 One authoritative router

OmniRoute remains the authoritative production model router.

OMH model categories and routing metadata may inform OmniRoute policy or evaluation, but OMH must not:

- replace OmniRoute;
- create a second independent routing authority;
- silently write Hermes model aliases;
- bypass existing direct-provider requirements for sensitive profiles.

### 2.5 One authoritative durable memory system

OMH's long-term-memory subsystem is out of scope for tranche 1.

No second durable memory source of truth will be introduced until its storage model, retention behavior, provenance, conflict handling, and interaction with Hermes Ultra persistence are separately evaluated.

## 3. First Integration Tranche

### 3.1 Task-scoped capability catalog and projection

Create a machine-readable Hermes Ultra capability catalog that can be projected for a specific task.

A projection should contain the smallest useful working set instead of loading the full capability inventory into context.

Each projected capability should expose bounded metadata such as:

- stable capability ID;
- family/category;
- one-line purpose;
- match reason;
- expected utility or relevance score;
- consequence/reversibility class;
- required interface or provider when known;
- evidence state where relevant.

Capabilities left out of the projection remain discoverable.

Exclusion reasons are observability metadata, not blanket denials. Suggested closed vocabulary:

- `not_relevant_to_request`;
- `outranked_by_shortlist`;
- `beyond_context_budget`;
- `unavailable_in_current_runtime`;
- `consequential_boundary_requires_authorization`.

A capability should **not** be labeled unauthorized merely because it was absent from the first projection.

### 3.2 Context budgeting without capability loss

Projection must enforce a context budget so routing/catalog information cannot crowd out the user's task.

When the budget is exceeded:

1. remove the least relevant projected detail first;
2. degrade to summaries before dropping capability discoverability;
3. record what was omitted;
4. permit later on-demand expansion.

The invariant is:

> **Context compression may reduce what is loaded now, but it must not silently reduce what Hermes can do.**

### 3.3 Autonomous capability expansion

When Hermes needs a capability outside the current projection, it performs an expansion decision.

For low-consequence reversible work, expansion proceeds automatically and emits an append-only observation containing at least:

- task ID;
- capability ID;
- reason for expansion;
- expected utility;
- consequence class;
- reversibility assessment;
- source/provenance of the capability;
- timestamp or sequence position;
- eventual observed result when available.

The expansion mechanism is deliberately different from OMH's frozen-authority model. The task projection is an execution aid, not an authorization ceiling.

For a capability that crosses an existing consequential boundary, Hermes records the proposed expansion and routes that specific action through the existing authorization mechanism. Other reversible work may continue when technically independent.

### 3.4 Capability provenance and trust state

Discovered external capabilities remain untrusted until they pass the existing Hermes Ultra supply-chain lifecycle.

OMH itself should enter as a pinned, reviewable upstream source rather than an implicit runtime dependency.

Initial provenance references:

- stable baseline release: OMH `v2.0.0`;
- release wheel SHA-256: `302ef2e629d99159a5e059c754a13e93c3435088b518af69a378da902ee45725`;
- research snapshot observed on 2026-08-31: `06df4eac8f300d9aa27290661f9edb0fb61e9b9d`.

If source code is reused rather than concepts reimplemented, the exact upstream commit/blob must be pinned and MIT attribution/license obligations preserved.

### 3.5 Verification and diagnostics

Adopt the useful OMH pattern that verification depends on the surface being changed.

Examples:

- plugin changes: real import/register/load smoke;
- frontend changes: rendered desktop/mobile verification;
- dependency/build metadata: installation/import smoke;
- workflow/CI changes: syntax and local equivalent checks;
- runtime configuration: live health/readiness observation where feasible.

Verification hooks supplement normal tests and proof-before-success behavior.

They must not become a universal pre-action blocker for reversible exploration. Their primary enforcement point is before Hermes claims an outcome is complete, healthy, deployed, or verified.

### 3.6 Self-diagnostics

Introduce a bounded diagnostics surface inspired by `omh doctor` / `omh probe` that can answer:

- what capabilities are installed or discoverable;
- what is currently loaded/observed;
- which providers/interfaces are available;
- which dependencies are missing;
- which runtime components are unhealthy;
- what repair action is recommended;
- whether the diagnosis is inferred, observed, or verified.

Diagnostics should prefer autonomous repair when the repair is reversible and within the current consequence boundary.

## 4. Routing Integration

OMH category concepts such as deep reasoning, architecture, quick tasks, writing, visual engineering, and review may be mapped into OmniRoute as advisory task metadata.

The mapping should be one-way:

`task/capability metadata -> OmniRoute decision`

not:

`OMH router -> provider/model execution`

OmniRoute continues to own provider pools, circuit breaking, caching, usage policy, fallbacks, multimodal routing, and profile-specific direct-provider requirements.

## 5. Coding and Worktree Integration

OMH's worktree, coding handoff, specialist, and independent-review concepts are candidates for tranche 2 after the capability/expansion foundation is proven.

They should extend the existing Hermes Ultra / Orca / coding-agent architecture rather than create a competing executor runtime.

Expected future pattern:

1. project the task-scoped capabilities;
2. choose or create an isolated workspace when appropriate;
3. delegate implementation/research/review lanes;
4. preserve executor identity and evidence;
5. independently verify output;
6. feed observed results back into capability utility metrics.

## 6. Explicit Non-Goals for Tranche 1

Do **not**:

- run `omh setup` wholesale on the production AWS host;
- make OMH the runtime authority above Hermes Ultra;
- replace OmniRoute or 9Router behavior;
- replace Orca or existing coding executors;
- enable OMH as a second durable memory authority;
- let OMH write model aliases automatically;
- adopt OMH themes/HUD as part of this tranche;
- copy OMH's frozen capability authority as a general execution restriction;
- make missing verification evidence equivalent to a blanket capability denial.

## 7. Data Model Direction

The implementation should favor small immutable records over mutable hidden state.

Suggested logical records:

### `CapabilityDescriptor`

Describes a capability independently of a task.

### `CapabilityProjection`

A deterministic, budgeted task-scoped view over the catalog.

### `CapabilityExpansionEvent`

Append-only evidence that Hermes expanded the working capability set, including why and under what consequence class.

### `CapabilityObservation`

Records prepared, observed, or verified evidence for execution/results.

These records should integrate with the existing Hermes Ultra evidence/ledger architecture rather than introduce a separate persistence system.

## 8. Consequence Classification

The first implementation should use a deliberately small classification surface rather than a complex new governance engine.

Suggested minimum:

- `REVERSIBLE_LOCAL` — autonomous;
- `REVERSIBLE_REMOTE` — autonomous when within existing profile/authorization scope;
- `CONSEQUENTIAL` — route only the consequential action through the existing approval boundary.

The classifier should be explicit and testable. It must not silently upgrade ordinary tool use into `CONSEQUENTIAL` merely because the tool is powerful.

## 9. Learning and Utility Feedback

Capability expansion events should eventually support learning which capabilities deserve context and compute.

Useful metrics include:

- projection hit rate;
- expansion frequency;
- expansion success/failure;
- context bytes/tokens saved;
- tool calls avoided;
- verification success rate;
- completed outcome rate;
- cost per completed outcome where applicable.

These metrics are advisory inputs for future projection/routing optimization, not automatic grounds for deleting capabilities.

## 10. Acceptance Criteria

Tranche 1 is accepted only when all of the following are demonstrated with command/test evidence:

1. Existing Hermes Ultra baseline capabilities remain reachable.
2. A task projection loads a smaller relevant working set than the full catalog.
3. A capability excluded from the initial projection remains discoverable.
4. A synthetic low-consequence task autonomously expands to an initially omitted capability and continues execution without a human approval prompt.
5. The expansion produces an auditable immutable event with reason, consequence class, and result/evidence state.
6. A synthetic consequential operation is isolated and routed through the existing authorization boundary without blocking independent reversible work.
7. Evidence state (`prepared`, `observed`, `verified`) affects completion claims without acting as a universal capability ban.
8. OmniRoute remains the sole authoritative production model router.
9. No second durable memory authority is introduced.
10. Existing supply-chain, secret-scan, rollback, release-provenance, and production validation gates continue to pass.
11. Clean-clone or equivalent isolated replay succeeds.
12. No production deployment occurs until the canonical CI-built release artifact passes the existing release gates.

## 11. Alternatives Considered

### A. Install OMH wholesale

**Rejected.** It would add a second managed plugin/configuration/routing surface in places already owned by Hermes Ultra and could create duplicated authority or configuration drift.

### B. Use OMH only as documentation/inspiration

**Rejected.** This leaves substantial runtime value on the table, especially task-scoped projection, evidence boundaries, diagnostics, and orchestration concepts.

### C. Selective deep graft into Hermes Ultra

**Selected.** Reuse or reimplement the strongest OMH concepts inside Hermes Ultra's existing runtime, evidence, routing, supply-chain, and deployment architecture while rewriting authority behavior around autonomous expansion.

## 12. Implementation Sequence After Written-Spec Review

1. map the existing Hermes Ultra capability/evidence interfaces;
2. write failing acceptance tests for projection and autonomous expansion;
3. implement the minimal capability descriptor/projection records;
4. implement append-only expansion evidence;
5. integrate the small consequence classifier with existing authorization boundaries;
6. add diagnostics/verification surfaces;
7. run focused tests, full suite, secret scan, release checks, and clean replay;
8. review before merge;
9. build only from canonical `main` CI after merge;
10. deploy through the existing rollback-safe production path and independently verify live health/provenance.

## 13. Architectural Invariant

The integration is incorrect if Hermes becomes less capable merely because the initial context projection was narrower.

**Projection controls attention. Consequence boundaries control exceptional actions. Neither is allowed to become a blanket reduction in Hermes Ultra's autonomous capability.**
