# Voice Revenue Recovery

Hermes Ultra now has a provider-independent, deterministic foundation for the
home-services voice product. It turns a call into a governed business disposition,
stages consent-aware recovery when a qualified call ends without a booking, and
records verified appointments in the existing Economic Ledger.

The package does not replace the Hermes router, invent approval categories, send a
message, or claim revenue from model output. Provider adapters and remote business
actions remain behind existing capability, delegated-identity, MCP, and autonomy
boundaries.

## Commercial contract

`home_services_offers(...)` preserves the two agreed price points while requiring
real usage limits and overage economics from the caller:

| Package | Monthly price | Core outcome |
| --- | ---: | --- |
| Receptionist | $499 | Answer, qualify, book, transfer |
| Revenue Recovery | $749 | Receptionist plus contextual warm transfer, failed-transfer and incomplete-call recovery, CRM evidence, and outcome attribution |

No package can silently become unlimited. The factory requires positive included
minutes and an explicit overage rate.

## Call control

`VoiceCallStateMachine` owns legal lifecycle transitions and produces replayable
receipts. A provider may emit events, but it cannot skip disclosure, qualification,
or booking states. Invalid or tampered transitions fail closed.

`VoicePolicyEngine` applies this disposition precedence:

1. Missing disclosure blocks the workflow.
2. Emergency or caller-requested handoff routes to a human. Revenue Recovery uses
   contextual warm transfer when a target is configured; Receptionist retains a
   normal transfer path.
3. Unsupported service or area is rejected.
4. A qualified, confirmed appointment is booked.
5. An incomplete call is recoverable only for the Revenue Recovery package when
   explicit consent, an opaque contact reference, an approved channel, and attempt
   capacity all exist.

## Recovery waterfall

`RecoveryPlanner` stages, but does not execute:

1. one consented SMS or email action using the configured channel order;
2. one CRM task carrying structured reasons;
3. one booking-verification action.

Every step has a deterministic idempotency key and a bounded expiry. Remote
execution must go through a `StagedBusinessActionBackend` and the existing Hermes
authority checks. Phone numbers and email addresses should remain in the provider or
CRM; the planner accepts an opaque contact reference.

## Escalation Assurance

`WarmTransferPlanner` stages a provider-independent two-step handoff:

1. initiate the transfer with a structured packet containing urgency,
   qualification, service-area context, actions already attempted, consent, and
   the requested next step;
2. wait for explicit human acceptance before disconnecting the AI.

The configured transfer target and contact reference stay in the provider-facing
staged action. Telemetry receives a PII-minimized packet without either reference.
An accepted handoff creates a `warm_transfer_accepted` business-outcome receipt. A
failed handoff can stage SMS or email recovery only when the same consent,
do-not-contact, channel, and attempt-limit checks used by incomplete-call recovery
pass. It never claims an appointment merely because a transfer was attempted.

The replayable lifecycle is:

`handoff -> transfer_connecting -> transfer_accepted -> ended`

or, on failure:

`handoff -> transfer_connecting -> transfer_failed -> incomplete -> ended`

## Field Voice Operations contract

`FieldVoicePlanner` turns one technician command into an ordered collection of
staged actions such as CRM updates, customer messages, job closure, follow-up
scheduling, part ordering, or a review request. It is an add-on/enterprise product
surface, not part of the free personal Jarvis assistant.

The planner fails closed in this order:

1. Missing job context or ambiguous intent returns `clarification_required` and
   stages no writes.
2. Consequential actions without an approval reference return
   `approval_required` and stage no writes.
3. Only an unambiguous, approved command returns ordered steps with deterministic
   idempotency keys.
4. Review requests additionally require verified job completion and payment.
5. An execution adapter must return a success receipt with an external reference,
   or a failure receipt with a reason.

The contract supports the reference journey:

`technician instruction -> clarification -> approval -> CRM update -> customer message -> receipts`

## Evidence and economics

`VoiceRevenueRuntime.finalize_call(...)` records:

- the deterministic disposition and reason codes;
- whether recovery was staged;
- qualified leads and directly booked appointments in `EconomicLedger`;
- redacted Hermes `EvidenceEnvelope` records.

`record_recovered_booking(...)` records a recovered appointment separately, so
recovery conversion can be measured without inflating direct-booking performance.
Closed-job revenue still enters through the Economic Engine's authorized revenue
path.

## Provider promotion

`VoiceReleaseGate` compares a candidate with the production baseline using completed
bookings, critical-field accuracy, handoff correctness, policy violations, recovery
success, transfer acceptance, interruption recovery, end-of-turn confidence, PII
redaction, p95 latency, all-in cost per completed booking, and evidence completeness.
Low token or per-minute cost alone cannot promote a provider.

Recommended replay cases include English/Spanish code-switching, names, street
addresses, postal codes, appointment times, trade vocabulary, noisy callers,
interruptions, changed intent, emergency phrases, out-of-area calls, and missing
follow-up consent.

## Minimal use

```python
from hermes_ultra.economic import EconomicLedger
from hermes_ultra.evidence import EvidenceRecorder
from hermes_ultra.voice import (
    CallContext,
    CallFacts,
    ContactChannel,
    VoicePackage,
    VoicePolicyConfig,
    VoicePolicyEngine,
    VoiceRevenueRuntime,
)

config = VoicePolicyConfig(
    package=VoicePackage.REVENUE_RECOVERY,
    supported_postal_codes=frozenset({"90210"}),
    allowed_services=frozenset({"plumbing"}),
    warm_transfer_target_reference="on-call-dispatch",
    secondary_languages=("es",),
)

with EconomicLedger("voice.sqlite3") as ledger:
    runtime = VoiceRevenueRuntime(
        policy=VoicePolicyEngine(config),
        evidence=EvidenceRecorder(),
        ledger=ledger,
    )
    result = runtime.finalize_call(
        CallContext(call_id="call-1", run_id="run-1", tenant_id="tenant-1"),
        CallFacts(
            disclosure_complete=True,
            requested_service="plumbing",
            postal_code="90210",
            qualified=True,
            ended_before_booking=True,
            follow_up_consent=True,
            contact_reference="crm-contact-1",
            contact_channels=frozenset({ContactChannel.SMS}),
        ),
    )
```
