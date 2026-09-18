-- AtoZ Revenue Coverage schema v1.
-- Monetary values are integer minor units; all timestamps are ISO-8601 UTC/offset strings.
CREATE TABLE IF NOT EXISTS recovery_cases (
    case_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
    lead_conversation_id TEXT NOT NULL, original_lead_source TEXT NOT NULL,
    intake_at TEXT NOT NULL, currency TEXT NOT NULL,
    attribution_window_hours INTEGER NOT NULL, attribution_rule_version TEXT NOT NULL,
    status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
    appointment_id TEXT, job_id TEXT, payment_id TEXT,
    collected_amount_minor INTEGER NOT NULL DEFAULT 0,
    refunded_amount_minor INTEGER NOT NULL DEFAULT 0,
    provider_cost_minor INTEGER NOT NULL DEFAULT 0,
    human_review_minutes INTEGER NOT NULL DEFAULT 0,
    completion_at TEXT, collection_at TEXT, cancellation_at TEXT,
    duplicate_of_case_id TEXT, dispute_status TEXT NOT NULL DEFAULT 'none',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS recovery_events (
    event_id TEXT PRIMARY KEY, event_hash TEXT NOT NULL,
    case_id TEXT NOT NULL, tenant_id TEXT NOT NULL, kind TEXT NOT NULL,
    occurred_at TEXT NOT NULL, payload_json TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES recovery_cases(case_id)
);
CREATE INDEX IF NOT EXISTS idx_recovery_events_case ON recovery_events(case_id, occurred_at, event_id);
CREATE TABLE IF NOT EXISTS billable_outcome_decisions (
    case_id TEXT NOT NULL, rule_version TEXT NOT NULL, eligible INTEGER NOT NULL,
    reasons_json TEXT NOT NULL, evidence_refs_json TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    success_fee_enabled INTEGER NOT NULL DEFAULT 0 CHECK(success_fee_enabled = 0),
    PRIMARY KEY(case_id, rule_version),
    FOREIGN KEY(case_id) REFERENCES recovery_cases(case_id)
);
PRAGMA user_version = 1;
