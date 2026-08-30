from __future__ import annotations

import json
import shutil
import subprocess
from typing import Callable

from ...contracts import CapabilityResult, FailureClass
from ...evidence import redact_secrets
from .contracts import OrcaExecutionReceipt, OrcaSession, OrcaTaskSpec

Runner = Callable[..., object]


class OrcaClient:
    """Typed, JSON-only boundary around the Orca CLI.

    Hermes chooses the agent and owns policy/verification. Orca owns only the
    worktree, terminal, and agent-session mechanics beneath that decision.
    """

    def __init__(self, binary: str = "orca", *, runner: Runner = subprocess.run) -> None:
        self.binary = binary
        self._runner = runner

    def _run_json(
        self,
        args: list[str],
        *,
        cwd: str | None = None,
        timeout: int = 600,
        metadata: dict[str, object] | None = None,
    ) -> CapabilityResult[object]:
        meta = {} if metadata is None else dict(metadata)
        if self._runner is subprocess.run and shutil.which(self.binary) is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                f"missing Orca binary: {self.binary}",
                recoverable=True,
                metadata=meta,
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
                metadata=meta,
            )
        except OSError as exc:
            return CapabilityResult.failure(
                FailureClass.UPSTREAM_UNAVAILABLE,
                str(redact_secrets(str(exc))),
                recoverable=True,
                metadata=meta,
            )

        returncode = int(getattr(proc, "returncode", 1))
        stdout = str(getattr(proc, "stdout", ""))
        stderr = str(redact_secrets(str(getattr(proc, "stderr", ""))))
        if returncode != 0:
            return CapabilityResult.failure(
                FailureClass.WORKER_FAILED,
                stderr.strip() or f"Orca exited {returncode}",
                recoverable=True,
                metadata={"returncode": returncode, **meta},
            )
        try:
            payload = json.loads(stdout or "null")
        except json.JSONDecodeError as exc:
            return CapabilityResult.failure(
                FailureClass.EVIDENCE_INCOMPLETE,
                f"Orca returned malformed JSON: {exc}",
                recoverable=True,
                metadata=meta,
            )
        return CapabilityResult.success(payload, metadata=meta)

    @staticmethod
    def _value(payload: object, *paths: tuple[str, ...]) -> object | None:
        for path in paths:
            current = payload
            for key in path:
                if not isinstance(current, dict) or key not in current:
                    break
                current = current[key]
            else:
                return current
        return None

    def status(self) -> CapabilityResult[object]:
        return self._run_json(["status", "--json"], timeout=30)

    def _resolve_terminal_handle(
        self,
        payload: object,
        *,
        worktree_id: str,
        agent: str,
    ) -> CapabilityResult[str]:
        handle = self._value(
            payload,
            ("agentTerminalHandle",),
            ("startupTerminal", "handle"),
            ("terminal", "handle"),
            ("terminalHandle",),
            ("terminal_handle",),
            ("terminal", "id"),
        )
        if handle:
            return CapabilityResult.success(str(handle))

        listed = self._run_json(
            ["terminal", "list", "--worktree", f"id:{worktree_id}", "--json"],
            timeout=30,
            metadata={"phase": "terminal_handle_recovery", "agent": agent},
        )
        if not listed.ok:
            return CapabilityResult.failure(
                listed.failure_class or FailureClass.EVIDENCE_INCOMPLETE,
                listed.message,
                recoverable=listed.recoverable,
                metadata=listed.metadata,
            )

        raw = listed.value
        terminals = raw.get("terminals", []) if isinstance(raw, dict) else raw
        if not isinstance(terminals, list):
            terminals = []

        matches: list[str] = []
        all_handles: list[str] = []
        agent_lower = agent.lower()
        for item in terminals:
            if not isinstance(item, dict):
                continue
            candidate = item.get("handle") or item.get("id")
            if not candidate:
                continue
            candidate = str(candidate)
            all_handles.append(candidate)
            searchable = " ".join(
                str(item.get(key, "")) for key in ("title", "command", "agent", "name")
            ).lower()
            if agent_lower and agent_lower in searchable:
                matches.append(candidate)

        if len(matches) == 1:
            return CapabilityResult.success(matches[0])
        if not matches and len(all_handles) == 1:
            return CapabilityResult.success(all_handles[0])
        return CapabilityResult.failure(
            FailureClass.EVIDENCE_INCOMPLETE,
            "unable to resolve a unique Orca agent terminal handle",
            recoverable=True,
            metadata={"agent": agent, "terminal_count": len(all_handles)},
        )

    def _create(
        self,
        task: OrcaTaskSpec,
        *,
        include_prompt: bool,
    ) -> CapabilityResult[OrcaSession]:
        args = ["worktree", "create", "--name", task.task_id]
        if task.top_level:
            args.append("--no-parent")
        args.extend(["--agent", task.agent])
        if include_prompt:
            args.extend(["--prompt", task.prompt])
        args.extend(["--setup", task.setup, "--json"])

        result = self._run_json(
            args,
            cwd=task.repo_path,
            metadata={"agent": task.agent, "task_id": task.task_id},
        )
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
        if not worktree_id:
            return CapabilityResult.failure(
                FailureClass.EVIDENCE_INCOMPLETE,
                "Orca create result omitted worktree id",
                recoverable=True,
                metadata={"agent": task.agent, "task_id": task.task_id},
            )

        terminal = self._resolve_terminal_handle(
            payload,
            worktree_id=str(worktree_id),
            agent=task.agent,
        )
        if not terminal.ok or terminal.value is None:
            return CapabilityResult.failure(
                terminal.failure_class or FailureClass.EVIDENCE_INCOMPLETE,
                terminal.message,
                recoverable=terminal.recoverable,
                metadata=terminal.metadata,
            )

        return CapabilityResult.success(
            OrcaSession(
                task_id=task.task_id,
                agent=task.agent,
                worktree_id=str(worktree_id),
                worktree_path=None if worktree_path is None else str(worktree_path),
                terminal_handle=terminal.value,
                payload=payload,
            ),
            metadata={"agent": task.agent, "task_id": task.task_id},
        )

    def create(self, task: OrcaTaskSpec) -> CapabilityResult[OrcaSession]:
        """Compatibility handoff: create a worktree and send the prompt immediately."""
        return self._create(task, include_prompt=True)

    def wait(self, terminal_handle: str, *, timeout_ms: int = 600000) -> CapabilityResult[object]:
        """Legacy exit wait retained for compatibility; agent TUIs usually should use wait_idle."""
        return self._run_json(
            [
                "terminal",
                "wait",
                "--terminal",
                terminal_handle,
                "--for",
                "exit",
                "--timeout-ms",
                str(timeout_ms),
                "--json",
            ],
            timeout=max(60, int(timeout_ms / 1000) + 30),
        )

    def wait_idle(self, terminal_handle: str, *, timeout_ms: int = 300000) -> CapabilityResult[object]:
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

    def send(self, terminal_handle: str, text: str) -> CapabilityResult[object]:
        return self._run_json(
            [
                "terminal",
                "send",
                "--terminal",
                terminal_handle,
                "--text",
                text,
                "--enter",
                "--json",
            ]
        )

    def read(self, terminal_handle: str) -> CapabilityResult[object]:
        return self._run_json(
            ["terminal", "read", "--terminal", terminal_handle, "--json"],
            timeout=30,
        )

    def stop(self, worktree_id: str) -> CapabilityResult[object]:
        return self._run_json(
            ["terminal", "stop", "--worktree", f"id:{worktree_id}", "--json"],
            timeout=30,
        )

    def start_task(
        self,
        task: OrcaTaskSpec,
        *,
        readiness_timeout_ms: int = 60000,
        observation_timeout_ms: int = 300000,
    ) -> CapabilityResult[OrcaExecutionReceipt]:
        """Start an agent with a readiness gate and collect non-authoritative evidence.

        The prompt is intentionally sent only after the TUI reports idle. The second
        idle observation is *not* treated as proof that the requested work is correct.
        """
        created = self._create(task, include_prompt=False)
        if not created.ok or created.value is None:
            return CapabilityResult.failure(
                created.failure_class or FailureClass.WORKER_FAILED,
                created.message,
                recoverable=created.recoverable,
                metadata=created.metadata,
            )

        session = created.value
        ready = self.wait_idle(session.terminal_handle, timeout_ms=readiness_timeout_ms)
        if not ready.ok:
            return CapabilityResult.failure(
                ready.failure_class or FailureClass.TIMEOUT,
                ready.message,
                recoverable=ready.recoverable,
                metadata={"phase": "readiness", "worktree_id": session.worktree_id},
            )

        sent = self.send(session.terminal_handle, task.prompt)
        if not sent.ok:
            return CapabilityResult.failure(
                sent.failure_class or FailureClass.WORKER_FAILED,
                sent.message,
                recoverable=sent.recoverable,
                metadata={"phase": "prompt_send", "worktree_id": session.worktree_id},
            )

        idle = self.wait_idle(session.terminal_handle, timeout_ms=observation_timeout_ms)
        if not idle.ok:
            return CapabilityResult.failure(
                idle.failure_class or FailureClass.TIMEOUT,
                idle.message,
                recoverable=idle.recoverable,
                metadata={"phase": "observation", "worktree_id": session.worktree_id},
            )

        transcript = self.read(session.terminal_handle)
        if not transcript.ok:
            return CapabilityResult.failure(
                transcript.failure_class or FailureClass.EVIDENCE_INCOMPLETE,
                transcript.message,
                recoverable=transcript.recoverable,
                metadata={"phase": "transcript", "worktree_id": session.worktree_id},
            )

        return CapabilityResult.success(
            OrcaExecutionReceipt(
                task_id=task.task_id,
                session=session,
                ready_payload=ready.value,
                send_payload=sent.value,
                idle_payload=idle.value,
                transcript_payload=transcript.value,
                worker_claimed_complete=False,
            ),
            metadata={"agent": task.agent, "worktree_id": session.worktree_id},
        )
