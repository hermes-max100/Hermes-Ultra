---
name: virtual-creator-trend-scanner
description: Read-only public trend scanner for AI-disclosed virtual creator revenue workflows. Use when researching niches, content angles, competitor patterns, or current platform/source signals for the virtual creator system.
---

# Virtual Creator Trend Scanner

## Purpose

Collect source-linked trend opportunities for an AI-disclosed virtual creator.
This skill is read-only. It supports content and offer discovery; it does not
post, message, follow, like, scrape private sessions, or make account changes.

## Inputs

- virtual creator profile JSON
- niche or target market
- target platforms
- time horizon
- risk tolerance

## Workflow

1. Check the requested action with `src/system/yolo-gate.sh check`.
2. Use Agent Reach or public web sources for collection.
3. Prefer public, source-linked findings over unsourced claims.
4. Record each trend with URL, platform, evidence excerpt, fit score, risk, and
   next content angle.
5. Label each item as `FACT` when directly observed or `INFERENCE` when derived.

## Output Schema

```json
{
  "trend": "missed-call automation for home service businesses",
  "source_url": "https://example.com/source",
  "platform": "reddit",
  "evidence_excerpt_under_200_chars": "short sanitized excerpt",
  "classification": "FACT",
  "audience_pain": "missed inquiries do not get followed up",
  "content_angle": "show the cost of missed leads",
  "fit_score_1_to_10": 8,
  "risk_low_medium_high": "low",
  "why_now": "recent discussion shows demand"
}
```

## Boundaries

- Do not post, message, like, follow, invite, subscribe, or change accounts.
- Do not use private browser profiles or cookies without explicit approval.
- Do not expose secrets, tokens, cookies, or private user data.
- Do not treat viral revenue claims as verified without payout and analytics
  evidence.
- Human approval is required before any send/post/delete/account action.

