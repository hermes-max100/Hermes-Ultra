from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class FieldActionKind(str, Enum):
    UPDATE_CRM = "update_crm"
    SEND_CUSTOMER_MESSAGE = "send_customer_message"
    CLOSE_JOB = "close_job"
    SCHEDULE_FOLLOW_UP = "schedule_follow_up"
    ORDER_REPLACEMENT_PART = "order_replacement_part"
    REQUEST_REVIEW = "request_review"


class FieldVoicePlanStatus(str, Enum):
    CLARIFICATION_REQUIRED = "clarification_required"
    APPROVAL_REQUIRED = "approval_required"
    STAGED = "staged"


@dataclass(frozen=True)
class FieldActionRequest:
    kind: FieldActionKind
    payload: Mapping[str, object] = field(default_factory=dict)
    consequential: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", FieldActionKind(self.kind))
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class FieldVoiceCommand:
    command_id: str
    tenant_id: str
    technician_reference: str
    job_reference: str | None
    actions: tuple[FieldActionRequest, ...]
    ambiguity_reasons: tuple[str, ...] = ()
    approval_reference: str | None = None

    def __post_init__(self) -> None:
        if not self.command_id.strip() or not self.tenant_id.strip():
            raise ValueError("command_id and tenant_id are required")
        if not self.technician_reference.strip():
            raise ValueError("technician_reference is required")
        if not self.actions:
            raise ValueError("at least one action is required")
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(
            self,
            "ambiguity_reasons",
            tuple(item.strip() for item in self.ambiguity_reasons if item.strip()),
        )


@dataclass(frozen=True)
class FieldActionStep:
    kind: FieldActionKind
    idempotency_key: str
    payload: Mapping[str, object]
    approval_reference: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class FieldVoicePlan:
    command_id: str
    tenant_id: str
    status: FieldVoicePlanStatus
    clarification_questions: tuple[str, ...]
    steps: tuple[FieldActionStep, ...]


@dataclass(frozen=True)
class FieldActionReceipt:
    idempotency_key: str
    succeeded: bool
    external_reference: str | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        if self.succeeded and not (
            self.external_reference and self.external_reference.strip()
        ):
            raise ValueError("successful action requires an external_reference")
        if not self.succeeded and not (self.failure_reason and self.failure_reason.strip()):
            raise ValueError("failed action requires a failure_reason")


class FieldVoicePlanner:
    """Turns one technician utterance into approval-gated, staged business actions."""

    def plan(self, command: FieldVoiceCommand) -> FieldVoicePlan:
        questions = list(command.ambiguity_reasons)
        if not command.job_reference:
            questions.append("Which job should I update?")
        if any(item.kind is FieldActionKind.REQUEST_REVIEW for item in command.actions):
            review = next(
                item for item in command.actions if item.kind is FieldActionKind.REQUEST_REVIEW
            )
            if not review.payload.get("job_complete_verified"):
                questions.append("Has job completion been verified?")
            if not review.payload.get("payment_verified"):
                questions.append("Has payment been verified?")
        if questions:
            return FieldVoicePlan(
                command.command_id,
                command.tenant_id,
                FieldVoicePlanStatus.CLARIFICATION_REQUIRED,
                tuple(dict.fromkeys(questions)),
                (),
            )
        if (
            any(item.consequential for item in command.actions)
            and not command.approval_reference
        ):
            return FieldVoicePlan(
                command.command_id,
                command.tenant_id,
                FieldVoicePlanStatus.APPROVAL_REQUIRED,
                ("Approve the requested business actions before execution.",),
                (),
            )
        steps = tuple(
            FieldActionStep(
                kind=item.kind,
                idempotency_key=f"field:{command.command_id}:{index}:{item.kind.value}",
                payload={
                    **item.payload,
                    "tenant_id": command.tenant_id,
                    "technician_reference": command.technician_reference,
                    "job_reference": command.job_reference,
                },
                approval_reference=(command.approval_reference if item.consequential else None),
            )
            for index, item in enumerate(command.actions)
        )
        return FieldVoicePlan(
            command.command_id,
            command.tenant_id,
            FieldVoicePlanStatus.STAGED,
            (),
            steps,
        )
