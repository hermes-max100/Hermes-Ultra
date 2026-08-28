---
name: virtual-creator-analytics
description: Tracks local performance metrics for AI-disclosed virtual creator content and revenue experiments.
---

# Virtual Creator Analytics

## Purpose

Record and review virtual creator performance without requiring platform
credentials. Use manual entry, exported analytics, or approved API imports.

## Ledger Fields

```json
{
  "ts": "2026-08-06T00:00:00Z",
  "platform": "instagram",
  "post_id": "manual-or-platform-id",
  "topic": "missed lead follow-up",
  "format": "reel",
  "views": 0,
  "likes": 0,
  "comments": 0,
  "saves": 0,
  "profile_clicks": 0,
  "link_clicks": 0,
  "leads": 0,
  "sales": 0,
  "cost_usd": 0,
  "notes": "manual entry or API import"
}
```

## Review Rules

- Identify top-performing pillars and formats.
- Flag weak content after enough impressions, not after one post.
- Treat revenue claims as internal metrics unless substantiated.
- Do not publish analytics or claims without human approval.

## Kill Criteria

- 30 posts with no profile clicks.
- 1000 profile visits with no qualified leads.
- 20 qualified leads with no booked calls.
- Cost or labor exceeds expected first-order revenue.

