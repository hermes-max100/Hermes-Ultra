from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping

from .contracts import EconomicMode, ExperimentStatus, TreasuryBucket, as_decimal


@dataclass(frozen=True)
class ExperimentState:
    experiment_id: str
    strategy_id: str
    status: ExperimentStatus = ExperimentStatus.PLANNED
    reserved_budget: Decimal = Decimal("0")
    realized_revenue: Decimal = Decimal("0")
    realized_cost: Decimal = Decimal("0")

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "strategy_id": self.strategy_id,
            "status": self.status.value,
            "reserved_budget": str(self.reserved_budget),
            "realized_revenue": str(self.realized_revenue),
            "realized_cost": str(self.realized_cost),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ExperimentState":
        return cls(
            experiment_id=str(payload["experiment_id"]),
            strategy_id=str(payload["strategy_id"]),
            status=ExperimentStatus(str(payload["status"])),
            reserved_budget=as_decimal(payload.get("reserved_budget", "0")),
            realized_revenue=as_decimal(payload.get("realized_revenue", "0")),
            realized_cost=as_decimal(payload.get("realized_cost", "0")),
        )


def _zero_balances() -> dict[TreasuryBucket, Decimal]:
    return {bucket: Decimal("0") for bucket in TreasuryBucket}


@dataclass
class EconomicState:
    mode: EconomicMode
    balances: dict[TreasuryBucket, Decimal] = field(default_factory=_zero_balances)
    experiments: dict[str, ExperimentState] = field(default_factory=dict)
    version: int = 1

    def __post_init__(self) -> None:
        normalized = _zero_balances()
        for bucket, value in self.balances.items():
            normalized[TreasuryBucket(bucket)] = as_decimal(value)
        self.balances = normalized

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "mode": self.mode.value,
            "balances": {bucket.value: str(self.balances[bucket]) for bucket in TreasuryBucket},
            "experiments": {
                experiment_id: experiment.to_dict()
                for experiment_id, experiment in sorted(self.experiments.items())
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "EconomicState":
        version = int(payload.get("version", 1))
        if version != 1:
            raise ValueError(f"unsupported economic state version: {version}")
        mode = EconomicMode(str(payload["mode"]))
        raw_balances = payload.get("balances", {})
        if not isinstance(raw_balances, Mapping):
            raise ValueError("balances must be a mapping")
        balances = {
            TreasuryBucket(str(bucket)): as_decimal(value)
            for bucket, value in raw_balances.items()
        }
        raw_experiments = payload.get("experiments", {})
        if not isinstance(raw_experiments, Mapping):
            raise ValueError("experiments must be a mapping")
        experiments = {
            str(experiment_id): ExperimentState.from_dict(experiment_payload)
            for experiment_id, experiment_payload in raw_experiments.items()
            if isinstance(experiment_payload, Mapping)
        }
        return cls(mode=mode, balances=balances, experiments=experiments, version=version)
