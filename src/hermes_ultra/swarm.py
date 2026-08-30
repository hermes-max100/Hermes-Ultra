from __future__ import annotations

import json
import shutil
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
class OrcaTask:
    task_id: str
    agent: str
    prompt: str
    repo_path: str
    setup: str = "inherit"


@dataclass(frozen=True)
class OrcaSession:
    task_id: str
    agent: str
    worktree_id: str
    worktree_path: str | None
    terminal_handle: str
    payload: object


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

    This fallback executor never selects the worker/model. Hermes routing supplies
    the assignment and command. OrcaAdapter is preferred when Orca is available.
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


class OrcaAdapter:
    """Native CLI boundary for stablyai/orca.

    Hermes chooses the agent before this adapter is called. Orca only supplies
    agent-first worktree lifecycle and terminal supervision beneath that choice.
    """

    def __init__(
        self,
        binary: str = "orca",
        *,
        runner: Runner = subprocess.run,
    ) -> None:
        self.binary = binary
        self._runner = runner

    def _run_json(
        self,
        args: list[str],
        *,
        cwd: str | None = None,
        metadata: dict[str, object] | None = None,
        timeout: int = 600,
    ) -> CapabilityResult[object]:
        if self._runner is subprocess.run and shutil.which(self.binary) is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                f"missing Orca binary: {self.binary}",
                recoverable=True,
                metadata={} if metadata is None else metadata,
            )
        try:
            proc = self._runner(
                [self.binary, *args],
                cwd=cwd,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return CapabilityResult.failure(
                FailureClass.TIMEOUT,
                "Orca command timed out",
                recoverable=True,
                metadata={} if metadata is None else metadata,
            )
        except OSError as exc:
            return CapabilityResult.failure(
                FailureClass.UPSTREAM_UNAVAILABLE,
                str(exc),
                recoverable=True,
                metadata={} if metadata is None else metadata,
            )

        returncode = int(getattr(proc, "returncode", 1))
        stdout = str(getattr(proc, "stdout", ""))
        stderr = str(getattr(proc, "stderr", ""))
        if returncode != 0:
            combined = {"returncode": returncode, **({} if metadata is None else metadata)}
            return CapabilityResult.failure(
                FailureClass.WORKER_FAILED,
                stderr.strip() or f"Orca exited {returncode}",
                recoverable=True,
                metadata=combined,
            )
        try:
            payload = json.loads(stdout or "null")
        except json.JSONDecodeError as exc:
            return CapabilityResult.failure(
                FailureClass.EVIDENCE_INCOMPLETE,
                f"Orca returned malformed JSON: {exc}",
                recoverable=True,
                metadata={} if metadata is None else metadata,
            )
        return CapabilityResult.success(payload, metadata={} if metadata is None else metadata)

    @staticmethod
    def _value(payload: object, *paths: tuple[str, ...]) -> object | None:
        for path in paths:
            current = payload
            valid = True
            for key in path:
                if not isinstance(current, dict) or key not in current:
                    valid = False
                    break
                current = current[key]
            if valid:
                return current
        return None

    def create(self, task: OrcaTask) -> CapabilityResult[OrcaSession]:
        if task.setup not in {"run", "skip", "inherit"}:
            raise ValueError("Orca setup must be run, skip, or inherit")
        args = [
            "worktree", "create",
            "--name", task.task_id,
            "--no-parent",
            "--agent", task.agent,
            "--prompt", task.prompt,
            "--setup", task.setup,
            "--json",
        ]
        result = self._run_json(args, cwd=task.repo_path, metadata={"agent": task.agent})
        if not result.ok:
            return CapabilityResult.failure(
                result.failure_class or FailureClass.WORKER_FAILED,
                result.message,
                recoverable=result.recoverable,
                metadata=result.metadata,
            )

        payload = result.value
        worktree_id = self._value(
            payload,
            ("worktree", "id"),
            ("worktreeId",),
            ("worktree_id",),
            ("id",),
        )
        worktree_path = self._value(
            payload,
            ("worktree", "path"),
            ("worktreePath",),
            ("worktree_path",),
        )
        terminal_handle = self._value(
            payload,
            ("terminal", "handle"),
            ("terminalHandle",),
            ("terminal_handle",),
            ("terminal", "id"),
        )
        if not worktree_id or not terminal_handle:
            return CapabilityResult.failure(
                FailureClass.EVIDENCE_INCOMPLETE,
                "Orca create result omitted worktree id or terminal handle",
                recoverable=True,
                metadata={"agent": task.agent},
            )
        return CapabilityResult.success(
            OrcaSession(
                task_id=task.task_id,
                agent=task.agent,
                worktree_id=str(worktree_id),
                worktree_path=None if worktree_path is None else str(worktree_path),
                terminal_handle=str(terminal_handle),
                payload=payload,
            ),
            metadata={"agent": task.agent},
        )

    def wait(self, terminal_handle: str, *, timeout_ms: int = 600000) -> CapabilityResult[object]:
        return self._run_json(
            [
                "terminal", "wait",
                "--terminal", terminal_handle,
                "--for", "exit",
                "--timeout-ms", str(timeout_ms),
                "--json",
            ],
            timeout=max(60, int(timeout_ms / 1000) + 30),
        )

    def stop(self, worktree_id: str) -> CapabilityResult[object]:
        return self._run_json(
            ["terminal", "stop", "--worktree", worktree_id, "--json"],
        )

    def remove(self, worktree_id: str) -> CapabilityResult[object]:
        return self._run_json(
            ["worktree", "rm", "--worktree", worktree_id, "--force", "--json"],
        )


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
