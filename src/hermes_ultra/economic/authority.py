from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Mapping
from uuid import uuid4

from .contracts import EconomicMode, TransactionEnvelope, TreasuryBucket, as_decimal, utc_now


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
    expires_at: datetime

    @classmethod
    def issue(
        cls,
        envelope: TransactionEnvelope,
        *,
        policy_revision: str,
        ttl_seconds: int = 300,
    ) -> "AuthorizationGrant":
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        return cls(
            grant_id=str(uuid4()),
            transaction_id=envelope.transaction_id,
            category=envelope.authority_category,
            policy_revision=policy_revision,
            expires_at=utc_now() + timedelta(seconds=ttl_seconds),
        )

    @property
    def expired(self) -> bool:
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return utc_now() >= expires_at


@dataclass(frozen=True)
class AuthorityDecision:
    allowed: bool
    authorization_required: bool
    category: str | None
    reason: str
    policy_revision: str


class FinancialAuthority:
    """Deterministic financial-policy evaluator; model text is never an authorization token."""

    def __init__(self, policy: AuthorityPolicy) -> None:
        self.policy = policy

    def evaluate(
        self,
        envelope: TransactionEnvelope,
        *,
        grant: AuthorizationGrant | object | None = None,
    ) -> AuthorityDecision:
        category = envelope.authority_category
        revision = self.policy.policy_revision

        if envelope.expired:
            return AuthorityDecision(False, False, category, "transaction_expired", revision)
        if envelope.amount > self.policy.max_transaction_amount:
            return AuthorityDecision(False, False, category, "transaction_limit_exceeded", revision)
        bucket_limit = self.policy.bucket_limits.get(envelope.bucket)
        if bucket_limit is not None and envelope.amount > bucket_limit:
            return AuthorityDecision(False, False, category, "bucket_limit_exceeded", revision)

        if envelope.mode is EconomicMode.SIMULATED:
            if envelope.amount > self.policy.simulated_auto_limit:
                return AuthorityDecision(False, False, category, "simulated_limit_exceeded", revision)
            return AuthorityDecision(True, False, category, "allowed", revision)

        if envelope.mode is EconomicMode.SANDBOX:
            if envelope.amount > self.policy.sandbox_auto_limit:
                return AuthorityDecision(False, False, category, "sandbox_limit_exceeded", revision)
            return AuthorityDecision(True, False, category, "allowed", revision)

        if category not in self.policy.registered_live_categories:
            return AuthorityDecision(False, False, category, "category_not_registered", revision)

        if not isinstance(grant, AuthorizationGrant):
            return AuthorityDecision(False, True, category, "grant_required", revision)
        if grant.expired:
            return AuthorityDecision(False, True, category, "grant_expired", revision)
        if grant.transaction_id != envelope.transaction_id:
            return AuthorityDecision(False, True, category, "grant_transaction_mismatch", revision)
        if grant.category != category:
            return AuthorityDecision(False, True, category, "grant_category_mismatch", revision)
        if grant.policy_revision != revision:
            return AuthorityDecision(False, True, category, "grant_policy_mismatch", revision)
        return AuthorityDecision(True, False, category, "allowed", revision)
