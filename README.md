# Hermes-Ultra

Hermes Ultra is an autonomy-first integration layer for code intelligence, coding swarms, internet intelligence, specialist-agent ingestion, Revenue OS media production, and evidence-backed provider benchmarking.

## Autonomy contract

**Ordinary work is autonomous by default.** Hardening controls run automatically around execution and must not become blanket human-approval gates.

Human approval may be required only when the action itself matches an explicit high-consequence category already registered in Hermes policy. Authentication, provider unfamiliarity, health failures, provenance checks, third-party tools, and retrieved internet content do not create new approval categories by themselves.

See `docs/architecture/autonomy-contract.md`.

## Architecture

```text
HERMES ULTRA
│
├── Existing Hermes Orchestrator / Model Router
│
├── Code Intelligence
│   ├── Codebase Memory                 [primary]
│   └── Native repository search        [automatic fallback]
│
├── Coding Swarm
│   ├── existing Hermes worker selection
│   ├── isolated Git worktrees
│   ├── Orca-compatible execution boundary
│   └── automatic verifier / promotion
│
├── Internet Intelligence
│   └── Agent-Reach                     [all supported channels]
│
├── Agent Library
│   └── Agency Agents automatic qualification
│
├── Revenue OS
│   └── OpenMontage autonomous media pipeline
│
├── Experimental Context
│   └── Graft benchmark + reversible promotion
│
└── Evidence / Autonomy Contracts
```

Hermes remains the orchestration and routing authority. None of the integrated upstream capabilities may replace the existing model router or invent new approval policy.

## Agent-Reach — unrestricted channels

Hermes Ultra treats Agent Reach as a first-class internet-intelligence provider with every currently documented optional channel eligible:

- OpenCLI
- Twitter/X
- XiaoYuZhou
- Xueqiu
- Xiaohongshu
- Reddit
- Facebook
- Instagram
- Bilibili
- LinkedIn

Zero-config Agent-Reach capabilities such as web reading, YouTube, RSS, GitHub, semantic web search, V2EX, and basic Bilibili remain available as well.

Authenticated channels remain usable when owner-controlled credentials/session state are configured. Hermes passes required authentication to the upstream process but automatically redacts secret material from persisted diagnostics/evidence. Authenticated access is **not** converted into a per-use approval gate.

### Install / inspect

```bash
pipx install https://github.com/Panniantong/agent-reach/archive/main.zip
agent-reach install --env=auto --channels=all --dry-run
```

For an already-authorized host-management context:

```bash
agent-reach install --env=auto --system --channels=all
agent-reach doctor
```

### Python

```python
from hermes_ultra import AgentReachAdapter

reach = AgentReachAdapter()
reach.install_all(dry_run=True)
print(reach.status_json())

result = reach.execute_with_fallback([
    ("twitter", ("search", "Hermes agents")),
    ("opencli", ("twitter", "search", "Hermes agents")),
])
```

A failed preferred backend is evidence, not a human-approval event. Hermes tries the next configured route.

## Code intelligence

`CodeIntelligenceRouter` uses Codebase Memory as the preferred structural context provider and `NativeRepoSearchAdapter` as an autonomous fallback. Loss of the preferred graph produces `degraded_context=true`; it does not stop ordinary work while a viable fallback exists.

```python
from hermes_ultra import (
    CodeIntelligenceRouter,
    CodebaseMemoryAdapter,
    NativeRepoSearchAdapter,
)

router = CodeIntelligenceRouter(
    primary=CodebaseMemoryAdapter(repo_path="."),
    fallback=NativeRepoSearchAdapter(repo_path="."),
)
```

## Coding swarm / Orca boundary

`WorktreeExecutor` receives an already-selected worker command from the existing Hermes router. It does **not** choose a provider or model. Workers run in isolated Git worktrees.

`CandidateVerifier` automatically promotes an ordinary candidate when configured tests and policy checks pass. Only `ApprovalRegistry` can introduce a human-approval requirement, and only through an exact pre-registered high-consequence category.

## Agency Agents

`AgencyAgentIngestor` automatically:

1. normalizes definitions;
2. deduplicates names;
3. scores capability completeness, provenance, tools, uniqueness, and instruction integrity;
4. activates qualified candidates.

A high-consequence capability label does not prevent an otherwise qualified agent from becoming active. The approval boundary is evaluated when that specific action is exercised.

## Revenue OS / OpenMontage

`OpenMontageAdapter` runs media production stages autonomously:

```text
research -> script -> assets -> narration -> subtitles -> render -> qa
```

A potential external-publication approval boundary is checked only after the render/QA pipeline completes. It does not block the production workflow itself.

## Graft benchmark and promotion

`PromotionPolicy` compares Graft against Codebase Memory on reproducible Hermes-local metrics. Graft can promote automatically when configured quality and efficiency thresholds pass. `ProviderRegistry.rollback()` restores the previous provider.

Promotion is evidence-backed and reversible rather than permanently disabled by a hard-coded safety rule.

## Shared evidence

Every orchestration lane uses the same normalized result/evidence concepts:

- explicit failure classes;
- retry/fallback before blocking;
- automatic secret redaction;
- test and health evidence;
- `human_approval_required=false` by default;
- exact-category approval semantics.

## Tests

```bash
python -m pip install -e '.[test]'
python -m compileall -q src
pytest -q
```

CI also runs focused autonomy-regression tests. A change that adds a blanket approval default or turns hardening into a routine interruption should fail those tests.
