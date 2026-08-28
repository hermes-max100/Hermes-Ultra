---
name: hermes-contact-form-executor
description: Governed browser execution for approved Revenue OS public contact-form handoffs.
---

# Hermes Contact Form Executor

Use this skill when Hermes needs to submit an approved Local Service Funnel
handoff through an official public contact form.

## Driver

```bash
src/system/contact-form-executor.sh init
src/system/contact-form-executor.sh validate-handoff --campaign-policy PATH --handoff PATH --approval-id ID --prospects-file prospects.jsonl
src/system/contact-form-executor.sh submit --campaign-policy PATH --handoff PATH --approval-id ID --prospects-file prospects.jsonl --operator-name NAME --operator-email EMAIL
```

## Required Upstream State

- Revenue Orchestrator experiment plan exists.
- Local Service Funnel generated an approved send handoff.
- Campaign policy exists and has a campaign-level approval receipt.
- `contact_form` is listed as a handoff-only campaign channel.
- The contact form URL is an official public URL for the prospect.

## Boundary

This skill may:

- validate campaign policy and approval receipts
- validate official-domain and source evidence
- fill only allowlisted business-contact fields
- submit an official public contact form
- capture screenshot and confirmation evidence
- write immutable contact-form receipts
- record `sent` only after positive submission evidence is sealed

It must not:

- discover prospects
- mutate the offer or outreach strategy
- bypass CAPTCHA, login, anti-bot, or access controls
- fill password, payment, SSN, upload, credential, or account fields
- submit forms outside the prospect's verified official domain
- record `sent` before browser submission evidence exists

## Production Rule

If the form asks for anything beyond ordinary business contact fields, abort.
If the browser cannot capture positive submission evidence, do not record
`sent`.
