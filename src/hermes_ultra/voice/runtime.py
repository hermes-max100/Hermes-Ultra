from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

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
