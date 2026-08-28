# Hermes Opportunity Engine v1

Opportunity Engine converts source findings into ranked Revenue OS opportunity
records.

## Boundary

It is local-only. It may write:

- `.hermes/revenue-os/opportunity-queue.jsonl`
- `.hermes/revenue-os/reports/opportunity-engine/*.md`
- optional Revenue Ledger opportunity records

It may not send messages, post content, spend money, change accounts, enter
credentials, grant permissions, delete content, or perform platform actions.

## Record Shape

Each normalized opportunity contains:

- `opportunity_id`
- `business_model`
- `customer_segment`
- `problem`
- `offer`
- `channel`
- `evidence_refs`
- `estimated_demand`
- `competition`
- `probability_of_conversion`
- `expected_revenue`
- `expected_cost`
- `expected_profit`
- `automation_fit`
- `time_to_revenue_days`
- `confidence`
- `strategic_fit`
- `compliance_risk`
- `execution_risk`
- `expected_value_score`
- `created_at`
- `expires_at`

## Workflow

```bash
src/system/opportunity-engine.sh normalize --source-file findings.jsonl
src/system/opportunity-engine.sh rank
src/system/opportunity-engine.sh report
```

Use `--write-ledger` only after the source findings are ready to become
ledger-backed opportunity hypotheses.
