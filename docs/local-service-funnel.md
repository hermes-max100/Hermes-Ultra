# Hermes Local Service Funnel v1

This is the first concrete Revenue OS funnel. It turns one approved experiment
plan into local artifacts for a high-value AI automation service offer to local
service businesses.

The funnel is intentionally narrow:

```text
experiment plan
-> prospect list
-> qualification
-> tailored audit
-> outreach draft
-> premortem gate
-> approval-gated send handoff
-> Revenue Ledger draft event
```

It does not send messages, post, buy anything, change accounts, enter
credentials, or perform platform actions.

## Inputs

Create an experiment with Revenue Orchestrator first:

```bash
src/system/opportunity-engine.sh normalize --source-file findings.jsonl --write-ledger
src/system/revenue-orchestrator.sh plan --experiment-id exp_local_service_001
```

Then provide a JSON or JSONL prospect file. Supported fields:

```json
{
  "business_name": "Apex Plumbing",
  "category": "plumbing",
  "city": "Riverside",
  "state": "CA",
  "website": "https://example.com/apex",
  "contact_channel": "email",
  "contact_ref": "hello@example.com",
  "source_url": "https://example.com/apex-profile",
  "signals": ["missed-calls", "no-online-booking", "high-ticket-service"]
}
```

Useful signals include:

- `missed-calls`
- `slow-response`
- `no-online-booking`
- `manual-follow-up`
- `bad-contact-flow`
- `active-ads`
- `high-ticket-service`
- `emergency-service`

## Commands

Generate local funnel artifacts:

```bash
src/system/local-service-funnel.sh generate \
  --experiment-id exp_local_service_001 \
  --prospects-file prospects.jsonl \
  --record-ledger
```

The command writes:

```text
.hermes/revenue-os/funnels/local-service/<experiment_id>/
  funnel-summary.json
  premortem-gate-<timestamp>.md
  prospects/<business>-<prospect_id>/
    audit.md
    outreach-draft.md
    send-handoff.json
```

If a human approves one outreach action through Revenue Orchestrator:

```bash
src/system/revenue-orchestrator.sh record-approval \
  --approval-id appr_local_service_001 \
  --experiment-id exp_local_service_001 \
  --action send \
  --scope "send one approved outreach draft to Apex Plumbing" \
  --action-id act_local_service_001 \
  --principal owner \
  --actor revenue-os \
  --counterparty "Apex Plumbing" \
  --destination smtp://hello@example.com \
  --amount 0 \
  --approver "human" \
  --policy-hash "<policy-hash-from-plan>" \
  --expires-at "2026-08-22T00:00:00Z"
```

Prepare a connector handoff packet:

```bash
src/system/local-service-funnel.sh prepare-approved-handoff \
  --experiment-id exp_local_service_001 \
  --handoff .hermes/revenue-os/funnels/local-service/exp_local_service_001/prospects/apex-plumbing-pros_.../send-handoff.json \
  --approval-id appr_local_service_001
```

The approved handoff still records `allowed_to_send=false`. A future connector
must verify the receipt and enforce its own send boundary. This tool never
sends.

## Pilot Tracker

The pilot tracker is a thin reporting layer over Revenue Ledger events and the
generated funnel artifacts. It does not introduce a separate database.

Record state transitions as the pilot runs:

```bash
src/system/local-service-funnel.sh record-stage \
  --experiment-id exp_local_service_001 \
  --prospect-id pros_... \
  --business-name "Apex Plumbing" \
  --stage sent \
  --approval-id appr_local_service_001 \
  --notes "Manual send completed after approval"

src/system/local-service-funnel.sh record-stage \
  --experiment-id exp_local_service_001 \
  --prospect-id pros_... \
  --business-name "Apex Plumbing" \
  --stage replied \
  --reply-status positive

src/system/local-service-funnel.sh record-stage \
  --experiment-id exp_local_service_001 \
  --prospect-id pros_... \
  --business-name "Apex Plumbing" \
  --stage revenue_received \
  --gross-revenue 1500 \
  --direct-cost 100
```

Allowed stages:

```text
discovered -> qualified -> audit_generated -> outreach_drafted -> approved
-> sent -> replied -> lead_qualified -> call_booked -> proposal_sent
-> lost
-> won -> revenue_received
```

The tracker counts funnel progress by unique prospect IDs reaching a stage.
`qualified` and `lead_qualified` are distinct state transitions, but they do not
double-count the same prospect as two qualified leads.

Generate the report:

```bash
src/system/local-service-funnel.sh pilot-report \
  --experiment-id exp_local_service_001 \
  --prospects-file prospects.jsonl
```

The report writes:

```text
.hermes/revenue-os/funnels/local-service/<experiment_id>/
  pilot-tracker.json
  pilot-tracker.md
```

The report answers:

- prospects reviewed
- qualified rate
- outreach sent
- reply rate
- positive reply rate
- calls booked
- proposals sent
- wins/losses
- gross revenue
- total direct cost
- profit
- cost per qualified lead
- profit per contacted prospect

## Premortem Gate

Every run writes a premortem artifact. Use it before launching the first real
outreach batch to check:

- whether prospect evidence is specific enough
- whether the offer is framed as a business outcome, not generic AI
- whether the human approval queue will actually be worked
- whether fulfillment scope is clear
- whether every manual step will be recorded in Revenue Ledger
