---
name: hermes-opportunity-engine
description: Normalize, validate, rank, and queue Revenue OS opportunities from source-linked findings.
---

# Hermes Opportunity Engine

Use this skill when Hermes needs to turn public/source findings into ranked
business opportunities for Revenue OS.

## Driver

```bash
src/system/opportunity-engine.sh init
src/system/opportunity-engine.sh normalize --source-file findings.jsonl
src/system/opportunity-engine.sh normalize --source-file findings.jsonl --write-ledger
src/system/opportunity-engine.sh rank --limit 10
src/system/opportunity-engine.sh report
```

## Inputs

The source file may be JSON, a JSON object with `findings`, or JSONL. Each
finding should include:

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
- `automation_fit`
- `time_to_revenue_days`
- `confidence`
- `strategic_fit`
- `compliance_risk`
- `execution_risk`
- `expires_at`

## Output

The engine writes local artifacts only:

- `.hermes/revenue-os/opportunity-queue.jsonl`
- `.hermes/revenue-os/reports/opportunity-engine/*.md`
- Optional Revenue Ledger records when `--write-ledger` is set

## Boundary

This skill may normalize, score, queue, rank, and report opportunities.

It must not:

- send messages
- post content
- buy anything
- change account settings
- enter credentials
- grant permissions
- delete content
- perform external platform actions

## Scoring

Risk-adjusted score:

```text
expected_profit
* probability_of_conversion
* automation_fit
* confidence
* strategic_fit
/ (time_to_revenue * execution_cost_factor * risk_penalty)
```

Expired opportunities are excluded from ranking by default.
