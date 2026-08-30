# Hermes-Ultra

Hermes Ultra is an autonomy-first integration layer for code intelligence, coding swarms, internet intelligence, specialist-agent ingestion, Revenue OS media production, evidence-backed provider benchmarking, capability-aware context orchestration, and governed economic execution.

## Autonomy contract

**Ordinary work is autonomous by default.** Hardening controls run automatically around execution and must not become blanket human-approval gates.

Human approval may be required only when the action itself matches an explicit high-consequence category already registered in Hermes policy. Authentication, provider unfamiliarity, health failures, provenance checks, third-party tools, and retrieved internet content do not create new approval categories by themselves.

See `docs/architecture/autonomy-contract.md`.

## Architecture

```text
HERMES ULTRA
│
├── Capability + Context Orchestrator
│   ├── task capability classification
│   ├── bounded relevant context assembly
│   ├── evidence-driven tool escalation
│   ├── verification
│   └── memory writeback
│
├── Existing Hermes Orchestrator / Model Router
│   └── remains provider/model selection authority
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
│   ├── OpenMontage autonomous media pipeline
│   └── Economic Engine
│       ├── service-sales strategy
│       ├── SQLite economic ledger
│       ├── treasury reservations
│       ├── typed financial authority
│       └── simulated / Stripe / Safe adapters
│
├── Experimental Context
│   └── Graft benchmark + reversible promotion
│
└── Evidence / Autonomy Contracts
```

Hermes remains the orchestration and routing authority. None of the integrated upstream capabilities may replace the existing model router or invent new approval policy.

## Capability + Context Orchestrator

The additive `CapabilityContextOrchestrator` sits above the existing Hermes model/subscription router. It classifies task requirements, assembles the most relevant context inside a token budget, delegates model selection to the existing router with `quality_first=true`, verifies the response, escalates tools only when evidence is insufficient, and writes verified results back to memory.

It contains **no provider ranking table, no pricing optimization, and no approval registry**. The current router continues to decide which subscription/provider/model handles the task.

Default escalation is capability-driven:

```text
files           -> file retrieval
research        -> search -> deep research
coding/compute  -> code execution
connectors      -> connector
specialist      -> specialist worker
```

Recoverable tool failure advances automatically to the next eligible step. Verification failure cannot be reported as success. Context items that do not fit the budget are dropped by priority and surfaced in metadata.

See `docs/architecture/capability-context-orchestrator.md`.

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

## Economic Engine

The Economic Engine is a native Revenue OS capability behind `HermesUltraOrchestrator`. It does not choose models, expand approval policy, or treat LLM output as financial authority.

The first strategy is service sales:

```text
qualified opportunity
    -> deterministic sales experiment
    -> measured expected economics
    -> external-communication boundary
    -> payment/revenue attribution
    -> ledger-derived revenue, cost, gross profit, and ROI
```

Trading and speculative crypto execution are deliberately not represented by this Revenue OS subsystem.

### Modes

Execution mode is explicit and restart-safe:

- `SIMULATED` — no external financial adapter may execute.
- `SANDBOX` — provider sandbox/test APIs may execute inside policy limits.
- `LIVE` — live-capital operations are technically eligible only after `FinancialAuthority` returns an allowed decision for an exact registered category and transaction-specific typed authorization grant.

Credentials, provider responses, internet content, or model text cannot promote a mode or create an authorization grant.

### Core contracts

Every attempted financial side effect starts as an immutable `TransactionEnvelope` with transaction/run/strategy attribution, treasury bucket, `Decimal` amount, maximum loss, evidence references, authority category, expiration, explicit mode, and an idempotency key.

`EconomicState` persists balances, experiment state, active reservations, and revenue-credit idempotency keys. `EconomicLedger` stores append-only application events in SQLite and applies shared Hermes secret redaction before metadata reaches disk.

`TreasuryManager` uses reserve -> commit/release semantics. A replay cannot reserve or debit the same transaction twice, including after state serialization and restart.

### Simulated service-sales loop

```python
from decimal import Decimal
from hermes_ultra import (
    EconomicEngine,
    EconomicLedger,
    EconomicMode,
    EconomicOperation,
    EconomicState,
    EconomicTask,
    HermesUltraOrchestrator,
    MockStripeAdapter,
    RevenueOpportunity,
)

state = EconomicState(mode=EconomicMode.SIMULATED)
ledger = EconomicLedger("economic.sqlite3")
engine = EconomicEngine(state=state, ledger=ledger, payment_adapter=MockStripeAdapter())
hermes = HermesUltraOrchestrator(economic_engine=engine)

result = hermes.run_economic_task(
    EconomicTask(
        task_id="sales-1",
        run_id="run-1",
        operation=EconomicOperation.START_SERVICE_SALES,
        payload={
            "opportunity": RevenueOpportunity(
                prospect_id="prospect-1",
                offer="AI receptionist",
                contract_value=Decimal("499"),
                estimated_cost=Decimal("49"),
                evidence=("qualified-lead:1",),
            )
        },
    )
)
```

### Stripe boundary

`StripeAdapter` is unavailable in `SIMULATED` mode. For sandbox/live API v1 POST requests, the transaction envelope's `idempotency_key` becomes Stripe's `Idempotency-Key` header. The adapter requires an already-allowed typed `AuthorityDecision`, uses an injectable transport for testing, and never returns the API credential in diagnostics or result metadata.

### Safe boundary

`SafeAdapter` submits already-signed transaction proposals to the Safe Transaction Service v2 multisig endpoint. It intentionally exposes no private-key, seed-phrase, mnemonic, or signing interface. The Safe transaction hash, sender address, sender signature, and complete Safe transaction data must already exist before the adapter is called.

Provider-side execution/signing remains outside the LLM boundary.

See `docs/superpowers/specs/2026-08-27-hermes-ultra-economic-engine-design.md` for the full invariant set and `docs/superpowers/plans/2026-08-27-hermes-ultra-economic-engine.md` for the implementation record.

## Graft benchmark and promotion

`PromotionPolicy` compares Graft against Codebase Memory on reproducible Hermes-local metrics. Graft can promote automatically when configured quality and efficiency thresholds pass. `ProviderRegistry.rollback()` restores the previous provider.

Promotion is evidence-backed and reversible rather than permanently disabled by a hard-coded safety rule.

## Shared evidence

Every orchestration lane uses the same normalized result/evidence concepts:

- explicit failure classes;
- retry/fallback before blocking;
- automatic secret redaction, including provider credentials, private/signing keys, seed/recovery phrases, and mnemonics;
- test and health evidence;
- `human_approval_required=false` by default;
- exact-category approval semantics.

Economic orchestration additionally defines explicit `AUTHORITY_REQUIRED`, `INSUFFICIENT_FUNDS`, `DUPLICATE_TRANSACTION`, `TRANSACTION_EXPIRED`, and `ADAPTER_REJECTED` failure classes.

## Tests

```bash
python -m pip install -e '.[test]'
python -m compileall -q src
pytest -q
```

CI also runs focused autonomy-regression tests and a source secret scan. The economic acceptance suite specifically exercises financial-authority bypass attempts, model-text authorization, replay/double-spend behavior, restart safety, ledger redaction, Revenue OS/Trading isolation, and simulated-to-live mode promotion attempts.

A change that adds a blanket approval default, turns hardening into a routine interruption, permits an implicit live-mode transition, or lets a model synthesize financial authority should fail the test suite.
