from __future__ import annotations

import json

import pytest

from hermes_ultra.astra_route_benchmark import (
    BenchmarkManifest,
    BenchmarkPolicy,
    RunObservation,
    default_routes,
    evaluate_benchmark,
    task_fingerprint,
)


def observation(route: str, *, run_id: str, fingerprint: str, **overrides):
    values = dict(
        route=route,
        run_id=run_id,
        task_fingerprint=fingerprint,
        completion_quality=0.98,
        context_retention=0.98,
        browser_reliability=0.98,
        tool_reliability=0.98,
        latency_seconds=100.0,
        input_tokens=100_000,
        cache_write_tokens=0,
        cache_read_tokens=0,
        output_tokens=10_000,
        extra_cost_usd=0.0,
        audit_score=0.80 if route == "direct-astra" else 0.95,
        audit_evidence_complete=True,
        success=True,
        tests_passed=True,
        regression=False,
    )
    values.update(overrides)
    return RunObservation(**values)


def test_default_routes_are_benchmark_only_and_do_not_mutate_primary():
    routes = default_routes()
    assert set(routes) == {"direct-astra", "bedrock-astra-us"}
    assert routes["direct-astra"].model_id == "gpt-6-astra"
    assert routes["bedrock-astra-us"].model_id == "us.openai.gpt-6-astra"
    assert routes["bedrock-astra-us"].base_url == (
        "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1"
    )
    assert all(route.benchmark_only for route in routes.values())
    assert all(not route.primary_eligible for route in routes.values())


def test_effective_cost_uses_route_specific_short_context_pricing():
    routes = default_routes()
    fingerprint = task_fingerprint("abc", "task")
    direct = observation("direct-astra", run_id="d1", fingerprint=fingerprint)
    bedrock = observation("bedrock-astra-us", run_id="b1", fingerprint=fingerprint)

    assert routes["direct-astra"].pricing.cost(direct) == pytest.approx(1.50)
    assert routes["bedrock-astra-us"].pricing.cost(bedrock) == pytest.approx(1.65)


def test_long_context_pricing_switches_at_272k_input_tokens():
    routes = default_routes()
    fingerprint = task_fingerprint("abc", "task")
    direct = observation(
        "direct-astra",
        run_id="d1",
        fingerprint=fingerprint,
        input_tokens=300_000,
        output_tokens=10_000,
    )
    bedrock = observation(
        "bedrock-astra-us",
        run_id="b1",
        fingerprint=fingerprint,
        input_tokens=300_000,
        output_tokens=10_000,
    )

    assert routes["direct-astra"].pricing.cost(direct) == pytest.approx(6.75)
    assert routes["bedrock-astra-us"].pricing.cost(bedrock) == pytest.approx(7.425)


def test_benchmark_requires_identical_task_fingerprint_for_both_routes():
    manifest = BenchmarkManifest(base_sha="abc", task="same repo task")
    good = task_fingerprint(manifest.base_sha, manifest.task)
    observations = [
        observation("direct-astra", run_id="d1", fingerprint=good),
        observation("bedrock-astra-us", run_id="b1", fingerprint="wrong"),
    ]

    with pytest.raises(ValueError, match="task fingerprint"):
        evaluate_benchmark(manifest, observations, policy=BenchmarkPolicy(min_runs=1))


def test_bedrock_can_be_candidate_but_never_auto_promotes_or_changes_primary():
    manifest = BenchmarkManifest(base_sha="abc", task="same repo task")
    fingerprint = task_fingerprint(manifest.base_sha, manifest.task)
    observations = []
    for index in range(3):
        observations.append(
            observation(
                "direct-astra",
                run_id=f"d{index}",
                fingerprint=fingerprint,
                latency_seconds=100.0,
                audit_score=0.80,
            )
        )
        observations.append(
            observation(
                "bedrock-astra-us",
                run_id=f"b{index}",
                fingerprint=fingerprint,
                latency_seconds=105.0,
                audit_score=0.95,
            )
        )

    report = evaluate_benchmark(manifest, observations)

    assert report.decision.candidate is True
    assert report.decision.auto_promote is False
    assert report.decision.primary_route_changed is False
    assert report.decision.human_approval_required is True
    assert "auditability" in report.decision.reason


def test_missing_bedrock_audit_evidence_blocks_candidate():
    manifest = BenchmarkManifest(base_sha="abc", task="same repo task")
    fingerprint = task_fingerprint(manifest.base_sha, manifest.task)
    observations = []
    for index in range(3):
        observations.append(observation("direct-astra", run_id=f"d{index}", fingerprint=fingerprint))
        observations.append(
            observation(
                "bedrock-astra-us",
                run_id=f"b{index}",
                fingerprint=fingerprint,
                audit_evidence_complete=False,
            )
        )

    report = evaluate_benchmark(manifest, observations)

    assert report.decision.candidate is False
    assert "audit evidence" in report.decision.reason
    assert report.decision.primary_route_changed is False


def test_quality_or_reliability_regression_blocks_candidate():
    manifest = BenchmarkManifest(base_sha="abc", task="same repo task")
    fingerprint = task_fingerprint(manifest.base_sha, manifest.task)
    observations = []
    for index in range(3):
        observations.append(observation("direct-astra", run_id=f"d{index}", fingerprint=fingerprint))
        observations.append(
            observation(
                "bedrock-astra-us",
                run_id=f"b{index}",
                fingerprint=fingerprint,
                completion_quality=0.90,
                tool_reliability=0.90,
            )
        )

    report = evaluate_benchmark(manifest, observations)

    assert report.decision.candidate is False
    assert "quality" in report.decision.reason or "tool reliability" in report.decision.reason


def test_report_is_json_serializable_for_evidence_receipts():
    manifest = BenchmarkManifest(base_sha="abc", task="same repo task")
    fingerprint = task_fingerprint(manifest.base_sha, manifest.task)
    observations = []
    for index in range(3):
        observations.extend(
            [
                observation("direct-astra", run_id=f"d{index}", fingerprint=fingerprint),
                observation("bedrock-astra-us", run_id=f"b{index}", fingerprint=fingerprint),
            ]
        )

    report = evaluate_benchmark(manifest, observations)
    payload = report.to_dict()
    encoded = json.dumps(payload, sort_keys=True)

    assert '"primary_route_changed": false' in encoded
    assert payload["manifest"]["primary_route_change_allowed"] is False
