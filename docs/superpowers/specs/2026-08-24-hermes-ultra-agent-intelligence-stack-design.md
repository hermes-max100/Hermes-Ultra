# Hermes Ultra Agent Intelligence Stack — Design

**Date:** 2026-08-24

**Status:** Approved architecture — autonomy-first

## Objective

Integrate six upstream capability families into Hermes Ultra without replacing Hermes' existing orchestration, model-routing, evidence, or proof-before-success layers. The resulting system adds persistent code intelligence, multi-agent worktree execution, unrestricted Agent-Reach internet intelligence, curated external agent ingestion, Revenue OS media production, and a controlled benchmark lane for Graft.

**Controlling rule:** Hermes autonomy is the default operating condition. Hardening, validation, evidence collection, isolation, redaction, health checks, and policy enforcement must be automatic, narrow, reversible where practical, and non-blocking for ordinary autonomous work. Human approval is reserved for explicit high-consequence approval categories already defined by Hermes policy; security or hardening language must not create new blanket approval gates.

## Architectural Principles

1. **Autonomy is primary.** Ordinary research, coding, testing, self-improvement, agent selection, worktree execution, benchmarking, recovery, retries, local configuration, and reversible internal operations proceed autonomously. Hardening must support autonomy rather than displace it.
2. **Hermes remains the brain.** Upstream projects are subordinate capability providers. None may replace Hermes orchestration, model routing, evidence, or runtime policy.
3. **Existing model routing is authoritative.** Orca or any worker manager receives already-selected providers/workers from Hermes. It does not choose the global routing policy.
4. **Capabilities are replaceable adapters.** Hermes talks to stable internal interfaces, not directly to third-party implementation details.
5. **Evidence before success, not evidence before action.** Material actions produce machine-readable evidence, but evidence collection is performed automatically and must not become a human-approval checkpoint for ordinary work.
6. **Failure isolation with autonomous recovery.** A failed optional upstream capability degrades its own lane; Hermes retries, falls back, reroutes, or continues in degraded mode whenever a viable path remains.
7. **No duplicated source of truth.** Codebase Memory is the primary structural code graph. Graft remains benchmark-only until promoted by reproducible evidence.
8. **Unrestricted Agent-Reach means full supported channel availability.** Hermes does not impose a content-source allowlist over supported Agent-Reach channels. Authentication remains local/upstream and secret material is automatically redacted from persisted evidence.
9. **Promotion is evidence-driven and may be autonomous.** Reproducible tests, benchmarks, and policy checks determine promotion. Human approval is not required merely because a component is new; only an existing explicit high-consequence category can require it.
10. **Hardening cannot silently expand scope.** A control introduced for secrets, provenance, prompt injection, branch protection, dependency integrity, or health checking may not be generalized into a stop-the-agent gate unrelated to the concrete risk it addresses.

## Top-Level Architecture

```text
HERMES ULTRA
│
├── Autonomous Core Orchestrator / Router / Evidence
│
├── Code Intelligence Plane
│   ├── Codebase Memory MCP              [primary]
│   └── Graft Benchmark Harness          [experimental]
│
├── Coding Swarm Execution Plane
│   ├── Hermes task decomposition
│   ├── existing subscription/model router
│   ├── isolated Git worktrees
│   ├── Orca adapter / worker fleet
│   └── automatic verifier + winning-patch promotion
│
├── Internet Intelligence Plane
│   └── Agent-Reach adapter              [all supported channels]
│
├── Agent Library Plane
│   ├── existing Hermes agents/skills
│   └── Agency Agents ingestion + dedupe + automatic qualification
│
├── Revenue OS
│   └── OpenMontage media-production adapter
│
└── Evidence Plane
    ├── provenance
    ├── health/doctor results
    ├── test results
    ├── benchmark results
    ├── worker outcomes
    └── autonomous promotion decisions
```

## Autonomy Contract

### Default State

A Hermes action is autonomous unless it falls into an explicit high-consequence approval category already defined outside this integration. This integration must not invent additional approval categories.

### Controls That Must Be Automatic

The following are implementation controls, not user-interaction gates:

- secret redaction;
- provenance capture;
- health checks;
- dependency verification;
- worktree isolation;
- test execution;
- rollback preparation;
- retry/backoff;
- fallback provider selection;
- prompt-injection treatment of external content as untrusted data;
- agent-definition normalization and scoring;
- benchmark qualification;
- evidence persistence.

When one of these controls fails, Hermes should attempt repair, retry, alternate tooling, or degraded-mode continuation before considering the task blocked.

### Human Approval Boundary

Human approval may be required only when the requested action itself falls into an existing explicit high-consequence category. Hardening failures, low confidence, unfamiliar upstream software, or the presence of authentication do not by themselves create an approval requirement.

## Component 1 — Codebase Memory MCP

### Purpose

Provide persistent structural knowledge of repositories to Hermes and coding workers before code modification.

### Internal Interface

Hermes exposes an internal `CodeIntelligenceProvider` contract with operations equivalent to:

- `index_repository(repo_path, ref)`
- `lookup_symbol(symbol)`
- `find_callers(symbol)`
- `find_dependencies(path_or_symbol)`
- `find_routes(service_or_path)`
- `impact_analysis(changed_paths_or_symbols)`
- `health()`

The adapter may call the upstream MCP server, but Hermes consumers depend only on this internal interface.

### Autonomous Pre-Edit Flow

Before a coding worker edits code, Hermes automatically:

1. identifies the subsystem;
2. queries the structural graph;
3. identifies callers and dependencies;
4. identifies likely impacted tests;
5. records change-intent evidence;
6. creates or assigns an isolated worktree;
7. allows the worker to edit without a human checkpoint;
8. executes tests;
9. reruns impact analysis against the changed set;
10. records proof-before-success evidence;
11. promotes or rejects the candidate according to automated policy and verification results.

### Failure Behavior

If Codebase Memory is unavailable, Hermes automatically falls back to repository-native search or another qualified provider and marks `degraded_context=true`. Unavailability of the preferred graph does not stop ordinary autonomous work when a viable fallback exists.

## Component 2 — Orca Worktree Fleet

### Purpose

Provide isolated parallel execution for coding workers such as Hermes Agent, Codex, Claude Code, Gemini, Kimi, Kiro, or future providers selected by the existing Hermes router.

### Boundary

Orca is an execution substrate, not a routing authority.

Hermes owns:

- task decomposition;
- provider/model selection;
- subscription/API lane selection;
- autonomous concurrency decisions;
- worktree lifecycle policy;
- verifier selection;
- patch acceptance and promotion;
- existing high-consequence approval policy where applicable.

The Orca adapter owns:

- spawning assigned workers;
- mapping workers to isolated worktrees;
- reporting stdout/stderr/exit state;
- reporting worker completion;
- cancelling failed or superseded workers;
- returning candidate patches/results to Hermes.

### Candidate Promotion

Workers remain isolated from protected branches while they work. Hermes automatically:

1. verifies tests;
2. checks applicable policy;
3. compares candidate evidence;
4. selects a winner or synthesizes a new candidate;
5. promotes the verified change when no explicit high-consequence approval category applies.

Protected-branch isolation is a technical integrity mechanism, not a standing human-approval gate.

## Component 3 — Agent-Reach Unrestricted Internet Intelligence

### Purpose

Expose every supported Agent-Reach channel through Hermes while retaining Agent-Reach's own backend selection and health diagnostics.

### Channel Policy

Hermes supports the upstream `channels=all` install/runtime mode and must not maintain a Hermes-side content-source allowlist that artificially disables supported Agent-Reach channels.

Expected optional channel families include:

- OpenCLI;
- Twitter/X;
- Reddit;
- Facebook;
- Instagram;
- LinkedIn;
- Xiaohongshu;
- Bilibili;
- Xueqiu;
- XiaoYuZhou;
- future channels discovered through supported upstream capability enumeration.

Zero-config upstream capabilities such as web reading, YouTube, RSS, GitHub, semantic search, V2EX, and similar supported sources remain available through the same adapter.

### Authentication Boundary

Hermes may autonomously use authenticated adapters once credentials/session state have been configured by an authorized owner-controlled mechanism. Authentication material stays in the upstream/local configuration or process environment and is automatically redacted from evidence and logs. The existence of authenticated access does not demote the channel to read-only or require per-use approval.

### Health and Evidence

`agent-reach doctor` or the current upstream equivalent is captured as structured health evidence. A channel failure degrades only that channel or route. Hermes automatically attempts another supported backend or source before declaring the requested capability unavailable.

## Component 4 — Agency Agents Curated Ingestion

### Purpose

Increase the available specialist agent/skill catalog without flooding runtime selection with duplicates or low-quality overlapping prompts.

### Ingestion States

Every imported definition moves through an automatic qualification pipeline:

```text
DISCOVERED -> NORMALIZED -> SCORED -> QUALIFIED -> ACTIVE
                           \-> REJECTED
```

A temporary isolation state may be used during parsing or testing, but it must not require human approval for ordinary low-risk agent definitions.

### Dedupe and Scoring

The ingestion layer automatically evaluates:

- semantic overlap with existing Hermes agents/skills;
- declared capabilities;
- required tools;
- privilege/risk level;
- conflicting or manipulative instruction patterns;
- provenance and upstream revision;
- measurable value versus existing agents.

Qualified candidates may become `ACTIVE` automatically. Only candidates that request an existing explicit high-consequence capability are subject to the corresponding approval policy when that capability is actually exercised.

### Runtime Rule

`ACTIVE` definitions are eligible for orchestration. Rejected definitions remain inspectable but cannot execute until rescored or repaired. Qualification is designed to improve routing quality, not to reduce autonomy.

## Component 5 — OpenMontage Revenue OS Adapter

### Purpose

Expose media-production workflows to Revenue OS without coupling the Hermes core to a specific video engine.

### Internal Workflow Contract

Revenue OS submits a media job containing:

- objective;
- audience;
- campaign/project context;
- source material;
- required outputs;
- brand constraints;
- publication intent.

The adapter may coordinate stages autonomously:

```text
research -> script -> asset plan -> asset acquisition/generation
-> narration -> subtitles -> render -> QA -> evidence bundle
```

### Publication Boundary

Research, creation, rendering, QA, packaging, and reversible staging proceed autonomously. External publication/posting is governed only if the action falls into an existing explicit external-communication or other high-consequence approval category; the media-production pipeline itself must not stop early merely because publication may later require separate authorization.

## Component 6 — Graft Benchmark Harness

### Purpose

Test whether Graft materially improves Hermes performance relative to Codebase Memory or baseline repository-native context retrieval.

### Experimental Status

Graft is not in the mandatory runtime context path at initial integration, but Hermes may benchmark it autonomously and may promote it autonomously when configured promotion criteria are met and no explicit high-consequence approval category is implicated.

### Benchmark Design

Use the same fixed Hermes repository tasks across:

- baseline repository-native search;
- Codebase Memory MCP;
- Graft;
- optional combined experimental mode when testing complementarity.

Capture at minimum:

- wall-clock latency;
- tool-call count;
- input/output token consumption where observable;
- model/API cost where applicable;
- context retrieval precision/recall proxy metrics;
- task success rate;
- tests passed/failed;
- incorrect-file edit rate;
- regression rate;
- evidence completeness.

### Promotion Rule

Graft may be promoted through an automatic configuration decision after reproducible Hermes-local evidence meets defined promotion thresholds. Promotion must be reversible and recorded in evidence. No human checkpoint is required solely because the promoted provider is third-party software.

## Shared Evidence Schema

Each capability invocation emits a normalized evidence envelope:

```json
{
  "run_id": "...",
  "task_id": "...",
  "capability": "codebase-memory|orca|agent-reach|agency-agents|openmontage|graft",
  "provider_version": "...",
  "input_digest": "sha256:...",
  "started_at": "RFC3339",
  "finished_at": "RFC3339",
  "status": "success|failure|degraded|cancelled",
  "failure_class": null,
  "artifacts": [],
  "tests": [],
  "health": {},
  "provenance": {},
  "redactions_applied": true,
  "human_approval_required": false,
  "approval_category": null
}
```

`human_approval_required` defaults to `false`. It may become `true` only when an existing explicit high-consequence policy category applies to the action itself.

Secrets, cookies, bearer tokens, authorization headers, passwords, session IDs, and provider credentials are automatically redacted before evidence persistence.

## Configuration Model

Hermes configuration uses capability-scoped settings rather than embedding third-party configuration globally. Example logical shape:

```yaml
autonomy:
  default: autonomous
  ordinary_operations_require_approval: false
  hardening_mode: automatic_non_blocking
  retry_before_block: true
  fallback_before_block: true
  approvals: existing_high_consequence_categories_only

capabilities:
  code_intelligence:
    primary: codebase_memory
    fallback: native_repo_search
    graft:
      mode: benchmark_and_auto_promote
      promotion_reversible: true

  coding_swarm:
    executor: orca
    router: existing_hermes_router
    worktree_isolation: required
    autonomous_candidate_promotion: true

  internet_intelligence:
    provider: agent_reach
    channels: all
    preserve_upstream_fallbacks: true
    authenticated_channels_require_per_use_approval: false

  agent_library:
    agency_agents:
      ingestion: curated_automatic
      automatic_activation: true

  revenue_os:
    media_production:
      provider: openmontage
```

## Failure Taxonomy

At minimum, normalize failures into:

- `DEPENDENCY_MISSING`
- `AUTH_REQUIRED`
- `AUTH_FAILED`
- `UPSTREAM_UNAVAILABLE`
- `RATE_LIMITED`
- `TIMEOUT`
- `POLICY_BLOCKED`
- `HEALTHCHECK_FAILED`
- `WORKER_FAILED`
- `TEST_FAILED`
- `EVIDENCE_INCOMPLETE`
- `PROVENANCE_FAILED`
- `BENCHMARK_REGRESSION`
- `UNKNOWN`

The core preserves the original stderr/error payload in a redacted artifact while exposing the normalized class to orchestration. Before treating recoverable failures as blocking, Hermes attempts the configured retry, repair, fallback, reroute, or degraded-mode path.

## Autonomy, Security, and Governance

- Autonomous execution is the default; controls run around the agent loop, not as routine human checkpoints inside it.
- No upstream package receives implicit authority to replace Hermes orchestration or approval policy.
- Worktree/protected-branch isolation prevents accidental corruption but does not require manual promotion for ordinary verified changes.
- Secret redaction is automatic and must not disable authenticated capabilities.
- Third-party agent definitions are machine-qualified before activation; qualification does not create a blanket human-review requirement.
- Internet-source content is treated as untrusted data and cannot rewrite Hermes policy merely by containing instructions; this is a parsing/execution boundary, not a ban on using the content.
- Health checks, provenance checks, and dependency checks are advisory/recovery inputs unless their concrete failure makes the requested operation impossible or unsafe under an existing explicit policy category.
- External actions are governed only by the existing explicit high-consequence approval categories applicable to those actions.
- No integration component may introduce a generic `require_human_approval=true` default.
- New hardening controls must include a documented autonomous recovery/fallback behavior and a test proving ordinary work continues when the control's preferred path is unavailable.

## Testing Strategy

### Unit Tests

- adapter command construction;
- environment propagation;
- secret redaction without capability disablement;
- health result normalization;
- failure classification;
- autonomous retry/fallback behavior;
- capability discovery;
- Agency Agents deduplication/scoring and automatic activation;
- Graft reversible auto-promotion guard;
- evidence schema validation;
- `human_approval_required` defaults false;
- approval can be raised only by an explicit registered high-consequence category.

### Integration Tests

- Codebase Memory graph query against a fixture repository;
- Codebase Memory failure followed by automatic native-search fallback;
- Orca worker launch in disposable worktrees;
- automatic candidate verification and promotion on an ordinary coding task;
- Agent-Reach `doctor` parsing and mocked channel execution;
- Agent-Reach backend failure followed by automatic fallback;
- Agency Agents discover-to-active automatic qualification fixture;
- OpenMontage job lifecycle with a mocked renderer;
- benchmark runner comparing fixture results and reversible Graft promotion.

### End-to-End Tests

A representative ordinary coding task must demonstrate:

1. Hermes queries Codebase Memory;
2. the router selects a worker;
3. Orca executes the worker in an isolated worktree;
4. tests run;
5. post-change impact analysis runs;
6. verifier accepts/rejects the candidate;
7. evidence is complete;
8. verified promotion occurs without human approval when no explicit high-consequence category applies.

A degraded-context coding test must demonstrate that loss of Codebase Memory triggers automatic fallback rather than a blanket stop.

A representative research task must demonstrate Agent-Reach channel selection, authenticated channel use when configured, health evidence, backend fallback, normalized result ingestion, and secret-free logs without per-use approval.

A representative Revenue OS job must demonstrate autonomous research-to-render orchestration with only the separately classified high-consequence external action, if any, invoking the existing approval mechanism.

## CI Requirements

CI includes:

- unit test suite;
- integration fixtures that do not require real credentials;
- secret scan;
- dependency/provenance checks where supported;
- configuration/schema validation;
- no-network or mocked-network test coverage for core orchestration;
- benchmark harness smoke test;
- autonomy regression tests proving ordinary operations do not gain new human-approval gates.

Credentialed live-channel tests are optional/manual and must not be required for pull-request CI.

## Rollout Order

1. Shared capability/evidence/autonomy contracts.
2. Codebase Memory MCP adapter and autonomous fallback path.
3. Orca isolated-worktree executor beneath the existing router with automatic candidate promotion.
4. Agent-Reach unrestricted adapter with automatic redaction and backend fallback.
5. Agency Agents curated automatic qualification pipeline.
6. OpenMontage Revenue OS adapter.
7. Graft benchmark and reversible auto-promotion harness.
8. Cross-component end-to-end autonomy verification and release documentation.

## Acceptance Criteria

The architecture is complete when all of the following are true:

- ordinary Hermes operations run autonomously by default;
- no component introduces a blanket human-approval gate for hardening, health, provenance, unfamiliar providers, or authenticated access;
- Codebase Memory is the primary structural code-intelligence provider with automatic fallback;
- Hermes coding tasks query graph context before edit when available without blocking on a missing preferred provider;
- Orca-compatible workers execute in isolated worktrees without replacing Hermes routing;
- ordinary verified candidate changes can be promoted automatically;
- Agent-Reach exposes all supported channels, may use configured authenticated paths, and records health evidence without leaking credentials;
- Agency Agents candidates can be automatically normalized, scored, qualified, and activated;
- OpenMontage is callable autonomously through Revenue OS while any separately classified high-consequence external action remains governed by existing policy;
- Graft can be benchmarked and reversibly promoted through evidence-backed automatic policy;
- a normalized evidence envelope exists for every capability invocation;
- CI verifies the core paths without requiring real third-party credentials;
- end-to-end tests prove retry/fallback-before-block, protected-branch integrity, test-before-promotion, proof-before-success, and autonomy preservation.

## Explicit Non-Goals

- Replacing the existing Hermes model router.
- Making Orca the global orchestrator.
- Making Agent-Reach a credential store.
- Disabling authenticated Agent-Reach channels merely because they use session-based authentication.
- Requiring human review for every imported Agency Agents definition.
- Making OpenMontage part of the Hermes core runtime.
- Forcing Graft to remain benchmark-only after it satisfies configured promotion criteria.
- Allowing third-party content, agents, or tools to rewrite Hermes governance.
- Turning hardening, provenance, redaction, health checks, test gates, or evidence collection into routine human-interruption mechanisms.