from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .model import VoiceCallState


class InvalidVoiceTransition(ValueError):
    pass


@dataclass(frozen=True)
class VoiceTransitionReceipt:
    sequence: int
    previous: VoiceCallState
    current: VoiceCallState
    reason: str


class VoiceCallStateMachine:
    """Deterministic, replayable call lifecycle with fail-closed transitions."""

    _ALLOWED: dict[VoiceCallState, frozenset[VoiceCallState]] = {
        VoiceCallState.INITIATED: frozenset(
            {VoiceCallState.CONNECTED, VoiceCallState.BLOCKED, VoiceCallState.ENDED}
        ),
        VoiceCallState.CONNECTED: frozenset(
            {VoiceCallState.DISCLOSED, VoiceCallState.BLOCKED, VoiceCallState.ENDED}
        ),
        VoiceCallState.DISCLOSED: frozenset(
            {
                VoiceCallState.QUALIFYING,
                VoiceCallState.HANDOFF,
                VoiceCallState.BLOCKED,
                VoiceCallState.ENDED,
            }
        ),
        VoiceCallState.QUALIFYING: frozenset(
            {
                VoiceCallState.ELIGIBLE,
                VoiceCallState.INCOMPLETE,
                VoiceCallState.HANDOFF,
                VoiceCallState.BLOCKED,
            }
        ),
        VoiceCallState.ELIGIBLE: frozenset(
            {VoiceCallState.BOOKING, VoiceCallState.INCOMPLETE, VoiceCallState.HANDOFF}
        ),
        VoiceCallState.BOOKING: frozenset(
            {VoiceCallState.BOOKED, VoiceCallState.INCOMPLETE, VoiceCallState.HANDOFF}
        ),
        VoiceCallState.BOOKED: frozenset({VoiceCallState.ENDED}),
        VoiceCallState.HANDOFF: frozenset({VoiceCallState.ENDED}),
        VoiceCallState.INCOMPLETE: frozenset({VoiceCallState.ENDED}),
        VoiceCallState.BLOCKED: frozenset({VoiceCallState.ENDED}),
        VoiceCallState.ENDED: frozenset(),
    }

    def __init__(self, state: VoiceCallState = VoiceCallState.INITIATED) -> None:
        self.state = VoiceCallState(state)
        self._receipts: list[VoiceTransitionReceipt] = []

    @property
    def receipts(self) -> tuple[VoiceTransitionReceipt, ...]:
        return tuple(self._receipts)

    def transition(self, current: VoiceCallState, *, reason: str) -> VoiceTransitionReceipt:
        target = VoiceCallState(current)
        if target not in self._ALLOWED[self.state]:
            raise InvalidVoiceTransition(f"cannot transition from {self.state.value} to {target.value}")
        if not reason.strip():
            raise ValueError("transition reason is required")
        receipt = VoiceTransitionReceipt(
            sequence=len(self._receipts),
            previous=self.state,
            current=target,
            reason=reason.strip(),
        )
        self.state = target
        self._receipts.append(receipt)
        return receipt

    @classmethod
    def replay(cls, receipts: Iterable[VoiceTransitionReceipt]) -> "VoiceCallStateMachine":
        machine = cls()
        for expected_sequence, receipt in enumerate(receipts):
            if receipt.sequence != expected_sequence or receipt.previous is not machine.state:
                raise InvalidVoiceTransition("transition receipts are not a valid ordered replay")
            replayed = machine.transition(receipt.current, reason=receipt.reason)
            if replayed != receipt:
                raise InvalidVoiceTransition("transition receipt changed during replay")
        return machine

