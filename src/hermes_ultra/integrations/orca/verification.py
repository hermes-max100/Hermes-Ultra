from __future__ import annotations

from .contracts import OrcaVerificationDecision, OrcaVerificationInput
from .policy import OrcaAuthorityPolicy


class OrcaResultVerifier:
    """Hermes-side verifier for evidence produced by Orca workers."""

    def __init__(self, policy: OrcaAuthorityPolicy | None = None) -> None:
        self.policy = policy or OrcaAuthorityPolicy()

    def evaluate(self, evidence: OrcaVerificationInput) -> OrcaVerificationDecision:
        authority = self.policy.evaluate(evidence.action_category)
        if not authority.allowed:
            return OrcaVerificationDecision(
                verified=False,
                promotion_authority=False,
                reason=authority.reason,
            )
        if not evidence.tests_passed:
            return OrcaVerificationDecision(
                verified=False,
                promotion_authority=False,
                reason="configured tests did not pass",
            )
        if not evidence.policy_passed:
            return OrcaVerificationDecision(
                verified=False,
                promotion_authority=False,
                reason="Hermes policy checks did not pass",
            )
        if not evidence.artifacts_complete:
            return OrcaVerificationDecision(
                verified=False,
                promotion_authority=False,
                reason="required evidence artifacts are incomplete",
            )
        return OrcaVerificationDecision(
            verified=True,
            promotion_authority=False,
            reason="verified by Hermes; promotion remains a separate Hermes decision",
        )
