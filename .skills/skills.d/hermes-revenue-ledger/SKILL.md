---
name: hermes-revenue-ledger
description: Local Revenue OS attribution ledger for experiments, opportunities, conversions, costs, profit, and governed economic learning.
---

# Hermes Revenue Ledger

Use this skill when Hermes needs local attribution for revenue experiments,
opportunities, leads, conversions, costs, profit, and economic learning.

## Driver

```bash
src/system/revenue-ledger.sh init
src/system/revenue-ledger.sh record-event --experiment-id ID --event-type lead
src/system/revenue-ledger.sh summary --group-by experiment_id
src/system/revenue-ledger.sh report
```

## Boundary

Local ledger and report writes only. Sending, posting, purchases, account
changes, permissions, credentials, deletion, and irreversible actions require
human approval outside this skill.
