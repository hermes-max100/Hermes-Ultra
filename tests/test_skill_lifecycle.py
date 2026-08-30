from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_ultra.skill_lifecycle import (
    DEFAULT_DISCOVERY_SOURCES,
    AuthorityProfile,
    CapabilityDescriptor,
    CapabilityDeduplicator,
    CoderEvalAdapter,
    EvaluationMetrics,
    EvaluationReport,
    ExternalToolResult,
    ImmutableReceiptStore,
    LifecycleController,
    LifecycleState,
    PromotionPolicy,
    Provenance,
    SkillCandidate,
    SkillValidatorAdapter,
    ValidationReport,
)
from hermes_ultra.contracts import FailureClass


def _provenance() -> Provenance:
    return Provenance(
        repository="https://github.com/example/skill",
        commit_sha="a" * 40,
        license="MIT",
        discovered_from="awesome-codex-skills",
    )


def _authority(**overrides: bool) -> AuthorityProfile:
    values = {
        "network": False,
        "filesystem_read": True,
        "filesystem_write": False,
        "shell": False,
        "git_write": False,
        "credential_access": False,
        "external_send": False,
        "financial": False,
    }
    values.update(overrides)
    return AuthorityProfile(**values)


def _validation(**overrides: bool) -> ValidationReport:
    values = {
        "structural": True,
        "links": True,
        "contamination": True,
        "secret_scan": True,
        "dependency_scan": True,
        "license_check": True,
        "provenance_check": True,
        "permissions_declared": True,
        "evidence_contract": True,
        "rollback_defined": True,
    }
    values.update(overrides)
    return ValidationReport(**values)


def _evaluation(
    *,
    baseline_score: float = 0.80,
    candidate_score: float = 0.95,
    baseline_tokens: float = 1000.0,
    candidate_tokens: float = 800.0,
) -> EvaluationReport:
    return EvaluationReport(
        baseline=EvaluationMetrics(
            score=baseline_score,
            success_rate=0.95,
            tests_pass_rate=1.0,
            wrong_file_edit_rate=0.0,
            regression_rate=0.0,
            evidence_complete=True,
            latency_seconds=10.0,
            tool_calls=8.0,
            tokens=baseline_tokens,
        ),
        candidate=EvaluationMetrics(
            score=candidate_score,
            success_rate=0.98,
            tests_pass_rate=1.0,
            wrong_file_edit_rate=0.0,
            regression_rate=0.0,
            evidence_complete=True,
            latency_seconds=9.0,
            tool_calls=7.0,
            tokens=candidate_tokens,
        ),
        evaluator="coder-eval",
        evidence_uri="runs/skill-eval/run.json",
    )


def _candidate(**overrides) -> SkillCandidate:
    values = {
        "candidate_id": "cand_001",
        "name": "systematic-debugging",
        "provenance": _provenance(),
        "authority": _authority(),
        "capability": CapabilityDescriptor(
            capability_id="systematic-debugging",
            capabilities=frozenset({"coding", "debugging"}),
            tools=frozenset({"shell", "files"}),
            outputs=frozenset({"patch", "diagnosis"}),
        ),
        "state": LifecycleState.CANDIDATE,
    }
    values.update(overrides)
    return SkillCandidate(**values)


def test_provenance_requires_full_commit_sha() -> None:
    with pytest.raises(ValueError, match="40-character"):
        Provenance(
            repository="https://github.com/example/skill",
            commit_sha="abc123",
            license="MIT",
            discovered_from="catalog",
        )


def test_validation_report_fails_closed_on_any_missing_gate() -> None:
    report = _validation(secret_scan=False)

    assert not report.passed
    assert "secret_scan" in report.failed_gates


def test_skill_validator_adapter_uses_strict_check_without_shell(tmp_path: Path) -> None:
    calls = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="clean", stderr="")

    adapter = SkillValidatorAdapter(binary="skill-validator", runner=runner)
    result = adapter.validate(tmp_path)

    assert result.ok
    assert isinstance(result.value, ExternalToolResult)
    assert result.value.passed
    assert calls[0][0] == ["skill-validator", "check", "--strict", str(tmp_path)]
    assert "shell" not in calls[0][1]


def test_skill_validator_nonzero_exit_fails_closed(tmp_path: Path) -> None:
    def runner(args, **kwargs):
        return SimpleNamespace(returncode=2, stdout="warnings", stderr="")

    adapter = SkillValidatorAdapter(binary="skill-validator", runner=runner)
    result = adapter.validate(tmp_path)

    assert not result.ok
    assert result.failure_class is FailureClass.TEST_FAILED
    assert result.metadata["returncode"] == 2


def test_coder_eval_adapter_disables_telemetry_and_uses_plan(tmp_path: Path) -> None:
    task = tmp_path / "task.yaml"
    task.write_text("task_id: x\n", encoding="utf-8")
    calls = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="valid", stderr="")

    adapter = CoderEvalAdapter(binary="coder-eval", runner=runner)
    result = adapter.plan(task)

    assert result.ok
    assert calls[0][0] == ["coder-eval", "plan", str(task)]
    assert calls[0][1]["env"]["TELEMETRY_ENABLED"] == "false"
    assert "shell" not in calls[0][1]


def test_coder_eval_run_is_fail_closed_on_nonzero_exit(tmp_path: Path) -> None:
    task = tmp_path / "task.yaml"
    task.write_text("task_id: x\n", encoding="utf-8")

    def runner(args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="failed")

    adapter = CoderEvalAdapter(binary="coder-eval", runner=runner)
    result = adapter.run(task)

    assert not result.ok
    assert result.failure_class is FailureClass.BENCHMARK_REGRESSION


def test_capability_deduplicator_blocks_near_exact_duplicate() -> None:
    dedupe = CapabilityDeduplicator(duplicate_threshold=0.90, review_threshold=0.60)
    candidate = _candidate().capability
    existing = CapabilityDescriptor(
        capability_id="debugger-v1",
        capabilities=frozenset({"coding", "debugging"}),
        tools=frozenset({"shell", "files"}),
        outputs=frozenset({"patch", "diagnosis"}),
    )

    decision = dedupe.compare(candidate, [existing])

    assert decision.blocked
    assert decision.nearest_capability_id == "debugger-v1"
    assert decision.overlap_score == pytest.approx(1.0)


def test_capability_deduplicator_flags_partial_overlap_for_review() -> None:
    dedupe = CapabilityDeduplicator(duplicate_threshold=0.90, review_threshold=0.45)
    candidate = _candidate().capability
    existing = CapabilityDescriptor(
        capability_id="generic-coder",
        capabilities=frozenset({"coding"}),
        tools=frozenset({"files"}),
        outputs=frozenset({"patch"}),
    )

    decision = dedupe.compare(candidate, [existing])

    assert not decision.blocked
    assert decision.review_required
    assert 0.45 <= decision.overlap_score < 0.90


def test_promotion_rejects_candidate_when_validation_incomplete() -> None:
    policy = PromotionPolicy()
    decision = policy.evaluate(
        candidate=_candidate(),
        validation=_validation(license_check=False),
        evaluation=_evaluation(),
        dedupe=None,
    )

    assert not decision.promoted
    assert decision.target_state is LifecycleState.CANDIDATE
    assert "license_check" in decision.reason


def test_promotion_rejects_quality_regression() -> None:
    policy = PromotionPolicy()
    report = _evaluation(baseline_score=0.95, candidate_score=0.90)
    decision = policy.evaluate(
        candidate=_candidate(),
        validation=_validation(),
        evaluation=report,
        dedupe=None,
    )

    assert not decision.promoted
    assert "strictly improve" in decision.reason


def test_promotion_accepts_strict_improvement_to_trusted_only() -> None:
    policy = PromotionPolicy()
    decision = policy.evaluate(
        candidate=_candidate(),
        validation=_validation(),
        evaluation=_evaluation(),
        dedupe=None,
    )

    assert decision.promoted
    assert decision.target_state is LifecycleState.TRUSTED
    assert not decision.activation_allowed


def test_duplicate_decision_blocks_promotion_even_with_good_eval() -> None:
    dedupe = CapabilityDeduplicator().compare(
        _candidate().capability,
        [_candidate().capability],
    )
    decision = PromotionPolicy().evaluate(
        candidate=_candidate(),
        validation=_validation(),
        evaluation=_evaluation(),
        dedupe=dedupe,
    )

    assert not decision.promoted
    assert "duplicate" in decision.reason.lower()


def test_install_disabled_requires_review_approval() -> None:
    controller = LifecycleController()
    candidate = _candidate(state=LifecycleState.TRUSTED)

    with pytest.raises(PermissionError, match="review approval"):
        controller.transition(candidate, LifecycleState.INSTALLED_DISABLED)

    transitioned, receipt = controller.transition(
        candidate,
        LifecycleState.INSTALLED_DISABLED,
        review_approved=True,
    )
    assert transitioned.state is LifecycleState.INSTALLED_DISABLED
    assert receipt.to_state is LifecycleState.INSTALLED_DISABLED


def test_transition_cannot_skip_canary() -> None:
    controller = LifecycleController()
    candidate = _candidate(state=LifecycleState.INSTALLED_DISABLED)

    with pytest.raises(ValueError, match="illegal lifecycle transition"):
        controller.transition(
            candidate,
            LifecycleState.ACTIVE,
            review_approved=True,
            canary_passed=True,
        )


def test_consequential_authority_requires_explicit_approval_before_canary() -> None:
    controller = LifecycleController()
    candidate = _candidate(
        state=LifecycleState.INSTALLED_DISABLED,
        authority=_authority(external_send=True),
    )

    with pytest.raises(PermissionError, match="consequential authority"):
        controller.transition(
            candidate,
            LifecycleState.CANARY,
            review_approved=True,
        )

    transitioned, _ = controller.transition(
        candidate,
        LifecycleState.CANARY,
        review_approved=True,
        authority_approved=True,
    )
    assert transitioned.state is LifecycleState.CANARY


def test_activation_requires_canary_pass_and_rollback_readiness() -> None:
    controller = LifecycleController()
    candidate = _candidate(state=LifecycleState.CANARY)

    with pytest.raises(PermissionError, match="canary pass"):
        controller.transition(candidate, LifecycleState.ACTIVE, rollback_ready=True)

    with pytest.raises(PermissionError, match="rollback readiness"):
        controller.transition(candidate, LifecycleState.ACTIVE, canary_passed=True)

    active, _ = controller.transition(
        candidate,
        LifecycleState.ACTIVE,
        canary_passed=True,
        rollback_ready=True,
    )
    assert active.state is LifecycleState.ACTIVE


def test_rollback_is_allowed_from_canary_and_active() -> None:
    controller = LifecycleController()

    for state in (LifecycleState.CANARY, LifecycleState.ACTIVE):
        rolled_back, receipt = controller.transition(
            _candidate(state=state),
            LifecycleState.ROLLED_BACK,
        )
        assert rolled_back.state is LifecycleState.ROLLED_BACK
        assert receipt.to_state is LifecycleState.ROLLED_BACK


def test_receipt_hash_verifies_and_tampering_is_detected() -> None:
    controller = LifecycleController(clock=lambda: "2026-08-27T18:00:00Z")
    _, receipt = controller.transition(
        _candidate(state=LifecycleState.TRUSTED),
        LifecycleState.INSTALLED_DISABLED,
        review_approved=True,
    )

    assert receipt.verify()

    payload = receipt.to_dict()
    payload["reason"] = "tampered"
    assert not receipt.verify_payload(payload)


def test_immutable_receipt_store_is_create_only(tmp_path: Path) -> None:
    controller = LifecycleController(clock=lambda: "2026-08-27T18:00:00Z")
    _, receipt = controller.transition(
        _candidate(state=LifecycleState.TRUSTED),
        LifecycleState.INSTALLED_DISABLED,
        review_approved=True,
    )
    store = ImmutableReceiptStore(tmp_path)

    path = store.persist(receipt)
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["receipt_hash"] == receipt.receipt_hash

    with pytest.raises(FileExistsError):
        store.persist(receipt)


def test_default_discovery_sources_are_never_trusted_or_active() -> None:
    names = {source.name for source in DEFAULT_DISCOVERY_SOURCES}

    assert {
        "awesome-codex-skills",
        "awesome-codex-subagents",
        "awesome-mcp-servers",
        "awesome",
    }.issubset(names)
    assert all(source.discovery_only for source in DEFAULT_DISCOVERY_SOURCES)
    assert all(not source.auto_install for source in DEFAULT_DISCOVERY_SOURCES)
