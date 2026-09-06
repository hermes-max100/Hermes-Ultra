from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import ceil
from typing import Iterable, Sequence


@dataclass(frozen=True)
class VoiceBenchmarkObservation:
    provider: str
    case: str
    booking_completed: bool
    critical_fields_correct: bool
    handoff_correct: bool
    policy_violation: bool
    recovery_attempted: bool
    recovery_succeeded: bool
    latency_ms: int
    cost_usd: Decimal
    evidence_complete: bool
    transfer_attempted: bool = False
    transfer_accepted: bool = False
    interruption_recovered: bool = True
    end_of_turn_confidence: Decimal | None = None
    pii_redaction_complete: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "cost_usd", Decimal(str(self.cost_usd)))
        if self.end_of_turn_confidence is not None:
            object.__setattr__(
                self,
                "end_of_turn_confidence",
                Decimal(str(self.end_of_turn_confidence)),
            )
        if self.latency_ms < 0 or self.cost_usd < 0:
            raise ValueError("latency and cost cannot be negative")
        if self.recovery_succeeded and not self.recovery_attempted:
            raise ValueError("recovery success requires a recovery attempt")
        if self.transfer_accepted and not self.transfer_attempted:
            raise ValueError("transfer acceptance requires a transfer attempt")
        if self.end_of_turn_confidence is not None and not (
            Decimal("0") <= self.end_of_turn_confidence <= Decimal("1")
        ):
            raise ValueError("end_of_turn_confidence must be between 0 and 1")


@dataclass(frozen=True)
class VoiceBenchmarkMetrics:
    cases: int
    booking_completion_rate: Decimal
    critical_field_accuracy: Decimal
    handoff_accuracy: Decimal
    policy_violations: int
    recovery_success_rate: Decimal | None
    p95_latency_ms: int
    cost_per_completed_booking: Decimal | None
    evidence_complete: bool
    transfer_acceptance_rate: Decimal | None
    interruption_recovery_rate: Decimal
    mean_end_of_turn_confidence: Decimal | None
    pii_redaction_complete: bool


@dataclass(frozen=True)
class VoicePromotionDecision:
    promoted: bool
    reason: str


def _rate(numerator: int, denominator: int) -> Decimal:
    return Decimal(numerator) / Decimal(denominator)


def aggregate_voice_benchmark(
    observations: Iterable[VoiceBenchmarkObservation],
) -> VoiceBenchmarkMetrics:
    rows: Sequence[VoiceBenchmarkObservation] = tuple(observations)
    if not rows:
        raise ValueError("at least one voice benchmark observation is required")
    count = len(rows)
    completed = sum(item.booking_completed for item in rows)
    recovery_attempts = sum(item.recovery_attempted for item in rows)
    recovery_successes = sum(item.recovery_succeeded for item in rows)
    transfer_attempts = sum(item.transfer_attempted for item in rows)
    transfer_acceptances = sum(item.transfer_accepted for item in rows)
    confidence_rows = [
        item.end_of_turn_confidence
        for item in rows
        if item.end_of_turn_confidence is not None
    ]
    latencies = sorted(item.latency_ms for item in rows)
    p95_index = max(0, ceil(0.95 * count) - 1)
    total_cost = sum((item.cost_usd for item in rows), Decimal("0"))
    return VoiceBenchmarkMetrics(
        cases=count,
        booking_completion_rate=_rate(completed, count),
        critical_field_accuracy=_rate(sum(item.critical_fields_correct for item in rows), count),
        handoff_accuracy=_rate(sum(item.handoff_correct for item in rows), count),
        policy_violations=sum(item.policy_violation for item in rows),
        recovery_success_rate=(
            None if recovery_attempts == 0 else _rate(recovery_successes, recovery_attempts)
        ),
        p95_latency_ms=latencies[p95_index],
        cost_per_completed_booking=(None if completed == 0 else total_cost / completed),
        evidence_complete=all(item.evidence_complete for item in rows),
        transfer_acceptance_rate=(
            None if transfer_attempts == 0 else _rate(transfer_acceptances, transfer_attempts)
        ),
        interruption_recovery_rate=_rate(
            sum(item.interruption_recovered for item in rows), count
        ),
        mean_end_of_turn_confidence=(
            None
            if not confidence_rows
            else sum(confidence_rows, Decimal("0")) / len(confidence_rows)
        ),
        pii_redaction_complete=all(item.pii_redaction_complete for item in rows),
    )


class VoiceReleaseGate:
    """Promotes providers on completed outcomes, safety, evidence, latency, and cost."""

    def __init__(
        self,
        *,
        minimum_cases: int = 20,
        max_p95_latency_ms: int = 1200,
        max_cost_per_completed_booking: Decimal | str = Decimal("25"),
        minimum_end_of_turn_confidence: Decimal | str = Decimal("0.65"),
    ) -> None:
        if minimum_cases <= 0 or max_p95_latency_ms <= 0:
            raise ValueError("case and latency thresholds must be positive")
        self.minimum_cases = minimum_cases
        self.max_p95_latency_ms = max_p95_latency_ms
        self.max_cost_per_completed_booking = Decimal(str(max_cost_per_completed_booking))
        self.minimum_end_of_turn_confidence = Decimal(str(minimum_end_of_turn_confidence))
        if self.max_cost_per_completed_booking < 0:
            raise ValueError("cost threshold cannot be negative")
        if not Decimal("0") <= self.minimum_end_of_turn_confidence <= Decimal("1"):
            raise ValueError("end-of-turn threshold must be between 0 and 1")

    def evaluate(
        self,
        baseline: VoiceBenchmarkMetrics,
        candidate: VoiceBenchmarkMetrics,
    ) -> VoicePromotionDecision:
        failures = []
        if candidate.cases < self.minimum_cases:
            failures.append("insufficient_cases")
        if candidate.policy_violations:
            failures.append("policy_violation")
        if not candidate.evidence_complete:
            failures.append("evidence_incomplete")
        if not candidate.pii_redaction_complete:
            failures.append("pii_redaction_incomplete")
        if candidate.booking_completion_rate < baseline.booking_completion_rate:
            failures.append("booking_completion_regression")
        if candidate.critical_field_accuracy < baseline.critical_field_accuracy:
            failures.append("critical_field_regression")
        if candidate.handoff_accuracy < baseline.handoff_accuracy:
            failures.append("handoff_regression")
        if candidate.interruption_recovery_rate < baseline.interruption_recovery_rate:
            failures.append("interruption_recovery_regression")
        if baseline.transfer_acceptance_rate is not None:
            if candidate.transfer_acceptance_rate is None:
                failures.append("transfer_acceptance_evidence_unavailable")
            elif candidate.transfer_acceptance_rate < baseline.transfer_acceptance_rate:
                failures.append("transfer_acceptance_regression")
        if (
            candidate.mean_end_of_turn_confidence is not None
            and candidate.mean_end_of_turn_confidence < self.minimum_end_of_turn_confidence
        ):
            failures.append("end_of_turn_confidence_below_limit")
        if candidate.p95_latency_ms > self.max_p95_latency_ms:
            failures.append("latency_above_limit")
        if candidate.cost_per_completed_booking is None:
            failures.append("completed_booking_cost_unavailable")
        elif candidate.cost_per_completed_booking > self.max_cost_per_completed_booking:
            failures.append("completed_booking_cost_above_limit")
        if baseline.recovery_success_rate is not None:
            if candidate.recovery_success_rate is None:
                failures.append("recovery_evidence_unavailable")
            elif candidate.recovery_success_rate < baseline.recovery_success_rate:
                failures.append("recovery_success_regression")
        return VoicePromotionDecision(not failures, "promoted" if not failures else ",".join(failures))
