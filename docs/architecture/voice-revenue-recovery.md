# Voice Revenue Recovery

Hermes Ultra now has a provider-independent, deterministic foundation for the
home-services voice product. It turns a call into one of six business dispositions,
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
| Revenue Recovery | $749 | Receptionist plus incomplete-call recovery, CRM evidence, and outcome attribution |

No package can silently become unlimited. The factory requires positive included
minutes and an explicit overage rate.

## Call control

`VoiceCallStateMachine` owns legal lifecycle transitions and produces replayable
receipts. A provider may emit events, but it cannot skip disclosure, qualification,
or booking states. Invalid or tampered transitions fail closed.

`VoicePolicyEngine` applies this disposition precedence:

1. Missing disclosure blocks the workflow.
2. Emergency or caller-requested handoff routes to a human.
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
success, p95 latency, all-in cost per completed booking, and evidence completeness.
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

