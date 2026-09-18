# AtoZ After-Hours Revenue Coverage Pilot Runbook

## Scope

`after-hours intake -> qualification -> RecoveryCase -> Job Packet -> CRM/calendar booking or escalation -> follow-up -> final disposition -> completed-paid-job attribution -> evidence report`

No paid acquisition, production customer contact, live payments, success-fee billing, marketplace listing, smart-home integration, or specialized hardware is enabled.

## Developer verification

```bash
python -m pip install -e '.[test]'
pytest -q tests/test_voice_revenue_recovery.py tests/test_atoz_revenue_coverage.py
python -m compileall -q src/hermes_ultra/atoz
python scripts/run_atoz_voice_benchmark.py --show-corpus
python scripts/run_atoz_voice_benchmark.py --observations config/atoz/benchmark-fixture.synthetic.json
```

The benchmark fixture is explicitly non-live and only proves harness behavior.

## Synthetic demonstration

```python
from hermes_ultra.atoz import run_synthetic_demo
print(run_synthetic_demo("var/atoz/demo.sqlite3"))
```

Expected properties: one lead maps to one RecoveryCase; an ambiguous connector timeout reconciles to one CRM/calendar object pair; a Job Packet links to the case revision; completed job + collected payment yields attribution; success-fee execution remains disabled; attributed revenue is distinct from incremental revenue.

## Live connector onboarding

1. Name the actual CRM and calendar.
2. Confirm tenant/account IDs and owner-authorized permission scope.
3. Store credentials outside source.
4. Map AtoZ IDs to external IDs.
5. Prove idempotent create/update.
6. Inject response-loss-after-commit and reconcile before retry.
7. Verify readback.
8. Record rollback/compensation path.
9. Only then enable outside source.

## Incident behavior

- Global pause blocks new dispatches.
- Agent revocation blocks subsequent actions.
- Run cancellation blocks queued/new actions.
- Accepted external work is not claimed to be reversed; reconcile or compensate from evidence.
- Ambiguous timeout: reconcile by idempotency key before retry.
- Cross-tenant/forbidden data: fail closed before dispatch.
- Budget exhaustion blocks before dispatch; idempotent replay does not spend twice.

## Rollback

Disable AtoZ integration flags, stop new dispatches, preserve SQLite/event evidence, revert the pilot commit/PR if needed, and reconcile any already-accepted external action. Never delete evidence to make rollback appear clean.
