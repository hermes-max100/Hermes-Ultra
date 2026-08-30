from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hermes_ultra.delegated_identity import CredentialReference, DelegatedIdentity


def root_identity() -> DelegatedIdentity:
    return DelegatedIdentity.root(
        owner="owner",
        subject="hermes-core",
        capabilities={"browser.read", "browser.write", "repo.read"},
        profiles={"coding", "research"},
        providers={"playwright", "github"},
        credentials={CredentialReference("github", "vault://github/hermes")},
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        task_id="task-1",
    )


def test_root_identity_serializes_references_not_secrets() -> None:
    identity = root_identity()
    meta = identity.to_mcp_meta()["com.hermes.ultra/delegatedIdentity"]
    assert meta["subject"] == "hermes-core"
    assert meta["credentialRefs"] == [{"provider": "github", "reference": "vault://github/hermes"}]


def test_delegate_can_only_narrow_scope() -> None:
    child = root_identity().delegate(
        subject="browser-worker",
        capabilities={"browser.read"},
        profiles={"coding"},
        providers={"playwright"},
        credentials=(),
    )
    assert child.capabilities == frozenset({"browser.read"})
    assert child.delegated_by == "hermes-core"


def test_delegate_cannot_widen_capabilities() -> None:
    with pytest.raises(PermissionError, match="widen capabilities"):
        root_identity().delegate(subject="child", capabilities={"browser.read", "financial.transfer"})


def test_delegate_cannot_widen_provider_or_profile() -> None:
    with pytest.raises(PermissionError, match="widen providers"):
        root_identity().delegate(subject="child", providers={"playwright", "alpaca"})
    with pytest.raises(PermissionError, match="widen profiles"):
        root_identity().delegate(subject="child", profiles={"coding", "trading"})


def test_delegate_cannot_add_credentials_or_extend_expiry() -> None:
    identity = root_identity()
    with pytest.raises(PermissionError, match="credential"):
        identity.delegate(
            subject="child",
            credentials={CredentialReference("aws", "vault://aws/prod")},
        )
    with pytest.raises(PermissionError, match="extend expiry"):
        identity.delegate(subject="child", expires_at=identity.expires_at + timedelta(seconds=1))


def test_delegation_preserves_bound_task() -> None:
    with pytest.raises(PermissionError, match="task scope"):
        root_identity().delegate(subject="child", task_id="different-task")
