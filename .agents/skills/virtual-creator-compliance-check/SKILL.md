---
name: virtual-creator-compliance-check
description: Policy gate for AI-disclosed virtual creator drafts. Returns pass, revise, or block before any content reaches approval queue.
---

# Virtual Creator Compliance Check

## Purpose

Review virtual creator drafts for deception, platform risk, unsupported claims,
likeness issues, and approval requirements.

## Decision Values

- `pass`: draft is acceptable for human approval queue.
- `revise`: draft can be fixed before approval queue.
- `block`: draft violates a hard boundary.

## Checks

1. AI disclosure is present where required or where users could be misled.
2. No hidden synthetic identity or "nobody knows she is not real" framing.
3. No stolen likeness, celebrity lookalike, private-person mimicry, or deepfake.
4. No unsupported earnings, customer, legal, medical, or performance claims.
5. No fake personal relationship, romantic availability, or human intimacy
   claims.
6. No automated DM language pretending to be a human.
7. No adult-content evasion language.
8. Posting, sending, replying, deleting, account changes, purchases, credentials,
   and permissions are marked `human_required`.

## Output Schema

```json
{
  "decision": "pass",
  "reasons": [],
  "required_changes": [],
  "disclosure_status": "present",
  "unsupported_claims": [],
  "likeness_or_deception_risk": "low",
  "approval_required": true,
  "human_required_actions": ["post", "send", "delete", "account_change"]
}
```

## Hard Blocks

Return `block` if the draft:

- hides that the creator is AI-generated,
- mimics a real person,
- uses fake payout or revenue proof,
- implies a real human relationship where none exists,
- asks Hermes/JARVIS to post/send/delete without human approval.

