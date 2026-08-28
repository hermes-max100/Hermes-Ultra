# Hermes Ultra Economic Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a native Hermes Ultra Economic Engine with persistent economic state, an append-only redacted ledger, simulated revenue/payment loops, service-sales strategy execution, explicit financial authority/treasury controls, and guarded Stripe/Safe adapters.

**Architecture:** `HermesUltraOrchestrator` remains the sole orchestration boundary. The new `hermes_ultra.economic` package defines deterministic contracts/state and uses existing `CapabilityResult`, `FailureClass`, `EvidenceEnvelope`, and `redact_secrets`. Live provider adapters are dependency-injected and fail closed unless mode and authority are explicit.

**Tech Stack:** Python 3.10+, dataclasses, Decimal, Enum, sqlite3, json, urllib, pytest; no new required runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-08-27-hermes-ultra-economic-engine-design.md`

## Global Constraints

- Hermes remains provider/model selection authority.
- Core remains standard-library only; no new required runtime dependency.
- `SIMULATED`, `SANDBOX`, and `LIVE` mode are explicit and never inferred.
- No model output can grant financial authority.
- No private key or provider secret may be persisted in evidence or the economic ledger.
- Trading/crypto strategy execution is out of scope for this Revenue OS subsystem.
- Every production function is introduced through a failing test first.
- Live Stripe/Safe adapter behavior is added only after the simulated acceptance suite is green.

---

### Task 1: Economic contracts and restart-safe state

**Files:**
- Create: `src/hermes_ultra/economic/__init__.py`
- Create: `src/hermes_ultra/economic/contracts.py`
- Create: `src/hermes_ultra/economic/state.py`
- Create: `tests/test_economic_contracts_state.py`

**Interfaces:**
- Produces: `EconomicMode`, `TreasuryBucket`, `ExperimentStatus`, `TransactionEnvelope`, `EconomicState`, `ExperimentState`.
- `TransactionEnvelope.new(...)` creates UUID-backed transaction/idempotency identifiers and UTC timestamps.
- `EconomicState.to_dict()` and `EconomicState.from_dict()` round-trip without changing mode.

- [ ] **Step 1: Write failing tests** for Decimal normalization, immutable envelope identity, explicit mode, three treasury buckets, experiment state, and deterministic state round-trip.
- [ ] **Step 2: Run `pytest tests/test_economic_contracts_state.py -q`** and confirm failure is caused by missing economic package/types.
- [ ] **Step 3: Implement minimal contracts/state** using dataclasses, Enum, Decimal, and explicit JSON-safe string serialization.
- [ ] **Step 4: Run focused test and full `pytest -q`**; both must pass.
- [ ] **Step 5: Commit** `feat: add economic contracts and state`.

### Task 2: Persistent redacted economic ledger

**Files:**
- Create: `src/hermes_ultra/economic/ledger.py`
- Create: `tests/test_economic_ledger.py`

**Interfaces:**
- Consumes: `TransactionEnvelope`, existing `redact_secrets`.
- Produces: `EconomicLedger`, `LedgerEntry`, methods `record_transaction`, `record_outcome`, `record_revenue`, `entries`, `find_transaction`.
- SQLite uniqueness constraints enforce `transaction_id` and `idempotency_key` identity.

- [ ] **Step 1: Write failing tests** proving persistence across reopen, transaction/run/strategy attribution, duplicate idempotency rejection, and secret redaction in metadata.
- [ ] **Step 2: Run focused ledger tests** and verify RED.
- [ ] **Step 3: Implement schema and append APIs** with sqlite3 transactions and redaction before JSON persistence.
- [ ] **Step 4: Run focused/full tests** and verify GREEN.
- [ ] **Step 5: Commit** `feat: add persistent economic ledger`.

### Task 3: Simulated wallet and mock Stripe full-loop adapters

**Files:**
- Create: `src/hermes_ultra/economic/adapters/__init__.py`
- Create: `src/hermes_ultra/economic/adapters/simulated_wallet.py`
- Create: `src/hermes_ultra/economic/adapters/mock_stripe.py`
- Create: `tests/test_economic_simulated_adapters.py`

**Interfaces:**
- Produces: `AdapterResult`, `SimulatedWalletAdapter.transfer(envelope)`, `MockStripeAdapter.create_payment(...)`, `MockStripeAdapter.record_revenue(...)`.
- Replaying an idempotency key returns the original result and cannot debit/credit twice.
- All adapters reject non-simulated envelopes in this task.

- [ ] **Step 1: Write failing tests** for transfer success, insufficient funds, replay idempotency, mode rejection, deterministic mock payment/revenue IDs, and zero network behavior.
- [ ] **Step 2: Run focused adapter tests** and verify RED.
- [ ] **Step 3: Implement minimal simulated adapters** with Decimal balances and in-process idempotency maps.
- [ ] **Step 4: Run focused/full tests** and verify GREEN.
- [ ] **Step 5: Commit** `feat: add simulated economic adapters`.

### Task 4: Revenue OS service-sales strategy and economic metrics

**Files:**
- Create: `src/hermes_ultra/economic/strategies/__init__.py`
- Create: `src/hermes_ultra/economic/strategies/base.py`
- Create: `src/hermes_ultra/economic/strategies/service_sales.py`
- Create: `src/hermes_ultra/economic/metrics.py`
- Create: `src/hermes_ultra/economic/engine.py`
- Create: `tests/test_service_sales_strategy.py`
- Create: `tests/test_economic_engine.py`

**Interfaces:**
- Produces: `RevenueOpportunity`, `RevenueExperiment`, `ServiceSalesStrategy.propose(...)`, `EconomicMetrics`, `EconomicEngine.run_service_sales_experiment(...)`.
- Strategy computes expected gross profit from caller-supplied opportunity economics and never performs external communication itself.
- Engine records experiment lifecycle and mock revenue attribution in the ledger.

- [ ] **Step 1: Write failing tests** for deterministic proposal economics, external-communication category labeling, experiment stop behavior, recorded revenue attribution, and metrics calculated from ledger outcomes.
- [ ] **Step 2: Run focused tests** and verify RED.
- [ ] **Step 3: Implement strategy/engine/metrics** with no network or live money movement.
- [ ] **Step 4: Run focused/full tests** and verify GREEN.
- [ ] **Step 5: Commit** `feat: add service sales economic loop`.

### Task 5: Financial authority and treasury reservation semantics

**Files:**
- Create: `src/hermes_ultra/economic/authority.py`
- Create: `src/hermes_ultra/economic/treasury.py`
- Create: `tests/test_financial_authority.py`
- Create: `tests/test_treasury.py`

**Interfaces:**
- Produces: `AuthorityPolicy`, `AuthorizationGrant`, `AuthorityDecision`, `FinancialAuthority.evaluate(...)`, `TreasuryManager.reserve`, `commit`, `release`, `credit_revenue`.
- Authorization grants are typed objects created outside model text and matched to transaction/category/policy revision.
- Treasury replay of the same transaction is idempotent.

- [ ] **Step 1: Write failing tests** proving simulated/sandbox limit behavior, live authorization requirement, expired transaction blocking, exact category matching, amount/bucket limits, model-string rejection, reserve/commit/release semantics, and replay safety.
- [ ] **Step 2: Run focused tests** and verify RED.
- [ ] **Step 3: Implement authority and treasury** with fail-closed live defaults.
- [ ] **Step 4: Run focused/full tests** and verify GREEN.
- [ ] **Step 5: Commit** `feat: add financial authority and treasury controls`.

### Task 6: Simulated acceptance gate

**Files:**
- Create: `tests/test_economic_acceptance.py`

**Interfaces:**
- Consumes all Tasks 1-5.
- Produces no runtime API; this is the gate that must be green before live adapter files are introduced.

- [ ] **Step 1: Write acceptance tests** proving no double-spend, no secret persistence, failed/stopped experiments cease budget use, restart-safe mode, complete run/strategy attribution, no implicit live promotion, treasury replay safety, and Revenue OS/Trading isolation.
- [ ] **Step 2: Run `pytest tests/test_economic_acceptance.py -q`** and correct any contract gaps via RED/GREEN cycles.
- [ ] **Step 3: Run `python -m compileall -q src && pytest -q`** and require zero failures before proceeding.
- [ ] **Step 4: Commit** `test: gate live adapters on simulated economic suite`.

### Task 7: Guarded Stripe and Safe adapters

**Files:**
- Create: `src/hermes_ultra/economic/adapters/stripe.py`
- Create: `src/hermes_ultra/economic/adapters/safe.py`
- Create: `tests/test_stripe_adapter.py`
- Create: `tests/test_safe_adapter.py`

**Interfaces:**
- `StripeAdapter(api_key, transport=None)` exposes guarded POST operations and sends `Idempotency-Key` from the transaction envelope.
- `SafeAdapter(api_key, service_url, transport=None)` submits pre-signed transaction proposals only; it does not accept or persist private keys.
- Both require an allowed `AuthorityDecision`; both fail closed otherwise.

- [ ] **Step 1: Write failing Stripe tests** proving no request without authority, exact idempotency header, redacted diagnostics, and injectable transport.
- [ ] **Step 2: Verify Stripe RED**, then implement minimal standard-library transport and verify GREEN.
- [ ] **Step 3: Write failing Safe tests** proving no private-key interface exists, pre-signed proposal requirement, authority requirement, and correct `/multisig-transactions/` submission path.
- [ ] **Step 4: Verify Safe RED**, then implement minimal Transaction Service client and verify GREEN.
- [ ] **Step 5: Run simulated acceptance suite again plus full suite**; live adapter addition must not weaken it.
- [ ] **Step 6: Commit** `feat: add guarded Stripe and Safe adapters`.

### Task 8: Hermes orchestrator integration, exports, docs, and final verification

**Files:**
- Modify: `src/hermes_ultra/orchestrator.py`
- Modify: `src/hermes_ultra/contracts.py`
- Modify: `src/hermes_ultra/__init__.py`
- Modify: `README.md`
- Create: `tests/test_economic_orchestrator.py`

**Interfaces:**
- `HermesUltraOrchestrator(..., economic_engine=None)`.
- `run_economic_task(...) -> CapabilityResult` delegates only when configured and records evidence.
- Add economic-specific `FailureClass` values from the spec.

- [ ] **Step 1: Write failing orchestrator tests** for dependency-missing behavior, successful delegation/evidence, and economic failure evidence.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement orchestrator/export/failure-class integration** and document the Economic Engine and live-mode boundary.
- [ ] **Step 4: Run focused tests, `python -m compileall -q src`, and full `pytest -q`**.
- [ ] **Step 5: Verify GitHub Actions** including full suite, autonomy regression suite, and source secret scan.
- [ ] **Step 6: Commit** `feat: integrate Hermes Ultra economic engine`.

## Final requirement audit

Before integration, verify each design acceptance gate against a named test, inspect the branch diff for secret material, and verify the live adapters cannot be reached by changing only model-generated content or provider credentials.
