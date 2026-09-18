# AtoZ Containment and Recovery Evidence — 2026-09-17

This report separates **observed implementation evidence** from **unverified live-host claims**.

## Observed in controlled execution

The AtoZ regression suite exercises the following failure cases with synthetic data and controlled endpoints:

| Test condition | Expected boundary | Evidence surface |
| --- | --- | --- |
| Cross-tenant RecoveryCase mutation | Fail before database state change | `RecoveryCaseStore.append_event` + regression test |
| Cross-tenant tool action | Fail before dispatch | `ExecutionPolicyGateway.begin_dispatch` + regression test |
| Host-credential data tag | Fail before dispatch | `DataHandlingPolicy` + regression test |
| Unclassified data tag | Fail before dispatch | `DataHandlingPolicy` |
| Missing permission | Fail before dispatch | `AgentIdentity.permissions` |
| Budget exhaustion | Fail before dispatch | `SpendPolicy`; idempotent replay does not spend twice |
| Global pause | Blocks new dispatches | gateway state test |
| Run cancellation | Blocks queued/new actions | gateway state test |
| Agent revocation | Blocks subsequent actions | gateway state test |
| Consequential/publication-shaped action | Delegates to Hermes `ApprovalRegistry` and fails closed without authority | gateway regression test |
| External response lost after commit | Mark ambiguous; reconcile by idempotency key before retry | `ContractTestCrmCalendarAdapter` + test |
| Duplicate RecoveryCase event | Identical replay is a no-op; conflicting reuse fails | durable event hash/idempotency test |
| Refund / duplicate / open dispute | Excluded from billable outcome | billable-outcome tests |
| Uncertain visual equipment identity | Requires human confirmation | visual packet test |

The controlled connector deliberately distinguishes these execution states: blocked before dispatch, dispatched, external accepted, reconciliation required, and compensation required. Pause/cancel does **not** claim to undo a side effect already accepted by an external service.

## Evidence not available in this run

The following completion evidence remains unavailable and is therefore **not claimed**:

1. Live Hermes tool-gateway/job-runner binding of the AtoZ policy module.
2. Host process/network observations showing scope-escape attempts blocked at the actual runtime boundary.
3. Credential-isolation evidence from the actual Hermes host filesystem/process environment.
4. Actual CRM/calendar sandbox writes and reconciliation receipts.
5. Live provider voice replay results and provider-side usage/cost receipts.
6. Post-cancellation observation of a real queued/external action on the production-shaped runtime.

Reason: the authorized Remote Desktop Commander endpoint reported no connected host, and no live pilot CRM/calendar or provider credentials were available in this execution context.

## Unresolved findings register

| Finding | Severity | Status | Required cure/evidence |
| --- | --- | --- | --- |
| Live policy binding not observed | High | OPEN | Connect Hermes host; bind AtoZ gateway at authoritative dispatch boundary; rerun tenant/budget/data/revoke/pause tests there. |
| Network containment not observed | High | OPEN | Run controlled forbidden egress/scope-escape tests and preserve gateway/network receipts. |
| Credential isolation not observed | High | OPEN | Verify runtime cannot read host credentials outside delegated references; preserve audit output. |
| Actual CRM/calendar unspecified | High | OPEN | Name system, configure authorized sandbox tenant, map IDs, inject response-loss-after-commit, reconcile exactly once. |
| Live voice benchmark unavailable | Medium | OPEN | Supply authorized provider access; run identical replay corpus; preserve raw measurement receipts. |
| Global pause cannot reverse accepted external actions | Expected constraint | DOCUMENTED | Reconciliation/compensation path is the required handling; do not describe pause as reversal. |

## Promotion gate

P1-6 and P1-7 remain BLOCKED until the live-host evidence above exists. The controlled implementation is suitable for continued reversible development and CI, not for representing production containment as proven.
