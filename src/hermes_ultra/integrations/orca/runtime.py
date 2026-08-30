from __future__ import annotations

from ...contracts import CapabilityResult, FailureClass
from ...evidence import EvidenceEnvelope, EvidenceRecorder
from .client import OrcaClient
from .contracts import OrcaExecutionReceipt, OrcaTaskSpec, OrcaVerificationDecision, OrcaVerificationInput
from .policy import OrcaAuthorityPolicy
from .verification import OrcaResultVerifier


class HermesOrcaRuntime:
    """Governed Hermes facade for Orca.

    Orca may execute developer tasks. It cannot authorize deployment, external
    communication, legal acts, financial acts, or promotion of its own output.
    """

    def __init__(
        self,
        *,
        client: OrcaClient | None = None,
        policy: OrcaAuthorityPolicy | None = None,
        verifier: OrcaResultVerifier | None = None,
        evidence_recorder: EvidenceRecorder | None = None,
    ) -> None:
        self.client = client or OrcaClient()
        self.policy = policy or OrcaAuthorityPolicy()
        self.verifier = verifier or OrcaResultVerifier(self.policy)
        self.evidence_recorder = evidence_recorder or EvidenceRecorder()

    def execute(self, task: OrcaTaskSpec) -> CapabilityResult[OrcaExecutionReceipt]:
        authority = self.policy.evaluate(task.action_category)
        if not authority.allowed:
            envelope = EvidenceEnvelope.new(task.task_id, "orca-execution-plane")
            envelope.status = "failure"
            envelope.failure_class = FailureClass.POLICY_BLOCKED.value
            envelope.health = {
                "action_category": task.action_category,
                "reason": authority.reason,
            }
            envelope.finish(status="failure", failure_class=FailureClass.POLICY_BLOCKED.value)
            self.evidence_recorder.record(envelope)
            return CapabilityResult.failure(
                FailureClass.POLICY_BLOCKED,
                authority.reason,
                recoverable=False,
                metadata={"action_category": task.action_category},
            )

        status = self.client.status()
        if not status.ok:
            return CapabilityResult.failure(
                status.failure_class or FailureClass.UPSTREAM_UNAVAILABLE,
                status.message,
                recoverable=status.recoverable,
                metadata=status.metadata,
            )

        result = self.client.start_task(task)
        envelope = EvidenceEnvelope.new(task.task_id, "orca-execution-plane")
        envelope.provider_version = "orca-cli"
        if not result.ok or result.value is None:
            envelope.status = "failure"
            envelope.failure_class = (
                result.failure_class.value if result.failure_class else FailureClass.UNKNOWN.value
            )
            envelope.health = {
                "action_category": task.action_category,
                "message": result.message,
                "metadata": dict(result.metadata),
            }
            envelope.finish(status="failure", failure_class=envelope.failure_class)
            self.evidence_recorder.record(envelope)
            return result

        receipt = result.value
        envelope.status = "observed"
        envelope.artifacts = [
            {
                "worktree_id": receipt.session.worktree_id,
                "worktree_path": receipt.session.worktree_path,
                "terminal_handle": receipt.session.terminal_handle,
            }
        ]
        envelope.health = {
            "agent": receipt.session.agent,
            "action_category": task.action_category,
            "terminal_observed_idle": True,
            "worker_claimed_complete": receipt.worker_claimed_complete,
            "promotion_authority": False,
        }
        envelope.provenance = {
            "runtime": "stablyai/orca",
            "task_id": task.task_id,
        }
        envelope.finish(status="observed")
        self.evidence_recorder.record(envelope)
        return result

    def verify(self, evidence: OrcaVerificationInput) -> OrcaVerificationDecision:
        decision = self.verifier.evaluate(evidence)
        envelope = EvidenceEnvelope.new(evidence.task_id, "orca-hermes-verification")
        envelope.tests = [
            {"name": "configured_tests", "passed": evidence.tests_passed},
            {"name": "policy_checks", "passed": evidence.policy_passed},
            {"name": "artifact_completeness", "passed": evidence.artifacts_complete},
        ]
        envelope.health = {
            "action_category": evidence.action_category,
            "worker_claimed_complete": evidence.worker_claimed_complete,
            "verified": decision.verified,
            "promotion_authority": decision.promotion_authority,
            "reason": decision.reason,
        }
        envelope.finish(status="success" if decision.verified else "failure")
        self.evidence_recorder.record(envelope)
        return decision
