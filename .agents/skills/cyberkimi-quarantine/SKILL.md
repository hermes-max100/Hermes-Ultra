---
name: cyberkimi-quarantine
description: Opt-in CyberKimi defensive cyber reasoning skill with strict no-tools/no-autonomy boundaries.
---

# CyberKimi Quarantine

## Purpose

Use CyberKimi only as a quarantined cyber-specialist reviewer for defensive
security analysis, detection engineering, incident response planning, patch
review, and lab-only exploitability assessment reports.

## Required Setup

Select the model explicitly:

```bash
src/system/cloud-model-picker.sh select adverserial lordx64/cyberkimi
```

Or route one task explicitly:

```bash
HERMES_MODEL_KEY_OVERRIDE=cyberkimi-quarantine \
HERMES_PROVIDER_OVERRIDE=adverserial \
HERMES_MODEL_OVERRIDE=lordx64/cyberkimi \
src/system/dynamic-router.sh --json "defensive security review" cyberkimi-quarantine
```

## Allowed Outputs

- threat model reports
- defensive code review notes
- incident response plans
- detection logic drafts
- hardening recommendations
- patch-diff analysis
- lab-only exploitability summaries

## Boundaries

CyberKimi must not:

- run shell commands
- access the network
- scan public targets
- execute exploits
- generate malware, phishing kits, persistence, stealth, or credential theft
- control Android apps or phone bridges
- send, post, delete, invite, purchase, enter credentials, or change settings

Any execution request must be converted into a report or approval request.

## Approval Rule

Human approval is required before any action outside local report generation.
Findings must be exported as report artifacts.
