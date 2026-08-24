from __future__ import annotations

from dataclasses import dataclass

from hermes_ultra.autonomy import ApprovalRegistry
from hermes_ultra.code_intelligence import CodeIntelligenceRouter, ImpactReport
from hermes_ultra.contracts import CapabilityResult, FailureClass
from hermes_ultra.evidence import EvidenceRecorder
from hermes_ultra.orchestrator import HermesUltraOrchestrator
from hermes_ultra.swarm import CandidateVerifier, WorkerOutcome


class Provider:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def impact_analysis(self, changed):
        self.calls += 1
        if len(self.results) == 1:
            return self.results[0]
        return self.results.pop(0)


class Worker:
    def __init__(self, result):
        self.result = result
        self.assignments = []

    def execute(self, assignment):
        self.assignments.append(assignment)
        return self.result


class ResearchAdapter:
    def __init__(self, result):
        self.result = result
        self.routes = []

    def execute_with_fallback(self, routes):
        self.routes.append(routes)
        return self.result


@dataclass(frozen=True)
class ResearchValue:
    stdout: str


def make_worker_success():
    return CapabilityResult.success(
        WorkerOutcome(
            task_id="task-1",
            worker="codex",
            worktree_path="/tmp/wt",
            returncode=0,
            stdout="done",
            stderr="",
        )
    )


def test_coding_task_auto_promotes_when_verified():
    primary = Provider(
        [CapabilityResult.success(ImpactReport(provider="codebase-memory"))]
    )
    fallback = Provider(
        [CapabilityResult.success(ImpactReport(provider="native-repo-search"))]
    )
    router = CodeIntelligenceRouter(primary=primary, fallback=fallback)
    worker = Worker(make_worker_success())
    recorder = EvidenceRecorder()
    orchestrator = HermesUltraOrchestrator(
        code_intelligence=router,
        worker_executor=worker,
        candidate_verifier=CandidateVerifier(ApprovalRegistry({"production_deploy"})),
        evidence_recorder=recorder,
    )

    result = orchestrator.run_coding_task(
        task_id="task-1",
        changed=("src/app.py",),
        worker="codex",
        repo_path="/repo",
        base_sha="abc",
        worktree_path="/tmp/wt",
        command=("codex", "exec", "fix"),
        tests_passed=True,
        policy_passed=True,
        action_category="code_edit",
    )

    assert result.ok
    assert result.value.promoted is True
    assert result.value.human_approval_required is False
    assert recorder.records[-1]["human_approval_required"] is False


def test_missing_primary_context_falls_back_without_stopping():
    primary = Provider(
        [
            CapabilityResult.failure(
                FailureClass.UPSTREAM_UNAVAILABLE,
                "graph down",
                recoverable=True,
            )
        ]
    )
    fallback = Provider(
        [CapabilityResult.success(ImpactReport(provider="native-repo-search"))]
    )
    router = CodeIntelligenceRouter(primary=primary, fallback=fallback)
    worker = Worker(make_worker_success())
    recorder = EvidenceRecorder()
    orchestrator = HermesUltraOrchestrator(
        code_intelligence=router,
        worker_executor=worker,
        candidate_verifier=CandidateVerifier(ApprovalRegistry()),
        evidence_recorder=recorder,
    )

    result = orchestrator.run_coding_task(
        task_id="task-1",
        changed=("src/app.py",),
        worker="codex",
        repo_path="/repo",
        base_sha="abc",
        worktree_path="/tmp/wt",
        command=("codex", "exec", "fix"),
        tests_passed=True,
        policy_passed=True,
    )

    assert result.ok
    assert result.value.degraded_context is True
    assert result.value.promoted is True


def test_research_result_is_recorded_without_secret_leak_or_approval():
    research = ResearchAdapter(
        CapabilityResult.success(
            ResearchValue(stdout="result"),
            metadata={
                "selected_backend": "opencli",
                "diagnostic": {"Authorization": "Bearer secret-value"},
            },
        )
    )
    recorder = EvidenceRecorder()
    orchestrator = HermesUltraOrchestrator(
        agent_reach=research,
        evidence_recorder=recorder,
    )

    result = orchestrator.run_research_task(
        task_id="research-1",
        routes=(("twitter", ("search", "hermes")), ("opencli", ("twitter", "search", "hermes"))),
    )

    assert result.ok
    rendered = repr(recorder.records[-1])
    assert "secret-value" not in rendered
    assert recorder.records[-1]["human_approval_required"] is False


def test_registered_high_consequence_action_is_only_approval_gate():
    primary = Provider(
        [CapabilityResult.success(ImpactReport(provider="codebase-memory"))]
    )
    fallback = Provider(
        [CapabilityResult.success(ImpactReport(provider="native-repo-search"))]
    )
    orchestrator = HermesUltraOrchestrator(
        code_intelligence=CodeIntelligenceRouter(primary=primary, fallback=fallback),
        worker_executor=Worker(make_worker_success()),
        candidate_verifier=CandidateVerifier(ApprovalRegistry({"production_deploy"})),
        evidence_recorder=EvidenceRecorder(),
    )

    result = orchestrator.run_coding_task(
        task_id="task-1",
        changed=("infra/prod.yml",),
        worker="codex",
        repo_path="/repo",
        base_sha="abc",
        worktree_path="/tmp/wt",
        command=("codex", "exec", "deploy"),
        tests_passed=True,
        policy_passed=True,
        action_category="production_deploy",
    )

    assert result.ok
    assert result.value.promoted is False
    assert result.value.human_approval_required is True
    assert result.value.approval_category == "production_deploy"
