from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Mapping
from uuid import uuid4

from .contracts import EconomicMode, TransactionEnvelope, TreasuryBucket, as_decimal, utc_now


def _secret_bytes(secret: bytes | str) -> bytes:
    value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if len(value) < 16:
        raise ValueError("authority_secret must contain at least 16 bytes")
    return value


def _normalized_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _envelope_digest(envelope: TransactionEnvelope) -> str:
    payload = json.dumps(
        envelope.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _mac(secret: bytes, purpose: str, payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        {"purpose": purpose, **dict(payload)},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hmac.new(secret, encoded, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class AuthorityPolicy:
    policy_revision: str
    registered_live_categories: frozenset[str]
    max_transaction_amount: Decimal
    bucket_limits: Mapping[TreasuryBucket, Decimal]
    simulated_auto_limit: Decimal
    sandbox_auto_limit: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "registered_live_categories", frozenset(self.registered_live_categories))
        object.__setattr__(self, "max_transaction_amount", as_decimal(self.max_transaction_amount))
        object.__setattr__(self, "simulated_auto_limit", as_decimal(self.simulated_auto_limit))
        object.__setattr__(self, "sandbox_auto_limit", as_decimal(self.sandbox_auto_limit))
        object.__setattr__(
            self,
            "bucket_limits",
            {TreasuryBucket(bucket): as_decimal(limit) for bucket, limit in self.bucket_limits.items()},
        )


@dataclass(frozen=True)
class AuthorizationGrant:
    grant_id: str
    transaction_id: str
    category: str
    policy_revision: str
    mode: EconomicMode
    envelope_digest: str
    expires_at: datetime
    attestation: str

    @classmethod
    def issue(
        cls,
        envelope: TransactionEnvelope,
        *,
        policy_revision: str,
        signing_secret: bytes | str,
        ttl_seconds: int = 300,
    ) -> "AuthorizationGrant":
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        secret = _secret_bytes(signing_secret)
        grant_id = str(uuid4())
        expires_at = utc_now() + timedelta(seconds=ttl_seconds)
        digest = _envelope_digest(envelope)
        payload = {
            "grant_id": grant_id,
            "transaction_id": envelope.transaction_id,
            "category": envelope.authority_category,
            "policy_revision": policy_revision,
            "mode": envelope.mode.value,
            "envelope_digest": digest,
            "expires_at": _normalized_datetime(expires_at).isoformat(),
        }
        return cls(
            grant_id=grant_id,
            transaction_id=envelope.transaction_id,
            category=envelope.authority_category,
            policy_revision=policy_revision,
            mode=envelope.mode,
            envelope_digest=digest,
            expires_at=expires_at,
            attestation=_mac(secret, "authorization-grant-v1", payload),
        )

    @property
    def expired(self) -> bool:
        return utc_now() >= _normalized_datetime(self.expires_at)

    def signing_payload(self) -> dict[str, object]:
        return {
            "grant_id": self.grant_id,
            "transaction_id": self.transaction_id,
            "category": self.category,
            "policy_revision": self.policy_revision,
            "mode": self.mode.value,
            "envelope_digest": self.envelope_digest,
            "expires_at": _normalized_datetime(self.expires_at).isoformat(),
        }


@dataclass(frozen=True)
class AuthorityDecision:
    allowed: bool
    authorization_required: bool
    category: str | None
    reason: str
    policy_revision: str
    transaction_id: str = ""
    mode: EconomicMode = EconomicMode.SIMULATED
    envelope_digest: str = ""
    attestation: str = ""

    def signing_payload(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "authorization_required": self.authorization_required,
            "category": self.category,
            "reason": self.reason,
            "policy_revision": self.policy_revision,
            "transaction_id": self.transaction_id,
            "mode": self.mode.value,
            "envelope_digest": self.envelope_digest,
        }


class FinancialAuthority:
    """Deterministic financial-policy evaluator with authenticated decisions.

    The owner-boundary secret never appears in grants, decisions, evidence, or
    adapter metadata. Model text and manually constructed dataclasses cannot
    authorize money movement because every accepted grant/decision must carry a
    valid HMAC bound to the exact transaction envelope and economic mode.
    """

    def __init__(
        self,
        policy: AuthorityPolicy,
        *,
        authority_secret: bytes | str | None = None,
    ) -> None:
        self.policy = policy
        # An ephemeral key is safe for simulated/sandbox-only callers. LIVE
        # grants must be issued by a boundary holding this same secret.
        self._authority_secret = _secret_bytes(authority_secret or secrets.token_bytes(32))

    def __repr__(self) -> str:
        return f"FinancialAuthority(policy_revision={self.policy.policy_revision!r}, authority_secret='[REDACTED]')"

    def _decision(
        self,
        envelope: TransactionEnvelope,
        *,
        allowed: bool,
        authorization_required: bool,
        reason: str,
    ) -> AuthorityDecision:
        digest = _envelope_digest(envelope)
        unsigned = AuthorityDecision(
            allowed=allowed,
            authorization_required=authorization_required,
            category=envelope.authority_category,
            reason=reason,
            policy_revision=self.policy.policy_revision,
            transaction_id=envelope.transaction_id,
            mode=envelope.mode,
            envelope_digest=digest,
        )
        return AuthorityDecision(
            **{**unsigned.__dict__, "attestation": _mac(self._authority_secret, "authority-decision-v1", unsigned.signing_payload())}
        )

    def _grant_signature_valid(self, grant: AuthorizationGrant) -> bool:
        expected = _mac(self._authority_secret, "authorization-grant-v1", grant.signing_payload())
        return hmac.compare_digest(expected, grant.attestation)

    def validate_decision(
        self,
        envelope: TransactionEnvelope,
        decision: AuthorityDecision | object,
    ) -> bool:
        if not isinstance(decision, AuthorityDecision):
            return False
        if decision.transaction_id != envelope.transaction_id:
            return False
        if decision.mode is not envelope.mode:
            return False
        if decision.category != envelope.authority_category:
            return False
        if decision.policy_revision != self.policy.policy_revision:
            return False
        if decision.envelope_digest != _envelope_digest(envelope):
            return False
        expected = _mac(self._authority_secret, "authority-decision-v1", decision.signing_payload())
        return hmac.compare_digest(expected, decision.attestation)

    def evaluate(
        self,
        envelope: TransactionEnvelope,
        *,
        grant: AuthorizationGrant | object | None = None,
    ) -> AuthorityDecision:
        category = envelope.authority_category
        revision = self.policy.policy_revision

        if envelope.expired:
            return self._decision(envelope, allowed=False, authorization_required=False, reason="transaction_expired")
        if envelope.amount > self.policy.max_transaction_amount:
            return self._decision(envelope, allowed=False, authorization_required=False, reason="transaction_limit_exceeded")
        bucket_limit = self.policy.bucket_limits.get(envelope.bucket)
        if bucket_limit is not None and envelope.amount > bucket_limit:
            return self._decision(envelope, allowed=False, authorization_required=False, reason="bucket_limit_exceeded")

        if envelope.mode is EconomicMode.SIMULATED:
            if envelope.amount > self.policy.simulated_auto_limit:
                return self._decision(envelope, allowed=False, authorization_required=False, reason="simulated_limit_exceeded")
            return self._decision(envelope, allowed=True, authorization_required=False, reason="allowed")

        if envelope.mode is EconomicMode.SANDBOX:
            if envelope.amount > self.policy.sandbox_auto_limit:
                return self._decision(envelope, allowed=False, authorization_required=False, reason="sandbox_limit_exceeded")
            return self._decision(envelope, allowed=True, authorization_required=False, reason="allowed")

        if category not in self.policy.registered_live_categories:
            return self._decision(envelope, allowed=False, authorization_required=False, reason="category_not_registered")

        if not isinstance(grant, AuthorizationGrant):
            return self._decision(envelope, allowed=False, authorization_required=True, reason="grant_required")
        if grant.expired:
            return self._decision(envelope, allowed=False, authorization_required=True, reason="grant_expired")
        if grant.transaction_id != envelope.transaction_id:
            return self._decision(envelope, allowed=False, authorization_required=True, reason="grant_transaction_mismatch")
        if grant.category != category:
            return self._decision(envelope, allowed=False, authorization_required=True, reason="grant_category_mismatch")
        if grant.policy_revision != revision:
            return self._decision(envelope, allowed=False, authorization_required=True, reason="grant_policy_mismatch")
        if grant.mode is not envelope.mode:
            return self._decision(envelope, allowed=False, authorization_required=True, reason="grant_mode_mismatch")
        if grant.envelope_digest != _envelope_digest(envelope):
            return self._decision(envelope, allowed=False, authorization_required=True, reason="grant_envelope_mismatch")
        if not self._grant_signature_valid(grant):
            return self._decision(envelope, allowed=False, authorization_required=True, reason="grant_signature_invalid")
        return self._decision(envelope, allowed=True, authorization_required=False, reason="allowed")
