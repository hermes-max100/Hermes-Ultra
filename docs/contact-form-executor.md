# Hermes Contact Form Executor

`src/system/contact-form-executor.sh` is the Revenue OS browser execution
boundary for official public contact forms. It consumes the same campaign
policy, approved handoff, and Revenue Orchestrator approval receipt as the
email outbound executor, but only for `contact_form` handoffs.

## Boundary

The executor records `sent` only after positive browser submission evidence is
sealed.

It fails closed for:

- missing or expired campaign approval
- duplicate prospect send attempts
- form URLs outside the prospect's verified official domain
- login/account creation flows
- CAPTCHA or anti-bot challenges
- password, payment, SSN, upload, or credential fields
- unsupported lost-call/lost-revenue claims
- private-network targets unless an explicit test flag is used

## Campaign Policy

Contact forms must be handoff-only, not autonomous email channels:

```bash
src/system/outbound-executor.sh create-campaign-policy \
  --campaign-id camp_exp_local_service_001 \
  --experiment-id exp_local_service_001 \
  --offer "AI-assisted lead capture and follow-up automation" \
  --max-sends 10 \
  --allowed-autonomous-channel email \
  --allowed-autonomous-channel business_email \
  --handoff-only-channel contact_form
```

## Submit a Form

```bash
src/system/contact-form-executor.sh submit \
  --campaign-policy .hermes/revenue-os/campaign-policies/camp_exp_local_service_001.json \
  --handoff path/to/approved-send-handoff.json \
  --approval-id appr_campaign_001 \
  --prospects-file prospects.jsonl \
  --operator-name "Your Name" \
  --operator-email "you@example.com"
```

Optional phone filling is disabled by default. Use `--supply-phone` only when
the campaign policy permits supplying your phone number and the value is
appropriate for the campaign.

## Evidence

Successful submissions write:

- `.hermes/revenue-os/contact-form/receipts/<send_id>.json`
- `.hermes/revenue-os/contact-form/submissions/<browser_run_id>-post.png`
- `.hermes/revenue-os/outbound/send-receipts.jsonl`
- a `sent` stage event through `local-service-funnel`

If browser submission succeeds but evidence or ledger persistence fails, do not
treat the prospect as sent until the missing evidence is repaired.
