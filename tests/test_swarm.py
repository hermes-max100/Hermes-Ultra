from __future__ import annotations

from types import SimpleNamespace

from hermes_ultra.autonomy import ApprovalRegistry
from hermes_ultra.swarm import (
    Candidate,
    CandidateVerifier,
    WorkerAssignment,
    WorktreeExecutor,
)


def test_worker_runs_inside_isolated_worktree():
    calls = []

    def runner(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    executor = WorktreeExecutor(runner=runner)
    assignment = WorkerAssignment(
        task_id="t1",
        worker="codex",
        repo_path="/repo",
        base_sha="abc123",
        worktree_path="/tmp/hermes-wt-t1",
        command=("codex", "exec", "fix tests"),
    )

    result = executor.execute(assignment)

    assert result.ok
    assert calls[0][0] == [
        "git",
        "-C",
        "/repo",
        "worktree",
        "add",
        "--detach",
        "/tmp/hermes-wt-t1",
        "abc123",
    ]
    assert calls[1][0] == ["codex", "exec", "fix tests"]
    assert calls[1][1]["cwd"] == "/tmp/hermes-wt-t1"
    assert calls[1][1]["cwd"] != "/repo"


def test_worker_failure_is_recoverable_for_orchestrator():
    def runner(cmd, **kwargs):
        if cmd[0] == "git":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=7, stdout="", stderr="worker crashed")

    executor = WorktreeExecutor(runner=runner)
    assignment = WorkerAssignment(
        task_id="t1",
        worker="kimi",
        repo_path="/repo",
        base_sha="abc123",
        worktree_path="/tmp/wt",
        command=("kimi", "run"),
    )

    result = executor.execute(assignment)

    assert not result.ok
    assert result.recoverable is True


def test_verified_ordinary_candidate_promotes_without_human_approval():
    verifier = CandidateVerifier(ApprovalRegistry({"production_deploy"}))
    candidate = Candidate(worker="codex", tests_passed=True, policy_passed=True)

    result = verifier.evaluate(candidate, action_category="code_edit")

    assert result.verified is True
    assert result.approved_for_promotion is True
    assert result.human_approval_required is False
    assert result.approval_category is None


def test_registered_high_consequence_category_preserves_approval_boundary():
    verifier = CandidateVerifier(ApprovalRegistry({"production_deploy"}))
    candidate = Candidate(worker="codex", tests_passed=True, policy_passed=True)

    result = verifier.evaluate(candidate, action_category="production_deploy")

    assert result.verified is True
    assert result.approved_for_promotion is False
    assert result.human_approval_required is True
    assert result.approval_category == "production_deploy"


def test_failed_tests_never_promote():
    verifier = CandidateVerifier(ApprovalRegistry())
    candidate = Candidate(worker="claude", tests_passed=False, policy_passed=True)

    result = verifier.evaluate(candidate, action_category="code_edit")

    assert result.verified is False
    assert result.approved_for_promotion is False
    assert result.human_approval_required is False
