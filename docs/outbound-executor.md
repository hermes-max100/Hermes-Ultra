# Hermes Outbound Executor

`src/system/outbound-executor.sh` is the Revenue OS execution boundary for
campaign sends. It consumes a campaign policy, an approved handoff, and a
Revenue Orchestrator approval receipt. It records `sent` only after SMTP or
sendmail succeeds.

## Create a Campaign Policy

```bash
src/system/outbound-executor.sh init
src/system/outbound-executor.sh create-campaign-policy \
  --campaign-id camp_exp_local_service_001 \
  --experiment-id exp_local_service_001 \
  --offer "AI-assisted lead capture and follow-up automation" \
  --max-sends 10 \
  --allowed-autonomous-channel email \
  --allowed-autonomous-channel business_email \
  --handoff-only-channel contact_form
```

Use the returned `campaign_policy_hash` as the `--policy-hash` when recording
the campaign approval receipt through Revenue Orchestrator.

`contact_form` is handoff-only until a governed browser/contact-form transport
exists. The executor will validate and send only autonomous email channels
(`email` and `business_email` by default).

## Validate a Handoff

```bash
src/system/outbound-executor.sh validate-handoff \
  --campaign-policy .hermes/revenue-os/campaign-policies/camp_exp_local_service_001.json \
  --handoff .hermes/revenue-os/funnels/local-service/exp_local_service_001/prospects/.../approved-send-handoff.json \
  --approval-id appr_campaign_001 \
  --prospects-file prospects.jsonl
```

Validation checks:

- campaign policy hash
- approval receipt hash, action, expiry, and experiment
- campaign send cap
- duplicate prospect send prevention
- allowed industry and channel
- handoff-only channels are rejected for autonomous send
- source evidence
- unsupported lost-call/lost-revenue claims

## Send

SMTP mode requires:

```bash
export HERMES_SMTP_HOST=smtp.example.com
export HERMES_SMTP_PORT=587
export HERMES_SMTP_USER=...
export HERMES_SMTP_PASSWORD=...
export HERMES_SMTP_FROM=...
```

Then:

```bash
src/system/outbound-executor.sh send \
  --campaign-policy .hermes/revenue-os/campaign-policies/camp_exp_local_service_001.json \
  --handoff path/to/approved-send-handoff.json \
  --approval-id appr_campaign_001 \
  --prospects-file prospects.jsonl \
  --transport smtp
```

Successful sends write:

- `.hermes/revenue-os/outbound/send-receipts/<send_id>.json`
- `.hermes/revenue-os/outbound/send-receipts.jsonl`
- a `sent` stage event through `local-service-funnel`

## Boundary

The executor does not discover prospects, modify offers, post to social media,
buy anything, alter accounts, enter credentials, or bypass campaign policy.
