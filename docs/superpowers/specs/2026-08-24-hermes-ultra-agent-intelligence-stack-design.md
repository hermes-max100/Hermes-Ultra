# Hermes Ultra Agent Intelligence Stack — Design

**Date:** 2026-08-24

**Status:** Approved architecture

## Objective

Integrate six upstream capability families into Hermes Ultra without replacing Hermes' existing orchestration, model-routing, governance, evidence, or proof-before-success layers. The resulting system adds persistent code intelligence, multi-agent worktree execution, unrestricted Agent-Reach internet intelligence, curated external agent ingestion, Revenue OS media production, and a controlled benchmark lane for Graft.

## Architectural Principles

1. **Hermes remains the brain.** Upstream projects are subordinate capability providers. None may replace Hermes orchestration, model routing, governance, approvals, evidence, or runtime policy.
2. **Existing model routing is authoritative.** Orca or any worker manager receives already-selected providers/workers from Hermes. It does not choose the global routing policy.
3. **Capabilities are replaceable adapters.** Hermes talks to stable internal interfaces, not directly to third-party implementation details.
4. **Evidence before success.** Every material action produces machine-readable evidence: inputs, selected capability, execution result, test result, health state, provenance, and failure class.
5. **Failure isolation.** A failed optional upstream capability must degrade its own lane rather than destabilize the Hermes core.
6. **No duplicated source of truth.** Codebase Memory is the primary structural code graph. Graft remains benchmark-only until explicitly promoted by evidence.
7. **Unrestricted Agent-Reach means full supported channel availability, not unrestricted secret handling.** All documented channels may be enabled. Authentication remains local/upstream; credentials, cookies, session values, and tokens must never be committed, logged, or copied into evidence bundles.
8. **Promotion requires reproducible tests.** No upstream component is designated production-default solely from marketing claims or external benchmarks.

## Top-Level Architecture

```text
HERMES ULTRA
│
├── Core Orchestrator / Policy / Evidence / Router
│
├── Code Intelligence Plane
│   ├── Codebase Memory MCP              [primary]
│   └── Graft Benchmark Harness          [non-production]
│
├── Coding Swarm Execution Plane
│   ├── Hermes task decomposition
│   ├── existing subscription/model router
│   ├── isolated Git worktrees
│   ├── Orca adapter / worker fleet
│   └── verifier + winning-patch promotion
│
├── Internet Intelligence Plane
│   └── Agent-Reach adapter              [all supported channels]
│
├── Agent Library Plane
│   ├── existing Hermes agents/skills
│   └── Agency Agents ingestion + dedupe + quarantine
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
    └── promotion decisions
```

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

### Required Pre-Edit Flow

Before a coding worker edits code:

1. identify the subsystem;
2. query the structural graph;
3. identify callers and dependencies;
4. identify likely impacted tests;
5. record a change-intent evidence object;
6. create or assign an isolated worktree;
7. allow the worker to edit;
8. execute tests;
9. rerun impact analysis against the changed set;
10. record proof-before-success evidence.

### Failure Behavior

If Codebase Memory is unavailable, Hermes may fall back to repository-native search for non-critical work, but must mark the run `degraded_context=true`. For high-risk changes, the policy layer may require a healthy structural graph before proceeding.

## Component 2 — Orca Worktree Fleet

### Purpose

Provide isolated parallel execution for coding workers such as Hermes Agent, Codex, Claude Code, Gemini, Kimi, Kiro, or future providers selected by the existing Hermes router.

### Boundary

Orca is an execution substrate, not a routing authority.

Hermes owns:

- task decomposition;
- provider/model selection;
- subscription/API lane selection;
- governance;
- concurrency limits;
- worktree lifecycle policy;
- verifier selection;
- patch acceptance and promotion.

The Orca adapter owns:

- spawning assigned workers;
- mapping workers to isolated worktrees;
- reporting stdout/stderr/exit state;
- reporting worker completion;
- cancelling failed or superseded workers;
- returning candidate patches/results to Hermes.

### Candidate Promotion

No worker writes directly to the protected branch. Each candidate remains isolated until Hermes:

1. verifies tests;
2. checks policy;
3. compares candidate evidence;
4. selects a winner or synthesizes a new candidate;
5. promotes only the verified change.

## Component 3 — Agent-Reach Unrestricted Internet Intelligence

### Purpose

Expose every supported Agent-Reach channel through Hermes while retaining Agent-Reach's own backend selection and health diagnostics.

### Channel Policy

Hermes must support the upstream `channels=all` install/runtime mode and must not maintain a Hermes-side content-source allowlist that artificially disables supported Agent-Reach channels.

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

Authentication is not stored in Hermes source control. Secrets and browser-session material stay in the upstream/local configuration or process environment. Hermes may invoke authenticated adapters when configured, but evidence/logging must redact credential-like values.

### Health and Evidence

`agent-reach doctor` or the current upstream equivalent is captured as structured health evidence. A channel failure degrades only that channel or route unless the requested task requires it exclusively.

## Component 4 — Agency Agents Curated Ingestion

### Purpose

Increase the available specialist agent/skill catalog without flooding runtime selection with duplicates or low-quality overlapping prompts.

### Ingestion States

Every imported definition moves through:

```text
DISCOVERED -> QUARANTINED -> NORMALIZED -> SCORED -> APPROVED -> ACTIVE
                                      \-> REJECTED
```

### Dedupe and Scoring

The ingestion layer evaluates:

- semantic overlap with existing Hermes agents/skills;
- declared capabilities;
- required tools;
- privilege/risk level;
- prompt injection or unsafe instruction patterns;
- provenance and upstream revision;
- measurable value versus existing agents.

A candidate cannot become `ACTIVE` merely because it exists upstream.

### Runtime Rule

Only `ACTIVE` definitions are eligible for orchestration. Quarantined or rejected definitions remain inspectable but cannot execute.

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

The adapter may coordinate stages such as:

```text
research -> script -> asset plan -> asset acquisition/generation
-> narration -> subtitles -> render -> QA -> evidence bundle
```

### Publication Boundary

Rendering and QA may be autonomous. External publication/posting remains governed by the existing Hermes external-communication policy and any applicable approval category.

## Component 6 — Graft Benchmark Harness

### Purpose

Test whether Graft materially improves Hermes performance relative to Codebase Memory or baseline repository-native context retrieval.

### Non-Production Status

Graft is not part of the mandatory runtime context path at initial integration.

### Benchmark Design

Use the same fixed Hermes repository tasks across:

- baseline repository-native search;
- Codebase Memory MCP;
- Graft;
- optional combined experimental mode only if required to test complementarity.

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

Graft may be promoted only through an explicit configuration change after reproducible Hermes-local evidence demonstrates a material advantage or a clearly complementary role. No automatic promotion is allowed.

## Shared Evidence Schema

Each capability invocation should emit a normalized evidence envelope:

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
  "redactions_applied": true
}
```

Secrets, cookies, bearer tokens, authorization headers, passwords, session IDs, and provider credentials must be redacted before evidence persistence.

## Configuration Model

Hermes configuration must use capability-scoped settings rather than embedding third-party configuration globally. Example logical shape:

```yaml
capabilities:
  code_intelligence:
    primary: codebase_memory
    fallback: native_repo_search
    graft:
      mode: benchmark_only

  coding_swarm:
    executor: orca
    router: existing_hermes_router
    worktree_isolation: required

  internet_intelligence:
    provider: agent_reach
    channels: all
    preserve_upstream_fallbacks: true

  agent_library:
    agency_agents:
      ingestion: curated
      quarantine_required: true

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

The core must preserve the original stderr/error payload in a redacted artifact while exposing the normalized class to orchestration.

## Security and Governance

- No upstream package receives implicit authority over Hermes policy.
- No direct write to protected branches from workers.
- No secrets in Git, CI logs, evidence bundles, prompts, or telemetry.
- Third-party agent definitions are untrusted until approved through ingestion.
- Internet-source content is untrusted data and cannot modify runtime policy merely by containing instructions.
- External publishing remains subject to existing external-communication governance.
- High-consequence operations remain governed by existing Hermes approval categories.

## Testing Strategy

### Unit Tests

- adapter command construction;
- environment propagation;
- secret redaction;
- health result normalization;
- failure classification;
- capability discovery;
- Agency Agents deduplication/scoring state transitions;
- Graft promotion guard;
- evidence schema validation.

### Integration Tests

- Codebase Memory graph query against a fixture repository;
- Orca worker launch in disposable worktrees;
- Agent-Reach `doctor` parsing and mocked channel execution;
- Agency Agents quarantine-to-active promotion fixture;
- OpenMontage job lifecycle with a mocked renderer;
- benchmark runner comparing fixture results.

### End-to-End Tests

A representative coding task must demonstrate:

1. Hermes queries Codebase Memory;
2. the router selects a worker;
3. Orca executes the worker in an isolated worktree;
4. tests run;
5. post-change impact analysis runs;
6. verifier accepts/rejects the candidate;
7. evidence is complete;
8. protected branch remains untouched until promotion.

A representative research task must demonstrate Agent-Reach channel selection, health evidence, normalized result ingestion, and secret-free logs.

A representative Revenue OS job must demonstrate research-to-render orchestration with publication remaining separately governed.

## CI Requirements

CI must include:

- unit test suite;
- integration fixtures that do not require real credentials;
- secret scan;
- dependency/provenance checks where supported;
- configuration/schema validation;
- no-network or mocked-network test coverage for core orchestration;
- benchmark harness smoke test without promoting Graft.

Credentialed live-channel tests are optional/manual and must not be required for pull-request CI.

## Rollout Order

1. Shared capability/evidence contracts.
2. Codebase Memory MCP adapter and pre-edit context flow.
3. Orca isolated-worktree executor integrated beneath the existing router.
4. Agent-Reach unrestricted adapter hardened against secret leakage.
5. Agency Agents curated ingestion pipeline.
6. OpenMontage Revenue OS adapter.
7. Graft benchmark harness.
8. Cross-component end-to-end verification and release documentation.

## Acceptance Criteria

The architecture is complete when all of the following are true:

- Codebase Memory is the primary structural code-intelligence provider.
- Hermes coding tasks can require graph context before edit.
- Orca-compatible workers execute in isolated worktrees without replacing Hermes routing.
- Agent-Reach exposes all supported channels and records health evidence without leaking credentials.
- Agency Agents candidates cannot execute before quarantine, normalization, scoring, and approval.
- OpenMontage is callable through Revenue OS while external publication remains separately governed.
- Graft remains benchmark-only until an explicit evidence-backed promotion.
- A normalized evidence envelope exists for every capability invocation.
- CI verifies the core paths without requiring real third-party credentials.
- End-to-end tests prove protected-branch isolation, test-before-promotion, and proof-before-success.

## Explicit Non-Goals

- Replacing the existing Hermes model router.
- Making Orca the global orchestrator.
- Making Agent-Reach a credential store.
- Activating the entire Agency Agents catalog automatically.
- Making OpenMontage part of the Hermes core runtime.
- Promoting Graft without Hermes-local benchmark evidence.
- Allowing third-party content, agents, or tools to rewrite Hermes governance.