# AtoZ Revenue Coverage Pilot — Current-State Inventory

Verified: 2026-09-17

## Source of truth inspected

- Repository: `hermes-max100/Hermes-Ultra`
- Default branch: `main`
- Remote HEAD inspected: `f7a1581c6374217d46db247522cc0551b15c1d91`
- Remote tree: `cabe2da0a3f726e647e9dfd8a7c01d7646e79a4d`
- Local host working-tree status: **unavailable**. The authorized Remote Desktop Commander endpoint reported no connected device, so no claim is made about unpublished local changes.
- Dedicated AtoZ runtime repository: **not found** in the connected GitHub repository inventory.
- `hermes-max100/proficio`: inspected and rejected as an implementation target because it is the Android prompt/tooling-control application, not the AtoZ service runtime.

## Existing Hermes capabilities reused

| Requested capability | Inspected source | State before this pilot |
| --- | --- | --- |
| Voice call state / deterministic disposition | `src/hermes_ultra/voice/model.py`, `policy.py`, `state_machine.py` | Existing |
| Consent-aware recovery | `src/hermes_ultra/voice/recovery.py`, `runtime.py` | Existing |
| Warm transfer | `src/hermes_ultra/voice/handoff.py`, `runtime.py` | Existing |
| Provider benchmark gate | `src/hermes_ultra/voice/benchmarks.py` | Existing |
| Economic ledger and business outcomes | `src/hermes_ultra/economic/ledger.py` | Existing |
| Consequential-action approval boundary | `src/hermes_ultra/autonomy.py` | Existing |
| Financial authority | `src/hermes_ultra/economic/authority.py` | Existing |
| Revenue execution security CI | `.github/workflows/revenue-execution-security-validate.yml` | Existing |

## Confirmed blockers

1. **Local working tree** — local Hermes host was not connected, so unpublished local state cannot be reconciled with remote HEAD.
2. **Actual pilot CRM/calendar** — no authoritative source named the exact CRM/calendar tenant or supplied authorized sandbox credentials. The live connector remains disabled.
3. **Live voice benchmark credentials/access** — no authorized provider credentials were available in the execution environment. Provider documentation was verified; measurements were not fabricated.
4. **Production launch** — intentionally not attempted. Production deployment, customer contact, payments, paid acquisition, or success-fee charging require separate explicit authorization.
