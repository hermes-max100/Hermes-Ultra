from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .contracts import CapabilityResult, FailureClass
from .evidence import EvidenceEnvelope, EvidenceRecorder
from .swarm import Candidate, WorkerAssignment


@dataclass(frozen=True)
class CodingTaskResult:
    task_id: str
    provider: str
    degraded_context: bool
    worker: str
    promoted: bool
    human_approval_required: bool
    approval_category: str | None


@dataclass(frozen=True)
class ResearchTaskResult:
    task_id: str
    value: object
    selected_backend: str | None


class HermesUltraOrchestrator:
    """Thin composition layer that preserves Hermes as routing authority."""

    def __init__(
        self,
        *,
        code_intelligence=None,
        worker_executor=None,
        candidate_verifier=None,
        agent_reach=None,
        media_adapter=None,
        capability_context=None,
        evidence_recorder: EvidenceRecorder | None = None,
    ) -> None:
        self.code_intelligence = code_intelligence
        self.worker_executor = worker_executor
        self.candidate_verifier = candidate_verifier
        self.agent_reach = agent_reach
        self.media_adapter = media_adapter
        self.capability_context = capability_context
        self.evidence_recorder = evidence_recorder or EvidenceRecorder()

    def _record_failure(
        self,
        *,
        task_id: str,
        capability: str,
        result: CapabilityResult,
    ) -> None:
        envelope = EvidenceEnvelope.new(task_id, capability)
        envelope.status = "failure"
        envelope.failure_class = (
            result.failure_class.value if result.failure_class is not None else FailureClass.UNKNOWN.value
        )
        envelope.health = {
            "message": result.message,
            "recoverable": result.recoverable,
            "metadata": dict(result.metadata),
        }
        envelope.finish(status="failure", failure_class=envelope.failure_class)
        self.evidence_recorder.record(envelope)

    def run_task(self, task) -> CapabilityResult:
        """Delegate a generic task to the additive capability/context layer."""
        if self.capability_context is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                "capability/context orchestrator is not configured",
                recoverable=False,
            )
        return self.capability_context.run(task)

    def run_coding_task(
        self,
        *,
        task_id: str,
        changed: Sequence[str],
        worker: str,
        repo_path: str,
        base_sha: str,
        worktree_path: str,
        command: Sequence[str],
        tests_passed: bool,
        policy_passed: bool,
        action_category: str = "code_edit",
    ) -> CapabilityResult[CodingTaskResult]:
        if self.code_intelligence is None or self.worker_executor is None or self.candidate_verifier is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                "coding orchestration dependencies are not configured",
                recoverable=False,
            )

        pre = self.code_intelligence.impact_analysis(changed)
        if not pre.ok or pre.value is None:
            self._record_failure(task_id=task_id, capability="code-intelligence", result=pre)
            return CapabilityResult.failure(
                pre.failure_class or FailureClass.UNKNOWN,
                pre.message,
                recoverable=pre.recoverable,
                metadata=pre.metadata,
            )

        assignment = WorkerAssignment(
            task_id=task_id,
            worker=worker,
            repo_path=repo_path,
            base_sha=base_sha,
            worktree_path=worktree_path,
            command=tuple(command),
        )
        execution = self.worker_executor.execute(assignment)
        if not execution.ok:
            self._record_failure(task_id=task_id, capability="coding-swarm", result=execution)
            return CapabilityResult.failure(
                execution.failure_class or FailureClass.WORKER_FAILED,
                execution.message,
                recoverable=execution.recoverable,
                metadata=execution.metadata,
            )

        post = self.code_intelligence.impact_analysis(changed)
        if not post.ok or post.value is None:
            self._record_failure(task_id=task_id, capability="code-intelligence-post", result=post)
            return CapabilityResult.failure(
                post.failure_class or FailureClass.UNKNOWN,
                post.message,
                recoverable=post.recoverable,
                metadata=post.metadata,
            )

        decision = self.candidate_verifier.evaluate(
            Candidate(worker=worker, tests_passed=tests_passed, policy_passed=policy_passed),
            action_category=action_category,
        )
        degraded = bool(pre.value.degraded_context or post.value.degraded_context)
        provider = post.value.provider
        output = CodingTaskResult(
            task_id=task_id,
            provider=provider,
            degraded_context=degraded,
            worker=worker,
            promoted=decision.approved_for_promotion,
            human_approval_required=decision.human_approval_required,
            approval_category=decision.approval_category,
        )

        envelope = EvidenceEnvelope.new(task_id, "coding-orchestrator")
        envelope.human_approval_required = decision.human_approval_required
        envelope.approval_category = decision.approval_category
        envelope.tests = [
            {"name": "configured_tests", "passed": tests_passed},
            {"name": "policy_checks", "passed": policy_passed},
        ]
        envelope.health = {
            "pre_context_provider": pre.value.provider,
            "post_context_provider": post.value.provider,
            "degraded_context": degraded,
            "worker": worker,
            "worker_returncode": getattr(execution.value, "returncode", None),
            "promoted": decision.approved_for_promotion,
            "pre_metadata": dict(pre.metadata),
            "post_metadata": dict(post.metadata),
        }
        envelope.finish(status="success")
        self.evidence_recorder.record(envelope)
        return CapabilityResult.success(output)

    def run_research_task(
        self,
        *,
        task_id: str,
        routes: Sequence[tuple[str, Sequence[str]]],
    ) -> CapabilityResult[ResearchTaskResult]:
        if self.agent_reach is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                "Agent-Reach is not configured",
                recoverable=False,
            )
        result = self.agent_reach.execute_with_fallback(routes)
        if not result.ok:
            self._record_failure(task_id=task_id, capability="agent-reach", result=result)
            return CapabilityResult.failure(
                result.failure_class or FailureClass.UPSTREAM_UNAVAILABLE,
                result.message,
                recoverable=result.recoverable,
                metadata=result.metadata,
            )

        selected = result.metadata.get("selected_backend")
        output = ResearchTaskResult(
            task_id=task_id,
            value=result.value,
            selected_backend=str(selected) if selected is not None else None,
        )
        envelope = EvidenceEnvelope.new(task_id, "agent-reach")
        envelope.health = {
            "metadata": dict(result.metadata),
            "result": getattr(result.value, "stdout", repr(result.value)),
        }
        envelope.finish(status="success")
        self.evidence_recorder.record(envelope)
        return CapabilityResult.success(output, metadata=result.metadata)

    def run_media_job(self, job) -> CapabilityResult:
        if self.media_adapter is None:
            return CapabilityResult.failure(
                FailureClass.DEPENDENCY_MISSING,
                "media adapter is not configured",
                recoverable=False,
            )
        result = self.media_adapter.run(job)
        envelope = EvidenceEnvelope.new(job.task_id, "openmontage")
        if result.ok:
            envelope.health = {"media_result": repr(result.value)}
            if getattr(result.value, "human_approval_required", False):
                envelope.human_approval_required = True
                envelope.approval_category = getattr(result.value, "approval_category", None)
            envelope.finish(status="success")
        else:
            envelope.status = "failure"
            envelope.failure_class = (
                result.failure_class.value if result.failure_class is not None else FailureClass.UNKNOWN.value
            )
            envelope.health = {"message": result.message, "metadata": dict(result.metadata)}
            envelope.finish(status="failure", failure_class=envelope.failure_class)
        self.evidence_recorder.record(envelope)
        return result
