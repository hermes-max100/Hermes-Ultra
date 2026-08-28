---
name: hermes-revenue-orchestrator
description: Select eligible Revenue OS opportunities and create bounded, approval-gated experiment plans.
---

# Hermes Revenue Orchestrator

Use this skill when Hermes needs to choose the best currently eligible
opportunity and turn it into one bounded, ledger-tracked experiment plan.

## Driver

```bash
src/system/revenue-orchestrator.sh init
src/system/revenue-orchestrator.sh plan
src/system/revenue-orchestrator.sh list-plans
src/system/revenue-orchestrator.sh show --experiment-id ID
src/system/revenue-orchestrator.sh record-approval --approval-id ID --experiment-id ID --action send --scope SCOPE --approver NAME --policy-hash HASH --expires-at TS
```

## Boundary

This skill may:

- read local opportunity queue and ledger records
- rank eligible opportunities
- create immutable local experiment plans
- record upstream approval receipts
- write local reports/artifacts

It must not:

- send messages
- post content
- buy anything
- change account settings
- enter credentials
- grant permissions
- delete content
- perform external platform actions

## Approval Rule

Approval-required actions cannot be authorized by setting
`human_approved=true`. They require a separate approval receipt containing:

- `approval_id`
- `experiment_id`
- `action`
- `scope`
- `approved_at`
- `expires_at`
- `approver`
- `policy_hash`
