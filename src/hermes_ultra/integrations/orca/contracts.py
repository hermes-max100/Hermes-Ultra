from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class OrcaTaskSpec:
    """Hermes-owned task description handed to Orca for execution only."""

    task_id: str
    agent: str
    prompt: str
    repo_path: str
    setup: str = "inherit"
    top_level: bool = True
    action_category: str = "code_edit"

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id is required")
        if not self.agent.strip():
            raise ValueError("agent is required")
        if not self.prompt.strip():
            raise ValueError("prompt is required")
        if not self.repo_path.strip():
            raise ValueError("repo_path is required")
        if self.setup not in {"run", "skip", "inherit"}:
            raise ValueError("setup must be run, skip, or inherit")


@dataclass(frozen=True)
class OrcaSession:
    task_id: str
    agent: str
    worktree_id: str
    worktree_path: str | None
    terminal_handle: str
    payload: object


@dataclass(frozen=True)
class OrcaExecutionReceipt:
    """Observed Orca execution state.

    This is deliberately not a success/verification receipt. An idle terminal or
    worker claim is evidence only; Hermes must independently verify the result.
    """

    task_id: str
    session: OrcaSession
    ready_payload: object
    send_payload: object
    idle_payload: object
    transcript_payload: object
    worker_claimed_complete: bool = False


@dataclass(frozen=True)
class OrcaPolicyDecision:
    allowed: bool
    action_category: str
    reason: str


@dataclass(frozen=True)
class OrcaVerificationInput:
    task_id: str
    action_category: str
    tests_passed: bool
    policy_passed: bool
    artifacts_complete: bool
    worker_claimed_complete: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class OrcaVerificationDecision:
    verified: bool
    promotion_authority: bool
    reason: str
