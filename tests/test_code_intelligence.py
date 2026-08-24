from __future__ import annotations

from types import SimpleNamespace

from hermes_ultra.code_intelligence import (
    CodeIntelligenceRouter,
    CodebaseMemoryAdapter,
    ImpactReport,
    NativeRepoSearchAdapter,
)
from hermes_ultra.contracts import CapabilityResult, FailureClass


class FakeProvider:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def impact_analysis(self, changed):
        self.calls.append(tuple(changed))
        return self.result


def test_primary_failure_uses_native_fallback():
    primary = FakeProvider(
        CapabilityResult.failure(
            FailureClass.UPSTREAM_UNAVAILABLE,
            "primary down",
            recoverable=True,
        )
    )
    fallback = FakeProvider(
        CapabilityResult.success(
            ImpactReport(provider="native-repo-search", changed=("src/app.py",))
        )
    )
    router = CodeIntelligenceRouter(primary=primary, fallback=fallback)

    result = router.impact_analysis(["src/app.py"])

    assert result.ok
    assert result.value.provider == "native-repo-search"
    assert result.value.degraded_context is True
    assert result.metadata["primary_failure"] == "UPSTREAM_UNAVAILABLE"


def test_primary_success_does_not_call_fallback():
    primary = FakeProvider(
        CapabilityResult.success(
            ImpactReport(provider="codebase-memory", changed=("src/app.py",))
        )
    )
    fallback = FakeProvider(CapabilityResult.success(ImpactReport(provider="native")))
    router = CodeIntelligenceRouter(primary=primary, fallback=fallback)

    result = router.impact_analysis(["src/app.py"])

    assert result.ok
    assert result.value.provider == "codebase-memory"
    assert fallback.calls == []


def test_codebase_memory_nonzero_is_recoverable_failure():
    def runner(cmd, **kwargs):
        return SimpleNamespace(returncode=3, stdout="", stderr="server unavailable")

    adapter = CodebaseMemoryAdapter(runner=runner)

    result = adapter.impact_analysis(["src/app.py"])

    assert not result.ok
    assert result.recoverable
    assert result.failure_class is FailureClass.UPSTREAM_UNAVAILABLE


def test_native_repo_search_returns_matches():
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="src/app.py:42:def target():\n", stderr="")

    adapter = NativeRepoSearchAdapter(repo_path="/repo", runner=runner)

    result = adapter.impact_analysis(["target"])

    assert result.ok
    assert result.value.provider == "native-repo-search"
    assert "src/app.py:42:def target():" in result.value.matches
    assert calls[0][:3] == ["git", "-C", "/repo"]
