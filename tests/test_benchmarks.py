from __future__ import annotations

import json
from types import SimpleNamespace

from hermes_ultra.benchmarks import (
    BenchmarkCase,
    BenchmarkMetrics,
    BenchmarkObservation,
    BenchmarkReport,
    BenchmarkRunner,
    GraftAdapter,
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


def test_graft_native_cli_build_ask_and_check():
    calls = []

    def runner(cmd, **kwargs):
        calls.append((cmd, kwargs))
        payload = {"ok": True, "nodes": ["auth"]}
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    graft = GraftAdapter(runner=runner)

    build = graft.build("/repo")
    ask = graft.ask("find auth callers", "/repo")
    check = graft.check("/repo")

    assert build.ok and ask.ok and check.ok
    assert calls[0][0] == ["graft", "build", "/repo"]
    assert calls[1][0] == ["graft", "ask", "find auth callers", "/repo", "--json"]
    assert calls[2][0] == ["graft", "check", "/repo", "--json"]
    assert ask.value == {"ok": True, "nodes": ["auth"]}


def test_graft_callers_supports_inbound_and_outbound():
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    graft = GraftAdapter(runner=runner)

    inbound = graft.callers("Search", "/repo")
    outbound = graft.callers("Search", "/repo", direction="out")

    assert inbound.ok and outbound.ok
    assert calls[0] == ["graft", "callers", "Search", "/repo"]
    assert calls[1] == ["graft", "callers", "Search", "/repo", "--direction", "out"]


def test_benchmark_runner_runs_same_cases_across_all_three_providers():
    cases = (
        BenchmarkCase(name="single", task="find auth entry", repo_path="/repo"),
        BenchmarkCase(name="multi", task="trace auth impact", repo_path="/repo"),
    )
    calls = []

    def execute(provider, case):
        calls.append((provider, case.name, case.task, case.repo_path))
        efficiency = {"baseline": 12.0, "codebase-memory": 8.0, "graft": 6.0}[provider]
        return BenchmarkObservation(
            provider=provider,
            case=case.name,
            latency_seconds=efficiency,
            tool_calls=int(efficiency),
            tokens=int(efficiency * 100),
            success=True,
            tests_passed=True,
            wrong_file_edit=False,
            regression=False,
            evidence_complete=True,
        )

    report = BenchmarkRunner(execute).run(cases)

    assert len(calls) == 6
    assert {item[0] for item in calls} == {"baseline", "codebase-memory", "graft"}
    assert report.baseline.latency_seconds == 12.0
    assert report.codebase_memory.latency_seconds == 8.0
    assert report.graft.latency_seconds == 6.0
    assert report.graft.success_rate == 1.0


def test_benchmark_runner_aggregates_failure_rates():
    cases = (
        BenchmarkCase(name="a", task="a", repo_path="/repo"),
        BenchmarkCase(name="b", task="b", repo_path="/repo"),
    )

    def execute(provider, case):
        failed = provider == "graft" and case.name == "b"
        return BenchmarkObservation(
            provider=provider,
            case=case.name,
            latency_seconds=1.0,
            tool_calls=1,
            tokens=100,
            success=not failed,
            tests_passed=not failed,
            wrong_file_edit=failed,
            regression=failed,
            evidence_complete=True,
        )

    report = BenchmarkRunner(execute).run(cases)

    assert report.graft.success_rate == 0.5
    assert report.graft.tests_pass_rate == 0.5
    assert report.graft.wrong_file_edit_rate == 0.5
    assert report.graft.regression_rate == 0.5


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
