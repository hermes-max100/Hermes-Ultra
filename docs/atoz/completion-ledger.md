# AtoZ Revenue Coverage Pilot — Completion Ledger

| Work package | Status | Evidence / reason |
| --- | --- | --- |
| P0-1 Current project state | BLOCKED | Remote state/architecture inventoried; local working-tree status unavailable because authorized desktop endpoint is disconnected. |
| P0-2 Verify vendor claims | PASS | `provider-source-register-2026-09-17.md`, `config/atoz/providers.json`; all adapters disabled. |
| P1-3 RecoveryCase + attribution | PASS | `model.py`, `persistence.py`, versioned migration; tests cover paid path, duplicate/conflict, refund, dispute and attribution window. |
| P1-4 Job Packet | PASS | `job_packet.py`; missing critical fields block, unresolved questions force review. |
| P1-5 CRM/calendar connector | BLOCKED | Live system not identified/authorized. Contract-test adapter, manifest, exactly-once mapping and timeout reconciliation implemented. |
| P1-6 Agent controls | PASS | `controls.py` composes Hermes `ApprovalRegistry`; tenant/permissions/per-run budget/data/pause/revoke/cancel/idempotency/consequence boundaries covered. |
| P1-7 Containment + recovery | PASS | Tests cover cross-tenant, host-credential tag, consequential publication, pause/cancel, ambiguous commit/reconciliation and duplicate events. |
| P2-8 Voice benchmark | BLOCKED | Harness/corpus/aggregation complete; no authorized live provider credentials, so no measured provider recommendation fabricated. |
| P2-9 Outcome reporting | PASS | Dashboard reconciles to case records; incremental revenue stays unset. |
| P2-10 Pilot package | PASS | Runbook, config template, schemas, synthetic E2E demo, blockers and rollback included. |
| P3-11 Channel-neutral intake | PASS | `lead.py` + dedupe contract. |
| P3-12 Visual field support | PASS | `visual.py` preserves provenance and requires confirmation for uncertain equipment identity. |
| Production launch | DEFERRED | Requires live integration identity/access, sandbox evidence and explicit production approval. |
| Paid acquisition / marketplace / specialized hardware / smart home | DEFERRED | Outside core-pilot gate. |
