# Hermes Reliability, Revenue Outcomes, and Stateful Authorization

This branch adds three complementary control layers without changing production authority.

## Reliability supervisor

`src/system/reliability-supervisor.py` provides scheduler-agnostic durable job state, heartbeats, stall detection, bounded recovery, verified completion receipts, and immutable update receipts. It never spawns arbitrary processes and never grants tool authority.

A scheduler should register a job once, start a run, heartbeat during useful progress, call stall evaluation, and only mark completion with evidence-backed output hashes. Recovery is bounded by the job contract; exhausted recovery budgets fail closed.

## Revenue outcome accounting

`src/system/revenue-ledger.py` now measures economic outcomes rather than model activity. In addition to leads and conversions, it tracks qualified leads, booked appointments, proposals sent, sales closed, attributed revenue, inference cost, tool cost, gross profit, gross margin, cost per qualified lead, cost per appointment, cost per proposal, cost per sale, and attributed revenue per sale.

Legacy `ai_api_cost` remains supported. When explicit `inference_cost` is nonzero it is authoritative so the same model expense is not double-counted.

## Consequential action gate

`src/system/consequential-action-gate.py` authorizes one exact action against one explicit authority grant. It does not execute the action. Authorization requires matching principal and actor, an unexpired grant, allowed action/tool/destination/counterparty, recent identity evidence, required evidence types, per-action limits, cumulative budget, and—when required—an authenticated HMAC approval bound to the exact action.

Authorization receipts are create-only and content-bound. Existing receipts form the durable cumulative-budget and duplicate-action ledger, so process restarts cannot reset spend. A filesystem lock serializes concurrent authorizations against the same ledger.

## Exact approval binding

Revenue Orchestrator approval receipts now include `action_id`, `principal`, `actor`, `counterparty`, `destination`, and `amount` in addition to the existing action/scope/expiry fields. The trusted `approval-security.py` HMAC signs the complete receipt.

The action gate rejects a validly signed approval if any bound field differs from the requested action. Authentication therefore proves both who approved and exactly what was approved.

## Security boundary

This branch does not enable autonomous payments, production deployments, legal filing/service, purchases, or new external communications. Existing execution and containment boundaries remain authoritative. The new gate is a prerequisite authorization layer for future adapters, not an execution bypass.

## Skill intake

`plugin-intake.py` can now inspect standalone skill candidates with the same bounded capability scan used for plugins. Standalone skills remain `CANDIDATE`, cannot auto-activate, and must still pass Trust Gate. Symlinked skill content fails closed.

## Validation

Run:

```bash
python3 tests/test_reliability_supervisor.py
python3 tests/test_revenue_outcomes.py
python3 tests/test_consequential_action_gate.py
python3 tests/test_skill_security_intake.py
bash tests/test_revenue_orchestrator.sh
python3 tests/test_revenue_execution_security.py
bash tests/test_revenue_ledger.sh
```
