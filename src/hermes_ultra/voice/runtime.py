from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from ..economic.ledger import EconomicLedger
from ..evidence import EvidenceEnvelope, EvidenceRecorder
from .handoff import (
    WarmTransferPlan,
    WarmTransferPlanner,
    WarmTransferReceipt,
    WarmTransferStatus,
)
from .model import CallContext, CallFacts, DispositionKind, VoiceDisposition
from .policy import VoicePolicyEngine
from .recovery import RecoveryPlan, RecoveryPlanner


@dataclass(frozen=True)
class VoiceRunResult:
    disposition: VoiceDisposition
    recovery_plan: RecoveryPlan | None
    warm_transfer_plan: WarmTransferPlan | None
    evidence: dict[str, object]


@dataclass(frozen=True)
class WarmTransferRunResult:
    receipt: WarmTransferReceipt
    failed_transfer_recovery_plan: RecoveryPlan | None
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
        self.warm_transfer = WarmTransferPlanner(policy.config)

    def finalize_call(self, context: CallContext, facts: CallFacts) -> VoiceRunResult:
        disposition = self.policy.evaluate(facts)
        plan = (
            self.recovery.build(context, facts, disposition)
            if disposition.kind is DispositionKind.INCOMPLETE_BUT_RECOVERABLE
            else None
        )
        transfer_plan = (
            self.warm_transfer.build(context, facts, disposition)
            if disposition.kind is DispositionKind.WARM_TRANSFER_REQUIRED
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
            "warm_transfer_staged": transfer_plan is not None,
        }
        if plan is not None:
            artifact["recovery_idempotency_keys"] = [step.idempotency_key for step in plan.steps]
        if transfer_plan is not None:
            artifact["warm_transfer_idempotency_keys"] = [
                step.idempotency_key for step in transfer_plan.steps
            ]
            artifact["warm_transfer_packet"] = dict(
                transfer_plan.packet.telemetry_payload()
            )
        envelope.artifacts.append(artifact)
        envelope.finish(status="success")
        recorded = self.evidence.record(envelope)
        return VoiceRunResult(disposition, plan, transfer_plan, recorded)

    def record_warm_transfer_result(
        self,
        context: CallContext,
        plan: WarmTransferPlan,
        facts: CallFacts,
        *,
        accepted: bool,
        human_reference: str | None = None,
        failure_reason: str | None = None,
        now: datetime | None = None,
    ) -> WarmTransferRunResult:
        if plan.call_id != context.call_id or plan.tenant_id != context.tenant_id:
            raise ValueError("warm transfer plan does not belong to this call")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if not plan.staged or current >= plan.expires_at:
            raise PermissionError("warm transfer plan is not active")
        status = WarmTransferStatus.ACCEPTED if accepted else WarmTransferStatus.FAILED
        receipt = WarmTransferReceipt(
            call_id=context.call_id,
            tenant_id=context.tenant_id,
            status=status,
            recorded_at=current,
            human_reference=human_reference,
            failure_reason=failure_reason,
        )
        recovery_plan = None
        if accepted:
            if self.ledger is not None:
                self.ledger.record_business_outcome(
                    run_id=context.run_id,
                    strategy_id=self.strategy_id,
                    outcome_type="warm_transfer_accepted",
                    currency=context.currency,
                    metadata={
                        "call_id": context.call_id,
                        "tenant_id": context.tenant_id,
                        "human_reference": human_reference,
                    },
                    idempotency_key=f"voice:{context.call_id}:warm-transfer-accepted",
                )
        else:
            recovery_facts = replace(
                facts,
                emergency_detected=False,
                handoff_requested=False,
                appointment_booked=False,
                ended_before_booking=True,
            )
            recovery_disposition = self.policy.evaluate(recovery_facts)
            if recovery_disposition.kind is DispositionKind.INCOMPLETE_BUT_RECOVERABLE:
                recovery_plan = self.recovery.build(
                    context,
                    recovery_facts,
                    recovery_disposition,
                    now=current,
                    source="failed_warm_transfer",
                )

        envelope = EvidenceEnvelope.new(
            task_id=context.call_id,
            capability="voice-warm-transfer",
            run_id=context.run_id,
        )
        envelope.artifacts.append(
            {
                "call_id": context.call_id,
                "tenant_id": context.tenant_id,
                "status": receipt.status.value,
                "human_reference": receipt.human_reference,
                "failure_reason": receipt.failure_reason,
                "failed_transfer_recovery_staged": recovery_plan is not None,
                "transfer_packet": dict(plan.packet.telemetry_payload()),
            }
        )
        envelope.finish(
            status="success" if accepted else "failed",
            failure_class=failure_reason,
        )
        recorded = self.evidence.record(envelope)
        return WarmTransferRunResult(receipt, recovery_plan, recorded)

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
                "recovery_source": plan.source,
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
                "recovery_source": plan.source,
            }
        )
        envelope.finish(status="success")
        return self.evidence.record(envelope)
