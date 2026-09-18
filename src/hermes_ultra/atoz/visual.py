from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class VisualObservation:
    asset_id: str
    source_case_id: str
    provenance_reference: str
    observed_details: tuple[str, ...]
    inferred_details: tuple[str, ...] = ()
    equipment_identifier: str | None = None
    equipment_identifier_confidence: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.asset_id.strip() or not self.source_case_id.strip() or not self.provenance_reference.strip():
            raise ValueError("asset_id, source_case_id, and provenance_reference are required")
        if self.equipment_identifier_confidence is not None:
            confidence = Decimal(str(self.equipment_identifier_confidence))
            if not Decimal("0") <= confidence <= Decimal("1"):
                raise ValueError("equipment_identifier_confidence must be between 0 and 1")
            object.__setattr__(self, "equipment_identifier_confidence", confidence)

    @property
    def equipment_confirmation_required(self) -> bool:
        if self.equipment_identifier is None:
            return bool(self.inferred_details)
        if self.equipment_identifier_confidence is None:
            return True
        return self.equipment_identifier_confidence < Decimal("0.90")


@dataclass(frozen=True)
class VisualJobPacketExtension:
    schema_version: str
    case_id: str
    observations: tuple[VisualObservation, ...]
    confirmation_required: bool


def build_visual_extension(case_id: str, observations: tuple[VisualObservation, ...]) -> VisualJobPacketExtension:
    if not case_id.strip():
        raise ValueError("case_id is required")
    if not observations:
        raise ValueError("at least one visual observation is required")
    if any(item.source_case_id != case_id for item in observations):
        raise ValueError("cross-case visual observation rejected")
    return VisualJobPacketExtension("atoz-visual-job-packet-v1", case_id, observations, any(item.equipment_confirmation_required for item in observations))
