from __future__ import annotations

from types import SimpleNamespace

from hermes_ultra.contracts import FailureClass
from hermes_ultra.integrations.orca import (
    HermesOrcaRuntime,
    OrcaAuthorityPolicy,
    OrcaClient,
    OrcaTaskSpec,
    OrcaVerificationInput,
)


def test_policy_is_fail_closed_for_production_financial_and_legal_authority():
    policy = OrcaAuthorityPolicy()

    assert policy.evaluate("code_edit").allowed is True
    assert policy.evaluate("production_deploy").allowed is False
    assert policy.evaluate("financial_transfer").allowed is False
    assert policy.evaluate("legal_filing").allowed is False
    assert policy.evaluate("unknown_future_action").allowed is False


def test_runtime_blocks_disallowed_action_before_orca_is_called():
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    runtime = HermesOrcaRuntime(client=OrcaClient(runner=runner))
    result = runtime.execute(
        OrcaTaskSpec(
            task_id="deploy-1",
            agent="codex",
            prompt="deploy production",
            repo_path="/repo",
            action_category="production_deploy",
        )
    )

    assert not result.ok
    assert result.failure_class == FailureClass.POLICY_BLOCKED
    assert calls == []


def test_worker_claim_can_never_self_promote():
    runtime = HermesOrcaRuntime(client=OrcaClient(runner=lambda *a, **k: None))
    decision = runtime.verify(
        OrcaVerificationInput(
            task_id="t1",
            action_category="code_edit",
            tests_passed=True,
            policy_passed=True,
            artifacts_complete=True,
            worker_claimed_complete=True,
        )
    )

    assert decision.verified is True
    assert decision.promotion_authority is False


def test_failed_tests_block_verification_even_when_worker_claims_done():
    runtime = HermesOrcaRuntime(client=OrcaClient(runner=lambda *a, **k: None))
    decision = runtime.verify(
        OrcaVerificationInput(
            task_id="t1",
            action_category="code_edit",
            tests_passed=False,
            policy_passed=True,
            artifacts_complete=True,
            worker_claimed_complete=True,
        )
    )

    assert decision.verified is False
    assert decision.promotion_authority is False
