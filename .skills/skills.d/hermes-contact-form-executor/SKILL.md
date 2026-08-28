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

## Boundary

This skill may validate campaign policy, validate official-domain evidence,
submit ordinary public contact forms, write receipts, and record `sent` only
after positive browser evidence exists.

It must not bypass CAPTCHA/login/anti-bot controls, fill credential/payment/SSN
or upload fields, submit outside the verified prospect domain, or record `sent`
before evidence is sealed.
