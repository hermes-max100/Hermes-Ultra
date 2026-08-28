# Hermes Ultra Economic Engine Design

## Status

Approved for implementation on 2026-08-27.

## Objective

Add a native, evidence-backed Economic Engine to Hermes Ultra that can discover, evaluate, execute, measure, and stop revenue experiments while preserving Hermes as the sole orchestration/model-routing authority and preserving the existing exact-match autonomy contract.

The first production revenue lane is service sales through Revenue OS. Trading and speculative crypto execution are explicitly out of scope for this subsystem and remain separate governed profiles.

## Architectural rule

The Economic Engine is an additive subsystem beneath `HermesUltraOrchestrator`; it is not a second top-level agent framework. It must use existing Hermes result/evidence concepts and may not grant itself authority.

```text
HermesUltraOrchestrator
        |
        +-- existing coding/research/media lanes
        |
        +-- EconomicEngine
              |
              +-- state + contracts
              +-- opportunity/strategy execution
              +-- persistent ledger
              +-- treasury + authority
              +-- payment/wallet adapters
```

## Execution modes

`EconomicMode` has exactly three values:

- `SIMULATED`: no external financial side effects are possible.
- `SANDBOX`: provider test/sandbox APIs may be used, but no production-capital movement is allowed.
- `LIVE`: production-capital movement is technically eligible, but only after an exact authority decision authorizes the transaction.

Mode is explicit state. No adapter may infer or silently promote mode from credentials, environment, provider responses, or model output.

## Transaction envelope

Every attempted economic side effect is represented by an immutable `TransactionEnvelope` before an adapter is called. Required fields:

- `transaction_id`
- `run_id`
- `strategy_id`
- `bucket`
- `counterparty`
- `amount`
- `currency`
- `expected_value`
- `maximum_loss`
- `reason`
- `source_evidence`
- `authority_category`
- `idempotency_key`
- `created_at`
- `expires_at`
- `mode`

Amounts use `Decimal`, never binary floating point.

## Economic state

Persistent `EconomicState` tracks mode, treasury balances, experiment status, and realized metrics. State serialization must be deterministic and versioned. Restoring state must never change execution mode or broaden authority.

Default treasury buckets are:

- `OPERATIONS`
- `GROWTH`
- `EXPERIMENTS`

## Ledger

The economic ledger is SQLite-backed and append-only at the application API. It stores transaction envelopes, execution outcomes, experiment events, and revenue attribution.

Security properties:

1. Private keys, API keys, bearer tokens, cookies, and session material are never ledger fields.
2. Free-form metadata is passed through the existing `redact_secrets` function before persistence.
3. Duplicate `transaction_id` or `idempotency_key` values cannot produce duplicate ledger movements.
4. Ledger persistence is independent from provider adapters; the ledger is created and tested before any live adapter exists.
5. Every execution outcome references a transaction and a run.

## Simulated adapters

`SimulatedWalletAdapter` is the reference financial adapter. It executes transfers against an in-memory balance map and is idempotent by envelope key.

`MockStripeAdapter` simulates payment creation and revenue receipts with deterministic IDs and no network calls. It exists to exercise the complete Revenue OS loop before live Stripe code is reachable.

## Service-sales strategy

The first real strategy is `ServiceSalesStrategy`.

It accepts a qualified opportunity and produces a deterministic revenue experiment containing:

- target/prospect identity supplied by the caller;
- offer and expected contract value;
- estimated cost;
- expected gross profit;
- proposed next action;
- external-communication authority category where applicable.

The strategy itself performs no network communication and moves no money. Discovery, content generation, messaging, and payment execution remain separate capabilities governed by Hermes.

## Authority model

`FinancialAuthority` evaluates a `TransactionEnvelope` against an explicit policy. Model output cannot create, mutate, or satisfy authority.

The authority decision contains:

- allowed/blocked;
- whether explicit human/owner authorization is required;
- matched category;
- reason;
- policy revision.

Required behavior:

- `SIMULATED` financial movements may execute automatically inside configured simulated limits.
- `SANDBOX` provider actions may execute automatically inside configured sandbox limits.
- `LIVE` money movement requires an exact registered financial authority category plus a supplied authorization grant.
- Expired envelopes are always blocked.
- Amounts above configured per-transaction or per-bucket limits are blocked.
- An LLM-generated string cannot act as an authorization grant.

## Treasury

`TreasuryManager` owns bucket accounting and enforces reservation/commit/release semantics around attempted movements.

A transaction must reserve capital before adapter execution. Success commits the reservation; failure releases it. Replaying the same transaction is idempotent and cannot reserve or debit twice.

Revenue receipts credit a configured bucket and retain strategy/run attribution.

## Live Stripe adapter

The live Stripe adapter remains unreachable until simulated acceptance gates are green. It uses explicit mode and authority inputs, never discovers credentials from browser/session state, and never records secret material.

For API v1 POST operations, Hermes sends the envelope `idempotency_key` as Stripe's `Idempotency-Key` header. Stripe documents that POST requests accept idempotency keys and retries with the same key return the saved result rather than creating a duplicate side effect.

The adapter uses an injectable transport so tests never contact Stripe. The default standard-library transport performs form-encoded HTTPS requests only when `LIVE`/`SANDBOX` eligibility has already been established by the caller.

## Safe adapter

The Safe adapter does not hold or derive private keys. It submits already-signed Safe transaction proposals to the Safe Transaction Service API. Safe documents transaction proposal/confirmation APIs for collecting off-chain signatures before execution.

The adapter requires:

- Safe address;
- sender address;
- sender signature;
- Safe transaction hash;
- complete Safe transaction data;
- explicit authority decision;
- explicit mode.

It may not sign arbitrary transactions inside the LLM/runtime boundary.

## Orchestrator integration

`HermesUltraOrchestrator` gains an optional `economic_engine` dependency and `run_economic_task(...)` delegation method. Existing routing remains unchanged.

Economic failures return existing `CapabilityResult` / `FailureClass` semantics and produce redacted evidence envelopes.

## Failure classes

Add only economic failure classes that are operationally distinct:

- `AUTHORITY_REQUIRED`
- `INSUFFICIENT_FUNDS`
- `DUPLICATE_TRANSACTION`
- `TRANSACTION_EXPIRED`
- `ADAPTER_REJECTED`

No generic risk label becomes an approval category.

## Acceptance gates

Implementation is not complete unless CI demonstrates:

1. No real transaction can bypass financial authority.
2. Duplicate execution cannot double-spend.
3. Secret/private-key material never reaches evidence or ledger serialization.
4. Failed experiments can transition to a terminal stopped state and stop consuming reserved budget.
5. Ordinary research/build work remains autonomous.
6. Economic state survives serialization/restart without changing mode.
7. Every ledger movement maps to a run and strategy.
8. Revenue receipts retain strategy/run attribution.
9. Unsupported/live-disabled adapters fail closed.
10. Simulated mode cannot become live implicitly.
11. External content/model output cannot alter financial policy.
12. Treasury limits survive retries/replays.
13. Revenue OS economic metrics are calculated from recorded outcomes.
14. Trading/crypto capital is not represented by or routable through this Revenue OS subsystem.

## Dependency policy

The core remains Python 3.10+ and standard-library only. No new required runtime dependency is introduced in this phase. Provider transports are injectable so production deployments can later substitute hardened clients without changing contracts.
