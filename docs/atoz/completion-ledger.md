# AtoZ Revenue Coverage Pilot — Completion Ledger

Status means the stated completion gate is actually satisfied, not merely that code exists.

| Work package | Status | Evidence / reason |
| --- | --- | --- |
| P0-1 Current project state | BLOCKED | Remote state/architecture inventoried; local working-tree status unavailable because the authorized desktop endpoint is disconnected. |
| P0-2 Verify vendor claims | PASS | `provider-source-register-2026-09-17.md`, `config/atoz/providers.json`; official documentation checked and every live adapter remains disabled. |
| P1-3 RecoveryCase + attribution | PASS | `model.py`, `persistence.py`, versioned migration; tests cover paid path, idempotent replay/conflict, refund, dispute, duplicate and attribution window. |
| P1-4 Job Packet | PASS | `job_packet.py`; missing critical fields block dispatch and unresolved questions force review. |
| P1-5 CRM/calendar connector | BLOCKED | Actual live pilot system was not identified/authorized. Contract-test adapter, manifest, exactly-once mapping and ambiguous-timeout reconciliation are implemented. |
| P1-6 Agent controls | BLOCKED | AtoZ execution-policy boundary is implemented/tested and composes Hermes `ApprovalRegistry`, but binding to the authoritative live Hermes tool gateway/job runner cannot be verified while the host is disconnected. |
| P1-7 Containment + recovery | BLOCKED | Automated adversarial database/policy/connector tests exist, but the requested observed live gateway/network/host evidence cannot be produced without the Hermes host and authorized endpoints. See `containment-evidence-2026-09-17.md`. |
| P2-8 Voice benchmark | BLOCKED | Harness/corpus/aggregation complete; no authorized live provider credentials, so no measured provider recommendation is fabricated. |
| P2-9 Outcome reporting | PASS | Dashboard reconciles to RecoveryCase records; attributed revenue is explicit and proven incremental revenue remains unset. |
| P2-10 Pilot package | PASS | Runbook, config template, schemas, synthetic E2E demo, blockers and rollback included. |
| P3-11 Channel-neutral intake | PASS | `lead.py` + source-neutral dedupe contract. |
| P3-12 Visual field support | PASS | `visual.py` preserves provenance, separates observed detail from inference, and requires confirmation for uncertain equipment identity. |
| Production launch | DEFERRED | Requires live connector identity/access, host-level control evidence, sandbox/live-provider benchmark evidence and explicit production approval. |
| Paid acquisition / marketplace / specialized hardware / smart home | DEFERRED | Outside the core-pilot gate. |
