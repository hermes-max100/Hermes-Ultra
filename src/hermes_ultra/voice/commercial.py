from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .model import VoicePackage


@dataclass(frozen=True)
class VoiceOffer:
    package: VoicePackage
    monthly_fee: Decimal
    included_minutes: int
    overage_per_minute: Decimal
    capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "package", VoicePackage(self.package))
        object.__setattr__(self, "monthly_fee", Decimal(str(self.monthly_fee)))
        object.__setattr__(self, "overage_per_minute", Decimal(str(self.overage_per_minute)))
        if self.monthly_fee < 0 or self.overage_per_minute < 0:
            raise ValueError("prices cannot be negative")
        if self.included_minutes <= 0:
            raise ValueError("included_minutes must be positive")
        if not self.capabilities:
            raise ValueError("at least one capability is required")

    def estimate_monthly_total(self, used_minutes: int) -> Decimal:
        if used_minutes < 0:
            raise ValueError("used_minutes cannot be negative")
        overage_minutes = max(0, used_minutes - self.included_minutes)
        return self.monthly_fee + self.overage_per_minute * overage_minutes


def home_services_offers(
    *,
    receptionist_minutes: int,
    recovery_minutes: int,
    overage_per_minute: Decimal | str,
) -> tuple[VoiceOffer, VoiceOffer]:
    """Known package prices with caller-supplied usage caps and overage economics."""

    overage = Decimal(str(overage_per_minute))
    return (
        VoiceOffer(
            package=VoicePackage.RECEPTIONIST,
            monthly_fee=Decimal("499"),
            included_minutes=receptionist_minutes,
            overage_per_minute=overage,
            capabilities=("answer", "qualify", "book", "transfer"),
        ),
        VoiceOffer(
            package=VoicePackage.REVENUE_RECOVERY,
            monthly_fee=Decimal("749"),
            included_minutes=recovery_minutes,
            overage_per_minute=overage,
            capabilities=(
                "answer",
                "qualify",
                "book",
                "transfer",
                "recover_incomplete_calls",
                "crm_evidence",
                "outcome_attribution",
            ),
        ),
    )

