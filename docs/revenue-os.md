# Hermes Revenue OS v1

Revenue OS changes the optimization target from internal capability growth to:

```text
maximize verified risk-adjusted profit within explicit budget, compliance,
security, and approval constraints
```

## Current Layer

`src/system/revenue-ledger.sh` implements Revenue Ledger + Attribution v1.

It records:

- experiments
- workflows
- offers
- channels
- campaigns
- assets
- leads
- customers
- impressions
- clicks
- leads
- qualified leads
- conversions
- gross revenue
- refunds
- platform fees
- ad spend
- AI/API cost
- other cost
- net revenue
- profit
- conversion rate
- CAC
- ROAS
- profit per lead

It also records opportunity hypotheses and ranks them by expected value.

`src/system/opportunity-engine.sh` implements Opportunity Engine v1.

It turns public/source findings into normalized opportunity records, validates
evidence references, applies expiry/staleness, scores expected value, and writes
a ranked local queue.

`src/system/revenue-orchestrator.sh` implements Revenue Orchestrator v1.

It chooses the best currently eligible ledger-backed opportunity and creates one
bounded, immutable local experiment plan with approval-required steps separated
from autonomous local work.

`src/system/local-service-funnel.sh` implements the first concrete Revenue OS
funnel.

It turns one experiment plan and a prospect file into source-linked prospect
qualification, tailored audit drafts, outreach drafts, a premortem gate, local
send handoff packets, optional Revenue Ledger draft events, and a pilot tracker
report. It does not send or perform platform actions.

## Commands

```bash
src/system/revenue-ledger.sh init

src/system/revenue-ledger.sh record-event \
  --experiment-id exp_ai_services_001 \
  --workflow-id wf_public_business_audit \
  --offer-id ai-followup-setup \
  --channel manual \
  --campaign first-test \
  --event-type lead \
  --leads 1 \
  --qualified-leads 1 \
  --notes "Manual seed lead"

src/system/revenue-ledger.sh record-event \
  --experiment-id exp_ai_services_001 \
  --event-type conversion \
  --conversions 1 \
  --gross-revenue 497 \
  --platform-fees 15 \
  --ai-api-cost 2

src/system/revenue-ledger.sh record-opportunity \
  --business-model "AI service setup" \
  --customer "local service businesses" \
  --problem "missed inbound lead follow-up" \
  --offer "lead capture and follow-up automation setup" \
  --channel "manual/public research" \
  --probability-of-conversion 0.08 \
  --expected-profit 900 \
  --automation-fit 0.8 \
  --time-to-revenue-days 7 \
  --startup-cost 0 \
  --confidence 0.6

src/system/revenue-ledger.sh summary --group-by experiment_id
src/system/revenue-ledger.sh rank-opportunities
src/system/revenue-ledger.sh report
```

## Opportunity Engine

Example source findings file:

```json
[
  {
    "business_model": "AI service setup",
    "customer_segment": "local service businesses",
    "problem": "missed inbound lead follow-up",
    "offer": "lead capture and follow-up automation setup",
    "channel": "public business discovery",
    "evidence_refs": [
      {"type": "source", "ref": "https://example.com/local-business-directory"}
    ],
    "estimated_demand": 0.8,
    "competition": 0.45,
    "probability_of_conversion": 0.08,
    "expected_revenue": 1500,
    "expected_cost": 100,
    "automation_fit": 0.85,
    "time_to_revenue_days": 7,
    "confidence": 0.7,
    "strategic_fit": 0.9,
    "compliance_risk": 0.1,
    "execution_risk": 0.2
  }
]
```

Commands:

```bash
src/system/opportunity-engine.sh init
src/system/opportunity-engine.sh normalize --source-file findings.jsonl
src/system/opportunity-engine.sh normalize --source-file findings.jsonl --write-ledger
src/system/opportunity-engine.sh rank --limit 10
src/system/opportunity-engine.sh report
```

Risk-adjusted scoring:

```text
expected_profit
* probability_of_conversion
* automation_fit
* confidence
* strategic_fit
/ (time_to_revenue * execution_cost_factor * risk_penalty)
```

Expired opportunities are excluded from rankings unless `--include-expired` is
provided. Findings without evidence are retained but confidence is capped and the
evidence status is marked `insufficient`.

## Revenue Orchestrator

Commands:

```bash
src/system/revenue-orchestrator.sh init
src/system/revenue-orchestrator.sh plan
src/system/revenue-orchestrator.sh list-plans
src/system/revenue-orchestrator.sh show --experiment-id exp_...
```

The orchestrator consumes Opportunity Engine queue records plus Revenue Ledger
opportunity records. By default it requires the selected opportunity to be:

- ledger-backed
- unexpired
- evidence-backed enough
- above the confidence threshold
- below compliance and execution risk limits
- within the configured budget-request ceiling

It writes immutable local artifacts under:

```text
.hermes/revenue-os/experiments/<experiment_id>/
  experiment-plan.json
  experiment-receipt.json
```

Each plan separates actions into:

- `AUTONOMOUS`: public research, analysis, drafting, local artifacts, lead
  scoring, reporting, ledger entries
- `APPROVAL_REQUIRED`: send, post, outreach, purchase, payment, credential use,
  account modification, permission change, external messages, paid spend
- `PROHIBITED`: actions outside declared policy

Approval-required actions are not authorized by a boolean flag. A future runtime
must present a separate approval receipt with:

```text
approval_id
experiment_id
action
scope
approved_at
expires_at
approver
policy_hash
```

## Local Service Funnel

Commands:

```bash
src/system/local-service-funnel.sh generate \
  --experiment-id exp_... \
  --prospects-file prospects.jsonl \
  --record-ledger

src/system/local-service-funnel.sh prepare-approved-handoff \
  --experiment-id exp_... \
  --handoff .hermes/revenue-os/funnels/local-service/exp_.../prospects/.../send-handoff.json \
  --approval-id appr_...

src/system/local-service-funnel.sh record-stage \
  --experiment-id exp_... \
  --prospect-id pros_... \
  --business-name "Apex Plumbing" \
  --stage sent

src/system/local-service-funnel.sh pilot-report \
  --experiment-id exp_... \
  --prospects-file prospects.jsonl
```

The funnel writes local artifacts under:

```text
.hermes/revenue-os/funnels/local-service/<experiment_id>/
  funnel-summary.json
  premortem-gate-<timestamp>.md
  prospects/<business>-<prospect_id>/
    audit.md
    outreach-draft.md
    send-handoff.json
  pilot-tracker.json
  pilot-tracker.md
```

`prepare-approved-handoff` verifies that a Revenue Orchestrator approval receipt
exists, but it still writes `allowed_to_send=false`. A downstream connector must
verify the receipt and enforce the real send boundary.

The pilot tracker uses this state machine:

```text
discovered -> qualified -> audit_generated -> outreach_drafted -> approved
-> sent -> replied -> lead_qualified -> call_booked -> proposal_sent
-> lost
-> won -> revenue_received
```

It reports reviewed prospects, qualified rate, outreach sent, reply rate,
positive reply rate, calls booked, proposals sent, wins/losses, gross revenue,
direct cost, profit, cost per qualified lead, and profit per contacted prospect.
Counts are based on unique prospects reaching each stage, not raw stage-event
counters.

Revenue Ledger also reports booked appointments, proposals sent, sales closed, attributed revenue, inference/tool cost, gross margin, and cost per qualified lead/appointment/proposal/sale so Revenue OS can optimize business outcomes rather than token volume.

## Boundaries

The ledger is local-only. It does not:

- send messages
- post content
- make purchases
- change accounts
- enter credentials
- grant permissions
- delete content
- perform irreversible actions

Those actions remain human-approved workflows.

## Next Layer

After attribution exists, the next layer is:

```text
one complete revenue funnel
```

That layer now starts with the local-service funnel. The next milestone is to
run real, human-approved experiments and measure attributable profit instead of
adding more infrastructure.
