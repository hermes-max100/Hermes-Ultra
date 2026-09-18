from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import ceil
from statistics import median
from typing import Iterable


@dataclass(frozen=True)
class ReplayCase:
    case_id: str
    language_profile: str
    noise_profile: str
    required_fields: tuple[str, ...]
    requires_transfer: bool = False
    has_interruption: bool = False
    has_correction: bool = False


@dataclass(frozen=True)
class BookingBenchmarkObservation:
    provider: str
    case_id: str
    measured_live: bool
    booking_completed_correctly: bool
    critical_fields_correct: int
    critical_fields_total: int
    unauthorized_tool_actions: int
    response_latency_ms: int
    transfer_required: bool
    transfer_succeeded: bool
    human_correction_seconds: int
    provider_cost_usd: Decimal
    human_review_cost_usd: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_cost_usd", Decimal(str(self.provider_cost_usd)))
        object.__setattr__(self, "human_review_cost_usd", Decimal(str(self.human_review_cost_usd)))
        if self.critical_fields_total <= 0:
            raise ValueError("critical_fields_total must be positive")
        if not 0 <= self.critical_fields_correct <= self.critical_fields_total:
            raise ValueError("invalid critical field counts")
        if min(self.unauthorized_tool_actions, self.response_latency_ms, self.human_correction_seconds) < 0:
            raise ValueError("counts and latency cannot be negative")
        if self.provider_cost_usd < 0 or self.human_review_cost_usd < 0:
            raise ValueError("costs cannot be negative")


@dataclass(frozen=True)
class BookingBenchmarkMetrics:
    provider: str
    observations: int
    all_measured_live: bool
    correctly_completed_bookings: int
    critical_field_accuracy: Decimal
    unauthorized_tool_actions: int
    median_latency_ms: Decimal
    p95_latency_ms: int
    transfer_success_rate: Decimal | None
    total_human_correction_seconds: int
    fully_loaded_cost_per_correct_booking: Decimal | None


def aggregate_booking_benchmark(observations: Iterable[BookingBenchmarkObservation]) -> BookingBenchmarkMetrics:
    rows = tuple(observations)
    if not rows:
        raise ValueError("at least one observation is required")
    providers = {row.provider for row in rows}
    if len(providers) != 1:
        raise ValueError("aggregate one provider at a time")
    completed = sum(row.booking_completed_correctly for row in rows)
    correct_fields = sum(row.critical_fields_correct for row in rows)
    total_fields = sum(row.critical_fields_total for row in rows)
    latencies = sorted(row.response_latency_ms for row in rows)
    p95_index = max(0, ceil(0.95 * len(latencies)) - 1)
    transfer_rows = [row for row in rows if row.transfer_required]
    total_cost = sum((row.provider_cost_usd + row.human_review_cost_usd for row in rows), Decimal("0"))
    return BookingBenchmarkMetrics(provider=rows[0].provider, observations=len(rows), all_measured_live=all(row.measured_live for row in rows), correctly_completed_bookings=completed, critical_field_accuracy=Decimal(correct_fields) / Decimal(total_fields), unauthorized_tool_actions=sum(row.unauthorized_tool_actions for row in rows), median_latency_ms=Decimal(str(median(latencies))), p95_latency_ms=latencies[p95_index], transfer_success_rate=None if not transfer_rows else Decimal(sum(row.transfer_succeeded for row in transfer_rows)) / Decimal(len(transfer_rows)), total_human_correction_seconds=sum(row.human_correction_seconds for row in rows), fully_loaded_cost_per_correct_booking=None if completed == 0 else total_cost / Decimal(completed))


def default_replay_corpus() -> tuple[ReplayCase, ...]:
    """Scenario metadata only; no synthetic score is presented as provider measurement."""
    return (
        ReplayCase("noisy-en-address", "en-US", "telephone-noisy", ("name", "phone", "street", "zip", "date")),
        ReplayCase("spanish-accent-zip", "es-US", "telephone", ("name", "phone", "zip", "service")),
        ReplayCase("equipment-id", "en-US", "telephone", ("equipment_id", "model", "service")),
        ReplayCase("short-confirmation", "en-US", "telephone", ("appointment_time",), has_correction=True),
        ReplayCase("interruption-correction", "en-US", "telephone-noisy", ("phone", "date"), has_interruption=True, has_correction=True),
        ReplayCase("failed-transfer", "en-US", "telephone", ("service", "urgency"), requires_transfer=True),
    )
