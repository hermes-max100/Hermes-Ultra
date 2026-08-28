---
name: hermes-revenue-ledger
description: Local Revenue OS attribution ledger for experiments, opportunities, conversions, costs, profit, and governed economic learning.
---

# Hermes Revenue Ledger

Use this skill when Hermes needs to record or analyze revenue experiments,
opportunities, leads, conversions, costs, attribution, profit, or economic
learning.

## Driver

```bash
src/system/revenue-ledger.sh init
src/system/revenue-ledger.sh record-event --experiment-id ID --event-type lead
src/system/revenue-ledger.sh record-opportunity --business-model ... --customer ... --problem ... --offer ... --channel ...
src/system/revenue-ledger.sh summary --group-by experiment_id
src/system/revenue-ledger.sh rank-opportunities
src/system/revenue-ledger.sh report
```

## Boundary

This skill is local-only. It may write local ledger entries and reports.

It must not:

- send messages
- post content
- buy anything
- change account settings
- enter credentials
- grant permissions
- delete content
- perform irreversible account actions

## Optimization Target

Optimize for verified risk-adjusted profit, not activity, views, followers, or
gross revenue without costs.

Every economic workflow should preserve attribution fields:

- `experiment_id`
- `workflow_id`
- `offer_id`
- `channel`
- `campaign`
- `asset_id`
- `lead_id`
- `customer_id`
