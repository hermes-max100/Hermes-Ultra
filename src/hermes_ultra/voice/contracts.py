from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

from ..contracts import CapabilityResult
from .model import CallContext


@dataclass(frozen=True)
class VoiceProviderEvent:
    call_id: str
    sequence: int
    kind: str
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.call_id.strip() or not self.kind.strip():
            raise ValueError("call_id and kind are required")
        if self.sequence < 0:
            raise ValueError("sequence cannot be negative")


@runtime_checkable
class RealtimeVoiceProvider(Protocol):
    """Provider boundary; Hermes remains policy and routing authority."""

    provider_id: str

    def start_call(self, context: CallContext) -> CapabilityResult[str]: ...

    def next_event(self, call_id: str) -> CapabilityResult[VoiceProviderEvent]: ...

    def cancel_response(self, call_id: str) -> CapabilityResult[None]: ...

    def end_call(self, call_id: str) -> CapabilityResult[None]: ...


@runtime_checkable
class StagedBusinessActionBackend(Protocol):
    """Stages a remote action; execution stays behind Hermes authority checks."""

    def stage_action(
        self,
        *,
        action: str,
        idempotency_key: str,
        payload: Mapping[str, object],
    ) -> CapabilityResult[str]: ...

