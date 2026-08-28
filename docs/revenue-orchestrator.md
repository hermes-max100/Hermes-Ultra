# Hermes Revenue Orchestrator v1

Revenue Orchestrator selects one eligible opportunity and converts it into a
bounded experiment plan.

## Boundary

It may:

- read `.hermes/revenue-os/opportunity-queue.jsonl`
- read `.hermes/revenue-os/opportunities.jsonl`
- write immutable experiment plans
- write approval receipt artifacts supplied by an upstream approval mechanism
- persist plan evidence to Memory Fabric

It may not send, post, spend, purchase, change accounts, enter credentials,
change permissions, delete data, or perform platform actions.

## Commands

```bash
src/system/revenue-orchestrator.sh init
src/system/revenue-orchestrator.sh plan
src/system/revenue-orchestrator.sh list-plans
src/system/revenue-orchestrator.sh show --experiment-id ID
```

## Approval Receipts

Approval-required steps need a separate receipt:

```bash
src/system/revenue-orchestrator.sh record-approval \
  --approval-id appr_001 \
  --experiment-id exp_001 \
  --action send \
  --scope "send one approved outreach draft to one named prospect" \
  --action-id act_001 \
  --principal owner \
  --actor revenue-os \
  --counterparty prospect_001 \
  --destination smtp://prospect@example.com \
  --amount 0 \
  --approver "human" \
  --policy-hash "<policy hash>" \
  --expires-at 2026-08-16T00:00:00Z
```

`human_approved=true` is not authority for Revenue Orchestrator. Approval receipts are HMAC-authenticated and bind the exact action ID, principal, actor, counterparty, destination, and amount for use by the stateful consequential-action gate.

## Next Step

After this layer, build one real revenue funnel:

```text
opportunity -> experiment plan -> public prospect discovery -> tailored audit
-> offer draft -> human-approved outreach -> response tracking -> proposal
-> fulfillment -> ledger attribution
```
