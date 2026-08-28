---
name: hermes-revenue-orchestrator
description: Select eligible Revenue OS opportunities and create bounded, approval-gated experiment plans.
---

# Hermes Revenue Orchestrator

Use this skill to create one local, immutable experiment plan from the best
currently eligible Revenue OS opportunity.

## Driver

```bash
src/system/revenue-orchestrator.sh init
src/system/revenue-orchestrator.sh plan
src/system/revenue-orchestrator.sh list-plans
```

## Boundary

Local plans and approval receipts only. No sending, posting, spending, account
changes, credential entry, permission changes, deletion, or irreversible actions.
