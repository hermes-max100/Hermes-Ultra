from __future__ import annotations

import json
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


def test_codebase_memory_uses_native_cli_index_contract():
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True}), stderr="")

    adapter = CodebaseMemoryAdapter(repo_path="/repo", project="repo", runner=runner)

    result = adapter.index_repository()

    assert result.ok
    assert calls[0] == [
        "codebase-memory-mcp",
        "cli",
        "--json",
        "index_repository",
        "--repo-path",
        "/repo",
    ]


def test_codebase_memory_symbol_and_trace_commands_match_upstream_cli():
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"results": []}), stderr="")

    adapter = CodebaseMemoryAdapter(repo_path="/repo", project="my-project", runner=runner)

    adapter.lookup_symbol("Search")
    adapter.find_callers("Search")
    adapter.find_dependencies("Search")
    adapter.find_routes("users")

    assert calls[0] == [
        "codebase-memory-mcp", "cli", "--json", "search_graph",
        "--project", "my-project", "--name-pattern", "Search", "--label", "Function",
    ]
    assert calls[1] == [
        "codebase-memory-mcp", "cli", "--json", "trace_path",
        "--project", "my-project", "--function-name", "Search", "--direction", "in",
    ]
    assert calls[2] == [
        "codebase-memory-mcp", "cli", "--json", "trace_path",
        "--project", "my-project", "--function-name", "Search", "--direction", "out",
    ]
    assert calls[3] == [
        "codebase-memory-mcp", "cli", "--json", "search_graph",
        "--project", "my-project", "--name-pattern", "users", "--label", "Route",
    ]


def test_codebase_memory_impact_uses_detect_changes_and_parses_json():
    calls = []
    payload = {"risk": "medium", "affected_symbols": ["Search", "Router"]}

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    adapter = CodebaseMemoryAdapter(repo_path="/repo", project="my-project", runner=runner)

    result = adapter.impact_analysis(["src/app.py"])

    assert result.ok
    assert result.value.provider == "codebase-memory"
    assert result.value.changed == ("src/app.py",)
    assert result.value.payload == payload
    assert calls[0] == [
        "codebase-memory-mcp", "cli", "--json", "detect_changes",
        "--project", "my-project",
    ]


def test_codebase_memory_nonzero_is_recoverable_failure():
    def runner(cmd, **kwargs):
        return SimpleNamespace(returncode=3, stdout="", stderr="server unavailable")

    adapter = CodebaseMemoryAdapter(project="repo", runner=runner)

    result = adapter.impact_analysis(["src/app.py"])

    assert not result.ok
    assert result.recoverable
    assert result.failure_class is FailureClass.UPSTREAM_UNAVAILABLE


def test_codebase_memory_malformed_json_is_recoverable_failure():
    def runner(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout="not-json", stderr="")

    adapter = CodebaseMemoryAdapter(project="repo", runner=runner)

    result = adapter.lookup_symbol("Search")

    assert not result.ok
    assert result.recoverable
    assert result.failure_class is FailureClass.EVIDENCE_INCOMPLETE


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
