---
name: hermes-local-service-funnel
description: Generate local-service revenue funnel audits, outreach drafts, premortem gates, and approval-gated send handoffs.
---

# Hermes Local Service Funnel

Use this skill when Hermes needs to run the first concrete Revenue OS funnel for
AI automation/service offers to local service businesses.

## Driver

```bash
src/system/local-service-funnel.sh generate --experiment-id ID --prospects-file prospects.jsonl [--record-ledger]
src/system/local-service-funnel.sh prepare-approved-handoff --experiment-id ID --handoff PATH --approval-id ID
src/system/local-service-funnel.sh record-stage --experiment-id ID --prospect-id ID --business-name NAME --stage STAGE
src/system/local-service-funnel.sh pilot-report --experiment-id ID [--prospects-file prospects.jsonl]
```

## Required Upstream State

- Opportunity Engine has normalized a source-linked opportunity.
- Revenue Ledger has an opportunity record when possible.
- Revenue Orchestrator has created an experiment plan.
- Prospect inputs are public/source-linked or manually provided by the user.

## Boundary

This skill may:

- qualify public/manual prospects
- draft tailored audits
- draft outreach copy
- write premortem gate artifacts
- write local send handoff packets
- record local Revenue Ledger draft events
- record local pilot stage events
- render the pilot tracker report from Revenue Ledger and funnel artifacts

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

Preparing a connector handoff requires a Revenue Orchestrator approval receipt,
but the handoff still keeps `allowed_to_send=false`. A downstream connector must
verify the receipt and enforce its own send boundary before any real message can
leave the machine.

## Pilot Tracker

Use `record-stage` for these transitions:

```text
discovered -> qualified -> audit_generated -> outreach_drafted -> approved
-> sent -> replied -> lead_qualified -> call_booked -> proposal_sent
-> lost
-> won -> revenue_received
```

Use `pilot-report` to produce the local tracker artifact and pilot metrics.
Do not change the offer mid-pilot unless the premortem exposes a hard defect.
