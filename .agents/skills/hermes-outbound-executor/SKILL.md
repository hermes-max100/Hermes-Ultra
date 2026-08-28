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

This skill may:

- validate campaign policy and approval receipts
- validate source evidence and allowed channels
- prevent duplicate sends
- send through configured SMTP/sendmail
- write send receipts
- record `sent` only after transport success

It must not:

- discover prospects
- mutate the offer or outreach strategy
- send without a campaign policy and approval receipt
- send to prohibited channels such as SMS, phone, personal email, or social DM
- buy anything
- change accounts or enter credentials
- record `sent` before transport success
- treat contact forms as autonomous sends before a governed browser/contact-form executor exists

## Production Rule

For real sends, use `smtp` or a governed `sendmail` bridge with public business
email only. `contact_form` is handoff-only until a governed browser/contact-form
executor exists. If the target only has phone, social DM, personal email, or
contact-form/manual-review contact data, the executor must reject automatic send
and the campaign must use a manual/governed path instead.
