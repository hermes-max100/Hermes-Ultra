# AtoZ Pilot Schemas and Example Records

## RecoveryCase v1

Persistence is SQLite schema version `1`; canonical migration is `migrations/atoz/001_revenue_coverage.sql`. Monetary values are integer minor units; timestamps are timezone-aware; `event_id` is the durable idempotency key. Identical replay is a no-op, conflicting reuse fails closed, and cross-tenant events fail closed.

Example projected record:

```json
{"case_id":"case-demo-1","tenant_id":"tenant-demo","lead_conversation_id":"lead-demo-1","original_lead_source":"synthetic-after-hours-call","currency":"USD","status":"paid","appointment_id":"appt-demo-1","job_id":"job-demo-1","payment_id":"payment-demo-1","collected_amount_minor":42500,"refunded_amount_minor":0,"provider_cost_minor":125,"human_review_minutes":3,"attribution_rule_version":"atoz-attribution-v1"}
```

## BillableOutcomeDecision v1

Eligibility is separate from recovered/paid status. It requires completion, positive net collection, an in-window attribution, no cancellation/refund/duplicate/open dispute, and supporting evidence. Success-fee charging remains disabled.

## JobPacket v1

Required dispatch fields are source case/revision, customer need, service location, and appointment identifier. Unresolved questions force review; missing critical fields block dispatch.

## LeadConversation v1

Carries source, source ID, campaign, consent evidence, need, qualification, handoff, acquisition cost in minor units, currency, receipt time, and metadata. Dedupe is source-neutral.

## Visual Job Packet v1

Each visual observation preserves asset ID and provenance. Observed detail is separated from model inference. Equipment identity below 0.90 confidence, or an unscored inferred identity, requires confirmation.
