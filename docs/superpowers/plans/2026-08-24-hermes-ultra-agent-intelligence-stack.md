# Hermes Ultra Agent Intelligence Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved autonomy-first Hermes Ultra intelligence stack with Codebase Memory, Orca-compatible isolated workers, unrestricted Agent-Reach, automatic Agency Agents qualification, OpenMontage Revenue OS integration, and evidence-backed Graft benchmarking/promotion.

**Architecture:** Hermes remains the orchestration and routing authority. Every upstream capability sits behind a small Python adapter and emits the same evidence/failure contract. Autonomy is the default: ordinary work retries, falls back, verifies, and promotes automatically; only an existing explicit high-consequence category can set `human_approval_required=true`.

**Tech Stack:** Python 3.10+, standard library, pytest 8+, subprocess-based adapters, dataclasses/protocols, JSON evidence envelopes, Git worktrees, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-24-hermes-ultra-agent-intelligence-stack-design.md`

## Global Constraints

- Existing Hermes model routing remains authoritative.
- Ordinary operations require no human approval.
- Hardening mode is automatic and non-blocking for ordinary work.
- Retry/fallback must occur before a recoverable failure becomes blocking.
- Agent-Reach exposes all supported channels and configured authenticated paths without per-use approval.
- Secrets, cookies, bearer tokens, authorization headers, passwords, session IDs, and provider credentials never persist in evidence.
- Worktree isolation is required for coding workers, but promotion of an ordinary verified change is automatic.
- Graft promotion must be evidence-backed and reversible.
- No third-party component may rewrite Hermes policy or introduce a blanket approval gate.

---

### Task 1: Shared autonomy, failure, and evidence contracts

**Files:**
- Create: `src/hermes_ultra/contracts.py`
- Create: `src/hermes_ultra/evidence.py`
- Create: `src/hermes_ultra/autonomy.py`
- Test: `tests/test_contracts.py`
- Test: `tests/test_evidence.py`
- Test: `tests/test_autonomy.py`

**Interfaces:**
- Produces: `FailureClass`, `CapabilityResult[T]`, `EvidenceEnvelope`, `EvidenceRecorder`, `ApprovalRegistry`, `AutonomyDecision`.
- Consumers: all later adapters and orchestrator tasks.

- [ ] **Step 1: Write failing contract tests**

```python
from hermes_ultra.contracts import FailureClass, CapabilityResult


def test_success_result_is_not_blocking():
    result = CapabilityResult.success({"ok": True})
    assert result.ok is True
    assert result.blocking is False
    assert result.failure_class is None


def test_recoverable_failure_is_not_blocking_when_fallback_exists():
    result = CapabilityResult.failure(
        FailureClass.UPSTREAM_UNAVAILABLE,
        "primary down",
        recoverable=True,
    )
    assert result.blocking is False
```

- [ ] **Step 2: Run contract tests and verify import failure**

Run: `pytest tests/test_contracts.py -v`
Expected: FAIL because `hermes_ultra.contracts` does not exist.

- [ ] **Step 3: Implement shared result/failure types**

Create `FailureClass` values matching the spec and a generic immutable `CapabilityResult` with `success()` and `failure()` constructors. `blocking` must be true only for non-recoverable failure after fallbacks are exhausted or an explicit policy block.

- [ ] **Step 4: Write failing autonomy tests**

```python
from hermes_ultra.autonomy import ApprovalRegistry


def test_ordinary_action_never_requires_approval():
    registry = ApprovalRegistry({"production_deploy", "external_communication"})
    decision = registry.evaluate("code_edit")
    assert decision.human_approval_required is False
    assert decision.category is None


def test_only_registered_high_consequence_category_can_require_approval():
    registry = ApprovalRegistry({"production_deploy"})
    decision = registry.evaluate("production_deploy")
    assert decision.human_approval_required is True
    assert decision.category == "production_deploy"
```

- [ ] **Step 5: Implement `ApprovalRegistry` and immutable `AutonomyDecision`**

Do not infer approval from risk scores, authentication, unfamiliar providers, health state, or hardening failures. `evaluate(action_category)` may return approval-required only when the exact category is registered.

- [ ] **Step 6: Write failing evidence redaction tests**

```python
from hermes_ultra.evidence import EvidenceEnvelope, redact_secrets


def test_redaction_removes_known_secret_shapes():
    data = {
        "Authorization": "Bearer abc123",
        "cookie": "auth_token=secret; ct0=xyz",
        "message": "safe",
    }
    redacted = redact_secrets(data)
    assert "abc123" not in repr(redacted)
    assert "secret" not in repr(redacted)
    assert redacted["message"] == "safe"


def test_approval_defaults_false():
    envelope = EvidenceEnvelope.new("task-1", "agent-reach")
    assert envelope.human_approval_required is False
```

- [ ] **Step 7: Implement recursive evidence redaction and envelope serialization**

Redact keys matching authorization/token/cookie/password/session/secret patterns and redact bearer/token-like values before JSON persistence. Preserve non-secret diagnostic text.

- [ ] **Step 8: Run Task 1 tests**

Run: `pytest tests/test_contracts.py tests/test_autonomy.py tests/test_evidence.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/hermes_ultra/contracts.py src/hermes_ultra/evidence.py src/hermes_ultra/autonomy.py tests/test_contracts.py tests/test_autonomy.py tests/test_evidence.py
git commit -m "feat: add autonomy and evidence contracts"
```

### Task 2: Codebase Memory primary code-intelligence adapter with autonomous fallback

**Files:**
- Create: `src/hermes_ultra/code_intelligence.py`
- Test: `tests/test_code_intelligence.py`

**Interfaces:**
- Consumes: `CapabilityResult`, `FailureClass`, `EvidenceEnvelope`.
- Produces: `CodeIntelligenceProvider`, `CodebaseMemoryAdapter`, `NativeRepoSearchAdapter`, `CodeIntelligenceRouter`, `ImpactReport`.

- [ ] **Step 1: Write failing fallback test**

```python
def test_primary_failure_uses_native_fallback(fake_primary, fake_native):
    router = CodeIntelligenceRouter(primary=fake_primary, fallback=fake_native)
    result = router.impact_analysis(["src/app.py"])
    assert result.ok
    assert result.value.provider == "native-repo-search"
    assert result.value.degraded_context is True
```

- [ ] **Step 2: Run and verify failure**

Run: `pytest tests/test_code_intelligence.py -v`
Expected: FAIL because module/classes do not exist.

- [ ] **Step 3: Implement provider protocol and normalized `ImpactReport`**

The protocol exposes `index_repository`, `lookup_symbol`, `find_callers`, `find_dependencies`, `find_routes`, `impact_analysis`, and `health`. Keep subprocess/MCP details inside adapters.

- [ ] **Step 4: Implement Codebase Memory command adapter**

Allow command template injection for testing. Normalize missing binary, timeout, nonzero exit, malformed output, and health failure into `CapabilityResult` rather than raising unclassified exceptions.

- [ ] **Step 5: Implement native repository-search fallback**

Use `git grep`/`git ls-files` through an injected runner; do not require network or third-party packages.

- [ ] **Step 6: Implement `CodeIntelligenceRouter` retry/fallback semantics**

Primary failure must not become blocking when native fallback succeeds. Set `degraded_context=true` and preserve the primary failure in redacted evidence metadata.

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_code_intelligence.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/hermes_ultra/code_intelligence.py tests/test_code_intelligence.py
git commit -m "feat: add code intelligence with autonomous fallback"
```

### Task 3: Orca-compatible isolated worktree executor and automatic verifier promotion

**Files:**
- Create: `src/hermes_ultra/swarm.py`
- Test: `tests/test_swarm.py`

**Interfaces:**
- Consumes: existing Hermes-selected worker command/model identity; `CapabilityResult`, `ApprovalRegistry`.
- Produces: `WorkerAssignment`, `WorkerOutcome`, `WorktreeExecutor`, `CandidateVerifier`.

- [ ] **Step 1: Write failing worktree isolation test**

Create a temporary Git repository fixture. Assert a worker assignment creates a distinct worktree path and never runs with the protected branch working directory.

- [ ] **Step 2: Write failing ordinary auto-promotion test**

```python
def test_verified_ordinary_candidate_promotes_without_human_approval(verifier, candidate):
    result = verifier.evaluate(candidate, action_category="code_edit")
    assert result.approved_for_promotion is True
    assert result.human_approval_required is False
```

- [ ] **Step 3: Implement `WorkerAssignment` and worktree lifecycle**

Use `git worktree add --detach` or an isolated branch derived from a supplied base SHA. Worker/provider selection is input; `WorktreeExecutor` must never select a model.

- [ ] **Step 4: Implement Orca-compatible runner boundary**

Support an injected command builder so Hermes can invoke Orca when available or direct CLI workers through the same assignment interface. Capture exit state/stdout/stderr as `WorkerOutcome`.

- [ ] **Step 5: Implement automatic verifier**

Require configured tests to pass and explicit policy checks to pass. Ordinary code changes are promotable without human approval. Only `ApprovalRegistry.evaluate()` may introduce approval-required state.

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_swarm.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hermes_ultra/swarm.py tests/test_swarm.py
git commit -m "feat: add autonomous isolated coding swarm executor"
```

### Task 4: Upgrade Agent-Reach integration to autonomy-first evidence and fallback behavior

**Files:**
- Modify: `src/hermes_ultra/agent_reach.py`
- Modify: `tests/test_agent_reach.py`

**Interfaces:**
- Consumes: `CapabilityResult`, `FailureClass`, evidence redaction.
- Produces: current public `AgentReachAdapter` methods plus normalized `execute_with_fallback()` and secret-safe status/evidence.

- [ ] **Step 1: Add failing tests for authenticated autonomy and secret-free errors**

Assert configured environment variables are passed to subprocess but are absent from raised/recorded diagnostics. Assert no per-use approval field exists in adapter execution.

- [ ] **Step 2: Add failing fallback test**

Provide two injected backend commands: first returns nonzero, second succeeds. Assert `execute_with_fallback()` returns success and records the first route as degraded evidence rather than stopping.

- [ ] **Step 3: Refactor subprocess results into shared capability result types**

Maintain backward-compatible `AgentReachResult` where useful, but all orchestration-facing methods return normalized failure classes.

- [ ] **Step 4: Redact status and error material**

Run stdout/stderr and structured status through evidence redaction before persistence. Do not remove authenticated capability or environment propagation.

- [ ] **Step 5: Run existing and new tests**

Run: `pytest tests/test_agent_reach.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hermes_ultra/agent_reach.py tests/test_agent_reach.py
git commit -m "feat: make Agent Reach autonomy-first and secret-safe"
```

### Task 5: Agency Agents automatic qualification and activation

**Files:**
- Create: `src/hermes_ultra/agency_agents.py`
- Test: `tests/test_agency_agents.py`

**Interfaces:**
- Produces: `AgentDefinition`, `AgentState`, `QualificationScore`, `AgencyAgentIngestor`.

- [ ] **Step 1: Write failing lifecycle tests**

Assert a low-overlap, valid agent progresses `DISCOVERED -> NORMALIZED -> SCORED -> QUALIFIED -> ACTIVE` without human approval. Assert a malformed/conflicting definition ends `REJECTED` with evidence.

- [ ] **Step 2: Implement deterministic normalization**

Normalize names, capability lists, tool requirements, source revision, and prompt text. Hash normalized definitions for deduplication.

- [ ] **Step 3: Implement scoring**

Use explicit weighted fields: uniqueness, capability completeness, provenance presence, tool declaration quality, conflict flags, and privilege category. A privilege category does not block activation; it limits use of that capability through the existing approval registry when exercised.

- [ ] **Step 4: Implement automatic activation threshold and rescore**

Keep thresholds in constructor/config, not hard-coded throughout orchestration. Support rescoring after upstream revision.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_agency_agents.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hermes_ultra/agency_agents.py tests/test_agency_agents.py
git commit -m "feat: add automatic agency agent qualification"
```

### Task 6: OpenMontage Revenue OS autonomous media pipeline

**Files:**
- Create: `src/hermes_ultra/openmontage.py`
- Test: `tests/test_openmontage.py`

**Interfaces:**
- Produces: `MediaJob`, `MediaStageResult`, `OpenMontageAdapter`, `MediaPipelineResult`.

- [ ] **Step 1: Write failing lifecycle test**

Use an injected renderer/runner and assert `research -> script -> assets -> narration -> subtitles -> render -> qa` executes without human approval for a staging-only job.

- [ ] **Step 2: Write external-action boundary test**

Assert `publication_intent=True` does not stop research/rendering. Only the final `publish` action is evaluated against `ApprovalRegistry` when publication is requested.

- [ ] **Step 3: Implement job/stage models and adapter**

Keep OpenMontage-specific CLI payload construction inside the adapter. Each stage emits evidence and a normalized result.

- [ ] **Step 4: Implement continuation semantics**

Recoverable stage failures retry or use configured alternate stage backend. Permanent render failure returns a failed media job without altering unrelated Hermes lanes.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_openmontage.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hermes_ultra/openmontage.py tests/test_openmontage.py
git commit -m "feat: add autonomous Revenue OS media pipeline"
```

### Task 7: Graft benchmark harness with reversible automatic promotion

**Files:**
- Create: `src/hermes_ultra/benchmarks.py`
- Test: `tests/test_benchmarks.py`

**Interfaces:**
- Produces: `BenchmarkCase`, `BenchmarkMetrics`, `BenchmarkReport`, `PromotionPolicy`, `ProviderRegistry`.

- [ ] **Step 1: Write failing promotion tests**

Assert Graft is not promoted when success rate regresses or evidence is incomplete. Assert it is promoted automatically when all configured thresholds pass. Assert rollback restores the previous provider.

- [ ] **Step 2: Implement benchmark metrics model**

Represent latency, tool calls, tokens when observable, success, tests, wrong-file edits, regressions, and evidence completeness.

- [ ] **Step 3: Implement reproducible comparison runner**

Each case runs the same task against baseline, Codebase Memory, and Graft adapters with a supplied runner. Tests use deterministic fakes.

- [ ] **Step 4: Implement `PromotionPolicy`**

Thresholds are explicit configuration. Promotion writes a reversible provider-registry change and evidence record. No manual confirmation is introduced for ordinary provider promotion.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_benchmarks.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hermes_ultra/benchmarks.py tests/test_benchmarks.py
git commit -m "feat: add evidence-backed Graft promotion harness"
```

### Task 8: Cross-component autonomous orchestrator and end-to-end tests

**Files:**
- Create: `src/hermes_ultra/orchestrator.py`
- Modify: `src/hermes_ultra/__init__.py`
- Create: `tests/test_orchestrator_e2e.py`

**Interfaces:**
- Consumes all previous adapters/contracts.
- Produces: `HermesUltraOrchestrator.run_coding_task()`, `run_research_task()`, `run_media_job()`.

- [ ] **Step 1: Write failing coding E2E test**

Fixture flow: Codebase Memory succeeds -> router supplies worker identity -> isolated worker modifies fixture -> tests pass -> post-impact analysis passes -> verifier promotes candidate -> evidence complete -> no human approval required.

- [ ] **Step 2: Write degraded-context E2E test**

Force Codebase Memory failure; native search succeeds; coding task continues and evidence contains `degraded_context=true`.

- [ ] **Step 3: Write Agent-Reach fallback E2E test**

First research backend fails; second succeeds. Assert final result succeeds, no credential value appears in serialized evidence, and no approval is requested.

- [ ] **Step 4: Implement thin orchestrator**

The orchestrator composes existing interfaces; do not duplicate adapter logic. All action-category decisions go through `ApprovalRegistry`.

- [ ] **Step 5: Run E2E tests**

Run: `pytest tests/test_orchestrator_e2e.py -v`
Expected: PASS.

- [ ] **Step 6: Run full suite**

Run: `pytest -q`
Expected: PASS with zero failures.

- [ ] **Step 7: Commit**

```bash
git add src/hermes_ultra/orchestrator.py src/hermes_ultra/__init__.py tests/test_orchestrator_e2e.py
git commit -m "feat: integrate autonomous Hermes intelligence stack"
```

### Task 9: CI autonomy regression gates and release documentation

**Files:**
- Modify: `.github/workflows/test.yml`
- Modify: `README.md`
- Create: `docs/architecture/autonomy-contract.md`

**Interfaces:**
- CI consumes the complete pytest suite.
- Documentation exposes operator-visible autonomy guarantees and explicit high-consequence boundary semantics.

- [ ] **Step 1: Add CI commands**

CI installs `.[test]`, runs `pytest -q`, scans tracked files for obvious credential patterns, and executes a focused autonomy regression command:

```bash
pytest tests/test_autonomy.py tests/test_orchestrator_e2e.py -q
```

- [ ] **Step 2: Document runtime behavior**

README must state: Hermes remains router/orchestrator; Agent-Reach is all-channels; Codebase Memory has automatic fallback; worktrees isolate workers; normal verified changes auto-promote; imported agents auto-qualify; Graft can auto-promote reversibly; only registered high-consequence categories trigger human approval.

- [ ] **Step 3: Add autonomy contract document**

Document default-autonomous semantics, retry/fallback-before-block, automatic hardening controls, and the rule that new integrations cannot invent approval categories.

- [ ] **Step 4: Run full verification**

Run:
```bash
python -m compileall -q src
pytest -q
git grep -nEi '(authorization: bearer|auth_token=|password[=:][^$<{])' -- . ':!docs/superpowers/specs/*' ':!docs/superpowers/plans/*' || true
```
Expected: compile succeeds; tests pass; secret scan returns no real credentials.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/test.yml README.md docs/architecture/autonomy-contract.md
git commit -m "ci: enforce Hermes autonomy contract"
```

## Final Verification

- [ ] `python -m compileall -q src` passes.
- [ ] `pytest -q` passes.
- [ ] Agent-Reach existing tests remain green.
- [ ] At least one test proves primary code-intelligence failure falls back automatically.
- [ ] At least one test proves authenticated Agent-Reach execution does not require per-use approval.
- [ ] At least one test proves ordinary verified code promotion does not require human approval.
- [ ] At least one test proves only an exact registered high-consequence category can set `human_approval_required=true`.
- [ ] At least one test proves persisted evidence contains no injected secret value.
- [ ] At least one test proves Graft promotion is reversible.
- [ ] CI workflow contains the full and autonomy-focused test commands.
