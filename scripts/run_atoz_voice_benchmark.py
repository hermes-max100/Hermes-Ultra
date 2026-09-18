#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from hermes_ultra.atoz.benchmark import BookingBenchmarkObservation, aggregate_booking_benchmark, default_replay_corpus


def load_observations(path: Path) -> list[BookingBenchmarkObservation]:
    raw = json.loads(path.read_text())
    return [BookingBenchmarkObservation(provider=row["provider"], case_id=row["case_id"], measured_live=bool(row["measured_live"]), booking_completed_correctly=bool(row["booking_completed_correctly"]), critical_fields_correct=int(row["critical_fields_correct"]), critical_fields_total=int(row["critical_fields_total"]), unauthorized_tool_actions=int(row["unauthorized_tool_actions"]), response_latency_ms=int(row["response_latency_ms"]), transfer_required=bool(row["transfer_required"]), transfer_succeeded=bool(row["transfer_succeeded"]), human_correction_seconds=int(row["human_correction_seconds"]), provider_cost_usd=Decimal(str(row["provider_cost_usd"])), human_review_cost_usd=Decimal(str(row.get("human_review_cost_usd", "0")))) for row in raw]


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate AtoZ voice benchmark observations without inventing provider measurements.")
    parser.add_argument("--observations", type=Path); parser.add_argument("--show-corpus", action="store_true"); args = parser.parse_args()
    if args.show_corpus:
        print(json.dumps([case.__dict__ for case in default_replay_corpus()], indent=2))
        if args.observations is None: return 0
    if args.observations is None: parser.error("--observations is required unless --show-corpus is used")
    metrics = aggregate_booking_benchmark(load_observations(args.observations))
    payload = {"provider": metrics.provider, "observations": metrics.observations, "all_measured_live": metrics.all_measured_live, "correctly_completed_bookings": metrics.correctly_completed_bookings, "critical_field_accuracy": str(metrics.critical_field_accuracy), "unauthorized_tool_actions": metrics.unauthorized_tool_actions, "median_latency_ms": str(metrics.median_latency_ms), "p95_latency_ms": metrics.p95_latency_ms, "transfer_success_rate": None if metrics.transfer_success_rate is None else str(metrics.transfer_success_rate), "total_human_correction_seconds": metrics.total_human_correction_seconds, "fully_loaded_cost_per_correct_booking": None if metrics.fully_loaded_cost_per_correct_booking is None else str(metrics.fully_loaded_cost_per_correct_booking)}
    print(json.dumps(payload, indent=2))
    if not metrics.all_measured_live: print("NOTICE: observations include non-live fixtures; output is harness validation, not a measured provider recommendation.")
    return 0


if __name__ == "__main__": raise SystemExit(main())
