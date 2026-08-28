---
name: hermes-outbound-executor
description: Campaign-policy-gated outbound execution for Revenue OS sends with duplicate prevention and sent-stage receipts.
---

# Hermes Outbound Executor

Use this skill when Hermes needs to validate or execute an outbound Revenue OS
campaign send from a prepared Local Service Funnel handoff.

## Driver

```bash
src/system/outbound-executor.sh init
src/system/outbound-executor.sh create-campaign-policy --experiment-id ID --offer OFFER
src/system/outbound-executor.sh validate-handoff --campaign-policy PATH --handoff PATH --approval-id ID --prospects-file prospects.jsonl
src/system/outbound-executor.sh send --campaign-policy PATH --handoff PATH --approval-id ID --prospects-file prospects.jsonl --transport smtp|sendmail
```

## Required Upstream State

- Revenue Orchestrator experiment plan exists.
- Local Service Funnel generated an approved send handoff.
- Campaign policy exists and has a campaign-level approval receipt.
- The target has a permitted autonomous outbound channel such as business email.

## Boundary

This skill may validate campaign policy, execute configured SMTP/sendmail sends
to public business email channels, write send receipts, and record `sent` after
transport success.

It must not discover prospects, mutate the offer, send without approval, send to
prohibited channels, buy anything, change accounts, enter credentials, or record
`sent` before transport success.

`contact_form` is handoff-only until a governed browser/contact-form executor
exists. The executor must reject automatic send for contact forms, phone,
social DM, personal email, or manual-review-only contact data.
