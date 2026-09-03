from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from ..economic.contracts import TreasuryBucket, as_decimal
from ..economic.ledger import EconomicLedger
from ..evidence import EvidenceEnvelope, EvidenceRecorder
from .model import CallContext, CallFacts, DispositionKind, VoiceDisposition
from .policy import VoicePolicyEngine
from .recovery import RecoveryPlan, RecoveryPlanner


@dataclass(frozen=True)
class VoiceRunResult:
    disposition: VoiceDisposition
    recovery_plan: RecoveryPlan | None
    evidence: dict[str, object]


class VoiceRevenueRuntime:
    """Joins deterministic voice policy to existing Hermes evidence and economics."""

    def __init__(
        self,
        *,
        policy: VoicePolicyEngine,
        evidence: EvidenceRecorder,
        ledger: EconomicLedger | None = None,
        strategy_id: str = "voice-revenue-recovery",
    ) -> None:
        self.policy = policy
        self.evidence = evidence
        self.ledger = ledger
        self.strategy_id = strategy_id
        self.recovery = RecoveryPlanner(policy.config)

    def finalize_call(self, context: CallContext, facts: CallFacts) -> VoiceRunResult:
        disposition = self.policy.evaluate(facts)
        plan = (
            self.recovery.build(context, facts, disposition)
            if disposition.kind is DispositionKind.INCOMPLETE_BUT_RECOVERABLE
            else None
        )
        if self.ledger is not None:
            if facts.qualified and disposition.kind is not DispositionKind.POLICY_BLOCKED:
                self.ledger.record_business_outcome(
                    run_id=context.run_id,
                    strategy_id=self.strategy_id,
                    outcome_type="qualified_lead",
                    currency=context.currency,
                    metadata={"call_id": context.call_id, "tenant_id": context.tenant_id},
                    idempotency_key=f"voice:{context.call_id}:qualified",
                )
            if disposition.kind is DispositionKind.BOOKED:
                self.ledger.record_business_outcome(
                    run_id=context.run_id,
                    strategy_id=self.strategy_id,
                    outcome_type="appointment_booked",
                    currency=context.currency,
                    metadata={
                        "call_id": context.call_id,
                        "tenant_id": context.tenant_id,
                        "recovered": False,
                    },
                    idempotency_key=f"voice:{context.call_id}:appointment",
                )

        envelope = EvidenceEnvelope.new(
            task_id=context.call_id,
            capability="voice-revenue-recovery",
            run_id=context.run_id,
        )
        artifact: dict[str, object] = {
            "call_id": context.call_id,
            "tenant_id": context.tenant_id,
            "disposition": disposition.kind.value,
            "reasons": disposition.reasons,
            "recovery_staged": plan is not None,
        }
        if plan is not None:
            artifact["recovery_idempotency_keys"] = [step.idempotency_key for step in plan.steps]
        envelope.artifacts.append(artifact)
        envelope.finish(status="success")
        recorded = self.evidence.record(envelope)
        return VoiceRunResult(disposition, plan, recorded)

    def record_recovered_booking(
        self,
        context: CallContext,
        plan: RecoveryPlan,
        *,
        booking_reference: str,
        now: datetime | None = None,
    ) -> dict[str, object]:
        if plan.call_id != context.call_id or plan.tenant_id != context.tenant_id:
            raise ValueError("recovery plan does not belong to this call")
        if not booking_reference.strip():
            raise ValueError("booking_reference is required")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if not plan.staged or current >= plan.expires_at:
            raise PermissionError("recovery plan is not active")
        if self.ledger is None:
            raise RuntimeError("an economic ledger is required for outcome attribution")
        self.ledger.record_business_outcome(
            run_id=context.run_id,
            strategy_id=self.strategy_id,
            outcome_type="appointment_booked",
            currency=context.currency,
            metadata={
                "call_id": context.call_id,
                "tenant_id": context.tenant_id,
                "booking_reference": booking_reference.strip(),
                "recovered": True,
                "recovery_attempt": plan.attempt,
            },
            idempotency_key=f"voice:{context.call_id}:recovered-appointment",
        )
        envelope = EvidenceEnvelope.new(
            task_id=context.call_id,
            capability="voice-recovery-attribution",
            run_id=context.run_id,
        )
        envelope.artifacts.append(
            {
                "call_id": context.call_id,
                "tenant_id": context.tenant_id,
                "booking_reference": booking_reference.strip(),
                "recovery_attempt": plan.attempt,
            }
        )
        envelope.finish(status="success")
        return self.evidence.record(envelope)

    def record_completed_job(
        self,
        context: CallContext,
        *,
        booking_reference: str,
        job_reference: str,
        attributed_revenue: Decimal | int | str,
        revenue_bucket: TreasuryBucket = TreasuryBucket.OPERATIONS,
    ) -> dict[str, object]:
        """Record a verified closed job and its attributable revenue exactly once.

        This completes the voice funnel without changing economic metric formulas.
        A closed job must trace to a previously recorded appointment for the call.
        Replays with identical evidence are idempotent; conflicting revenue replays
        fail closed instead of silently rewriting economic history.
        """
        if self.ledger is None:
            raise RuntimeError("an economic ledger is required for outcome attribution")
        booking = booking_reference.strip()
        job = job_reference.strip()
        if not booking or not job:
            raise ValueError("booking_reference and job_reference are required")
        revenue = as_decimal(attributed_revenue)
        if revenue <= 0:
            raise ValueError("attributed_revenue must be positive")

        appointments = [
            entry
            for entry in self.ledger.entries()
            if entry.run_id == context.run_id
            and entry.strategy_id == self.strategy_id
            and entry.kind == "business_outcome"
            and entry.status == "appointment_booked"
            and entry.metadata.get("call_id") == context.call_id
        ]
        if not appointments:
            raise PermissionError("a verified appointment is required before job completion")
        explicit_booking_refs = {
            str(entry.metadata.get("booking_reference"))
            for entry in appointments
            if entry.metadata.get("booking_reference") is not None
        }
        if explicit_booking_refs and booking not in explicit_booking_refs:
            raise PermissionError("booking_reference does not match the recorded appointment")

        completion_key = f"voice:{context.call_id}:job:{job}:completed"
        revenue_key = f"voice:{context.call_id}:job:{job}:revenue"
        prior_completion = self.ledger.find_event_by_key(
            f"business_outcome:completed_outcome:{completion_key}"
        )
        if prior_completion is not None:
            if (
                prior_completion.currency != context.currency
                or prior_completion.metadata.get("booking_reference") != booking
                or prior_completion.metadata.get("job_reference") != job
            ):
                raise ValueError("conflicting completed-job idempotent retry")
        prior_revenue = self.ledger.find_event_by_key(f"revenue:{revenue_key}")
        if prior_revenue is not None and (
            prior_revenue.amount != revenue or prior_revenue.currency != context.currency
        ):
            raise ValueError("conflicting revenue idempotent retry")

        self.ledger.record_business_outcome(
            run_id=context.run_id,
            strategy_id=self.strategy_id,
            outcome_type="completed_outcome",
            currency=context.currency,
            metadata={
                "call_id": context.call_id,
                "tenant_id": context.tenant_id,
                "booking_reference": booking,
                "job_reference": job,
            },
            idempotency_key=completion_key,
        )
        self.ledger.record_revenue(
            run_id=context.run_id,
            strategy_id=self.strategy_id,
            bucket=TreasuryBucket(revenue_bucket),
            amount=revenue,
            currency=context.currency,
            metadata={
                "call_id": context.call_id,
                "tenant_id": context.tenant_id,
                "booking_reference": booking,
                "job_reference": job,
                "attribution": "voice_completed_job",
            },
            idempotency_key=revenue_key,
        )

        envelope = EvidenceEnvelope.new(
            task_id=context.call_id,
            capability="voice-completed-outcome-attribution",
            run_id=context.run_id,
        )
        envelope.artifacts.append(
            {
                "call_id": context.call_id,
                "tenant_id": context.tenant_id,
                "booking_reference": booking,
                "job_reference": job,
                "attributed_revenue": str(revenue),
                "currency": context.currency,
                "revenue_bucket": TreasuryBucket(revenue_bucket).value,
            }
        )
        envelope.finish(status="success")
        return self.evidence.record(envelope)
