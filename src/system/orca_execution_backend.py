#!/usr/bin/env python3
"""Governed Orca execution backend beneath Hermes authority.

Orca supplies developer worktrees and agent terminals. Hermes retains routing,
policy, evidence, verification, and promotion authority. Worker state is never
accepted as proof of successful completion by itself.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Mapping

Runner = Callable[..., object]


class OrcaExecutionError(RuntimeError):
    pass


class OrcaPolicyError(PermissionError):
    pass


@dataclass(frozen=True)
class OrcaPolicyDecision:
    allowed: bool
    human_approval_required: bool = False
    category: str | None = None


class OrcaDevelopmentPolicy:
    """Fail-closed policy for the development-only Orca authority surface."""

    ALLOWED_ACTIONS = frozenset(
        {
            "code_edit",
            "code_review",
            "test",
            "lint",
            "build",
            "local_package",
            "local_git",
            "local_browser",
        }
    )
    ALLOWED_CLASSIFICATIONS = frozenset({"PUBLIC", "INTERNAL"})

    def authorize(self, action_category: str, classification: str) -> OrcaPolicyDecision:
        action = str(action_category).strip().lower()
        data_class = str(classification).strip().upper()
        if action not in self.ALLOWED_ACTIONS:
            raise OrcaPolicyError(f"Orca action is outside development authority: {action or '<empty>'}")
        if data_class not in self.ALLOWED_CLASSIFICATIONS:
            raise OrcaPolicyError(f"Orca data class is outside development authority: {data_class or '<empty>'}")
        return OrcaPolicyDecision(True, False, None)


@dataclass(frozen=True)
class OrcaTask:
    task_id: str
    agent: str
    prompt: str
    repo_path: str
    setup: str = "inherit"
    action_category: str = "code_edit"
    classification: str = "INTERNAL"


@dataclass(frozen=True)
class OrcaSession:
    task_id: str
    agent: str
    worktree_id: str
    worktree_path: str | None
    terminal_handle: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class OrcaVerificationDecision:
    verified: bool
    approved_for_promotion: bool
    worker_done: bool
    tests_passed: bool
    policy_passed: bool
    human_approval_required: bool = False


def verify_candidate(
    *,
    worker_done: bool,
    tests_passed: bool,
    policy_passed: bool,
    human_approval_required: bool = False,
) -> OrcaVerificationDecision:
    """Hermes proof gate. Orca completion is evidence, never self-certification."""
    verified = bool(worker_done and tests_passed and policy_passed)
    return OrcaVerificationDecision(
        verified=verified,
        approved_for_promotion=verified and not human_approval_required,
        worker_done=bool(worker_done),
        tests_passed=bool(tests_passed),
        policy_passed=bool(policy_passed),
        human_approval_required=bool(human_approval_required),
    )


class OrcaExecutionBackend:
    """JSON-only CLI boundary for stablyai/orca.

    The caller chooses the coding agent before invoking this backend. The
    backend does not route models, expand authority, deploy production, spend
    money, file legal documents, or promote its own output.
    """

    def __init__(
        self,
        binary: str | None = None,
        *,
        runner: Runner = subprocess.run,
        policy: OrcaDevelopmentPolicy | None = None,
    ) -> None:
        self.binary = binary or self.resolve_binary()
        self._runner = runner
        self.policy = policy or OrcaDevelopmentPolicy()

    @staticmethod
    def resolve_binary() -> str:
        explicit = os.environ.get("ORCA_CLI_COMMAND", "").strip()
        if explicit:
            return explicit
        if platform.system() == "Linux":
            return "orca-ide"
        return "orca"

    def _run_json(
        self,
        args: list[str],
        *,
        cwd: str | None = None,
        timeout: int = 600,
    ) -> Mapping[str, Any]:
        env = dict(os.environ)
        env["DO_NOT_TRACK"] = "1"
        env["ORCA_TELEMETRY_DISABLED"] = "1"
        try:
            proc = self._runner(
                [self.binary, *args],
                cwd=cwd,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OrcaExecutionError(f"Orca command unavailable: {exc}") from exc
        returncode = int(getattr(proc, "returncode", 1))
        stdout = str(getattr(proc, "stdout", ""))
        stderr = str(getattr(proc, "stderr", ""))
        if returncode != 0:
            raise OrcaExecutionError(stderr.strip() or f"Orca exited {returncode}")
        try:
            payload = json.loads(stdout or "{}")
        except json.JSONDecodeError as exc:
            raise OrcaExecutionError(f"Orca returned malformed JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise OrcaExecutionError("Orca JSON result must be an object")
        return payload

    @staticmethod
    def _nested(payload: Mapping[str, Any], *path: str) -> Any:
        current: Any = payload
        for key in path:
            if not isinstance(current, Mapping) or key not in current:
                return None
            current = current[key]
        return current

    def create(self, task: OrcaTask) -> OrcaSession:
        self.policy.authorize(task.action_category, task.classification)
        if task.setup not in {"run", "skip", "inherit"}:
            raise ValueError("Orca setup must be run, skip, or inherit")
        payload = self._run_json(
            [
                "worktree",
                "create",
                "--name",
                task.task_id,
                "--no-parent",
                "--agent",
                task.agent,
                "--prompt",
                task.prompt,
                "--setup",
                task.setup,
                "--json",
            ],
            cwd=task.repo_path,
        )
        worktree_id = self._nested(payload, "worktree", "id") or payload.get("worktreeId")
        worktree_path = self._nested(payload, "worktree", "path") or payload.get("worktreePath")
        terminal_handle = (
            payload.get("agentTerminalHandle")
            or self._nested(payload, "startupTerminal", "handle")
            or self._nested(payload, "terminal", "handle")
        )
        if not worktree_id:
            raise OrcaExecutionError("Orca create result omitted the full worktree id")
        if not terminal_handle:
            raise OrcaExecutionError("Orca create result omitted the agent terminal handle")
        return OrcaSession(
            task_id=task.task_id,
            agent=task.agent,
            worktree_id=str(worktree_id),
            worktree_path=None if worktree_path is None else str(worktree_path),
            terminal_handle=str(terminal_handle),
            payload=dict(payload),
        )

    def wait_tui_idle(self, terminal_handle: str, *, timeout_ms: int = 60000) -> Mapping[str, Any]:
        if timeout_ms < 1:
            raise ValueError("timeout_ms must be positive")
        return self._run_json(
            [
                "terminal",
                "wait",
                "--terminal",
                terminal_handle,
                "--for",
                "tui-idle",
                "--timeout-ms",
                str(timeout_ms),
                "--json",
            ],
            timeout=max(60, int(timeout_ms / 1000) + 30),
        )

    def stop(self, worktree_id: str) -> Mapping[str, Any]:
        return self._run_json(["terminal", "stop", "--worktree", f"id:{worktree_id}", "--json"])

    def remove(self, worktree_id: str) -> Mapping[str, Any]:
        return self._run_json(["worktree", "rm", "--worktree", f"id:{worktree_id}", "--force", "--json"])
