from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, Mapping, TypeVar

T = TypeVar("T")


class FailureClass(str, Enum):
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_FAILED = "AUTH_FAILED"
    AUTHORITY_REQUIRED = "AUTHORITY_REQUIRED"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    DUPLICATE_TRANSACTION = "DUPLICATE_TRANSACTION"
    TRANSACTION_EXPIRED = "TRANSACTION_EXPIRED"
    ADAPTER_REJECTED = "ADAPTER_REJECTED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    HEALTHCHECK_FAILED = "HEALTHCHECK_FAILED"
    WORKER_FAILED = "WORKER_FAILED"
    TEST_FAILED = "TEST_FAILED"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    PROVENANCE_FAILED = "PROVENANCE_FAILED"
    BENCHMARK_REGRESSION = "BENCHMARK_REGRESSION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CapabilityResult(Generic[T]):
    ok: bool
    value: T | None = None
    failure_class: FailureClass | None = None
    message: str = ""
    recoverable: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def blocking(self) -> bool:
        return not self.ok and not self.recoverable

    @classmethod
    def success(
        cls,
        value: T,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> "CapabilityResult[T]":
        return cls(
            ok=True,
            value=value,
            metadata={} if metadata is None else dict(metadata),
        )

    @classmethod
    def failure(
        cls,
        failure_class: FailureClass,
        message: str,
        *,
        recoverable: bool,
        metadata: Mapping[str, object] | None = None,
    ) -> "CapabilityResult[T]":
        return cls(
            ok=False,
            failure_class=failure_class,
            message=message,
            recoverable=recoverable,
            metadata={} if metadata is None else dict(metadata),
        )
