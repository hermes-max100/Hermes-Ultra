from __future__ import annotations

from hermes_ultra.contracts import CapabilityResult, FailureClass


def test_success_result_is_not_blocking():
    result = CapabilityResult.success({"ok": True})

    assert result.ok is True
    assert result.blocking is False
    assert result.failure_class is None
    assert result.value == {"ok": True}


def test_recoverable_failure_is_not_blocking_when_fallback_exists():
    result = CapabilityResult.failure(
        FailureClass.UPSTREAM_UNAVAILABLE,
        "primary down",
        recoverable=True,
    )

    assert result.ok is False
    assert result.recoverable is True
    assert result.blocking is False
    assert result.failure_class is FailureClass.UPSTREAM_UNAVAILABLE


def test_nonrecoverable_failure_is_blocking():
    result = CapabilityResult.failure(
        FailureClass.POLICY_BLOCKED,
        "explicit policy block",
        recoverable=False,
    )

    assert result.blocking is True
