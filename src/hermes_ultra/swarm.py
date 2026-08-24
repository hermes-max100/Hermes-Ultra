from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable

from .autonomy import ApprovalRegistry
from .contracts import CapabilityResult, FailureClass

Runner = Callable[..., object]


@dataclass(frozen=True)
class WorkerAssignment:
    task_id: str
    worker: str
    repo_path: str
    base_sha: str
    worktree_path: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class WorkerOutcome:
    task_id: str
    worker: str
    worktree_path: str
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class Candidate:
    worker: str
    tests_passed: bool
    policy_passed: bool


@dataclass(frozen=True)
class VerificationDecision:
    verified: bool
    approved_for_promotion: bool
    human_approval_required: bool
    approval_category: str | None


class WorktreeExecutor:
    """Runs an already-selected worker in an isolated Git worktree.

    This class never selects the worker/model. Hermes routing supplies the
    assignment and command.
    """

    def __init__(self, *, runner: Runner = subprocess.run) -> None:
        self._runner = runner

    def _call(self, cmd: list[str], **kwargs):
        return self._runner(
            cmd,
            text=True,
            capture_output=True,
            check=False,
            timeout=kwargs.pop("timeout", 600),
            **kwargs,
        )

    def execute(self, assignment: WorkerAssignment) -> CapabilityResult[WorkerOutcome]:
        try:
            prep = self._call(
                [
                    "git",
                    "-C",
                    assignment.repo_path,
                    "worktree",
                    "add",
                    "--detach",
                    assignment.worktree_path,
                    assignment.base_sha,
                ],
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return CapabilityResult.failure(
                FailureClass.TIMEOUT,
                "worktree creation timed out",
                recoverable=True,
            )
        except OSError as exc:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                str(exc),
                recoverable=True,
            )

        prep_rc = int(getattr(prep, "returncode", 1))
        if prep_rc != 0:
            return CapabilityResult.failure(
                FailureClass.WORKER_FAILED,
                str(getattr(prep, "stderr", "worktree creation failed")).strip(),
                recoverable=True,
                metadata={"phase": "worktree", "returncode": prep_rc},
            )

        try:
            proc = self._call(list(assignment.command), cwd=assignment.worktree_path)
        except subprocess.TimeoutExpired:
            return CapabilityResult.failure(
                FailureClass.TIMEOUT,
                f"worker {assignment.worker} timed out",
                recoverable=True,
            )
        except OSError as exc:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                str(exc),
                recoverable=True,
            )

        outcome = WorkerOutcome(
            task_id=assignment.task_id,
            worker=assignment.worker,
            worktree_path=assignment.worktree_path,
            returncode=int(getattr(proc, "returncode", 1)),
            stdout=str(getattr(proc, "stdout", "")),
            stderr=str(getattr(proc, "stderr", "")),
        )
        if outcome.returncode != 0:
            return CapabilityResult.failure(
                FailureClass.WORKER_FAILED,
                outcome.stderr.strip() or f"worker exited {outcome.returncode}",
                recoverable=True,
                metadata={"worker": assignment.worker, "returncode": outcome.returncode},
            )
        return CapabilityResult.success(outcome)


class CandidateVerifier:
    def __init__(self, approval_registry: ApprovalRegistry) -> None:
        self.approval_registry = approval_registry

    def evaluate(self, candidate: Candidate, *, action_category: str) -> VerificationDecision:
        verified = candidate.tests_passed and candidate.policy_passed
        approval = self.approval_registry.evaluate(action_category)
        return VerificationDecision(
            verified=verified,
            approved_for_promotion=verified and not approval.human_approval_required,
            human_approval_required=approval.human_approval_required,
            approval_category=approval.category,
        )
