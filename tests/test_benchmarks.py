from __future__ import annotations

from hermes_ultra.benchmarks import (
    BenchmarkMetrics,
    BenchmarkReport,
    PromotionPolicy,
    ProviderRegistry,
)


def metrics(**overrides):
    values = dict(
        latency_seconds=10.0,
        tool_calls=10,
        tokens=1000,
        success_rate=1.0,
        tests_pass_rate=1.0,
        wrong_file_edit_rate=0.0,
        regression_rate=0.0,
        evidence_complete=True,
    )
    values.update(overrides)
    return BenchmarkMetrics(**values)


def test_graft_not_promoted_when_success_regresses():
    registry = ProviderRegistry(current="codebase-memory")
    policy = PromotionPolicy(min_success_rate=0.95)
    report = BenchmarkReport(
        baseline=metrics(),
        codebase_memory=metrics(),
        graft=metrics(success_rate=0.80),
    )

    decision = policy.evaluate_and_promote(report, registry)

    assert decision.promoted is False
    assert registry.current == "codebase-memory"
    assert "success_rate" in decision.reason


def test_graft_not_promoted_when_evidence_incomplete():
    registry = ProviderRegistry(current="codebase-memory")
    policy = PromotionPolicy()
    report = BenchmarkReport(
        baseline=metrics(),
        codebase_memory=metrics(),
        graft=metrics(evidence_complete=False),
    )

    decision = policy.evaluate_and_promote(report, registry)

    assert decision.promoted is False
    assert registry.current == "codebase-memory"


def test_graft_auto_promotes_when_thresholds_pass():
    registry = ProviderRegistry(current="codebase-memory")
    policy = PromotionPolicy(min_success_rate=0.95, max_regression_rate=0.0)
    report = BenchmarkReport(
        baseline=metrics(latency_seconds=12.0, tool_calls=12),
        codebase_memory=metrics(latency_seconds=10.0, tool_calls=10),
        graft=metrics(latency_seconds=8.0, tool_calls=8),
    )

    decision = policy.evaluate_and_promote(report, registry)

    assert decision.promoted is True
    assert decision.human_approval_required is False
    assert registry.current == "graft"
    assert registry.previous == "codebase-memory"


def test_promotion_is_reversible():
    registry = ProviderRegistry(current="codebase-memory")
    registry.promote("graft")

    restored = registry.rollback()

    assert restored == "codebase-memory"
    assert registry.current == "codebase-memory"


def test_wrong_file_edits_block_promotion():
    registry = ProviderRegistry(current="codebase-memory")
    policy = PromotionPolicy(max_wrong_file_edit_rate=0.0)
    report = BenchmarkReport(
        baseline=metrics(),
        codebase_memory=metrics(),
        graft=metrics(wrong_file_edit_rate=0.1),
    )

    decision = policy.evaluate_and_promote(report, registry)

    assert decision.promoted is False
    assert "wrong_file_edit_rate" in decision.reason
