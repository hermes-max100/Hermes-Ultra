from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

_SUCCESS = frozenset({"success", "completed", "passed", "validated", "ok", "recovered", "resolved"})
_FAILURE = frozenset({"failed", "failure", "error", "blocked", "rejected", "timeout"})


def _action_signature(action: object) -> str:
    if isinstance(action, Mapping):
        for key in ("type", "capability", "tool", "operation", "name"):
            value = action.get(key)
            if value:
                return f"{key}:{value}"
        bounded = {str(key): action[key] for key in sorted(action, key=str) if str(key) not in {"timestamp", "duration_ms"}}
        return json.dumps(bounded, sort_keys=True, separators=(",", ":"), default=str)
    return str(action)


def _status(action: object) -> str:
    if not isinstance(action, Mapping):
        return ""
    return str(action.get("status") or action.get("result_status") or "").strip().lower()


def _entropy_bits(signatures: Sequence[str]) -> float:
    if not signatures:
        return 0.0
    counts = Counter(signatures)
    total = float(len(signatures))
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def _lz_complexity(signatures: Sequence[str]) -> int:
    """Small deterministic LZ76-style phrase count over action signatures."""
    if not signatures:
        return 0
    dictionary: set[tuple[str, ...]] = set()
    index = 0
    phrases = 0
    n = len(signatures)
    while index < n:
        length = 1
        while index + length <= n and tuple(signatures[index:index + length]) in dictionary:
            length += 1
        phrase = tuple(signatures[index:min(index + length, n)])
        dictionary.add(phrase)
        phrases += 1
        index += max(1, len(phrase))
    return phrases


@dataclass(frozen=True)
class TrajectoryMetrics:
    event_count: int
    unique_action_count: int
    success_ratio: float
    failure_ratio: float
    repetition_ratio: float
    entropy_bits: float
    normalized_entropy: float
    lz_complexity: int
    exploration_error: float
    exploitation_error: float
    policy_near_miss_ratio: float
    adaptation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrajectoryEvaluator:
    """External, autonomy-preserving evaluation of an execution trajectory.

    The evaluator emits adaptation signals only. It does not authorize actions,
    mutate lifecycle state, or introduce a human approval boundary. Loop/routing
    code can use the signals to adjust model/tool/context strategy automatically.
    """

    def __init__(
        self,
        *,
        exploitation_threshold: float = 0.60,
        exploration_threshold: float = 0.60,
    ) -> None:
        self.exploitation_threshold = float(exploitation_threshold)
        self.exploration_threshold = float(exploration_threshold)

    def evaluate(self, actions: Sequence[object]) -> TrajectoryMetrics:
        rows = list(actions)
        signatures = [_action_signature(action) for action in rows]
        n = len(rows)
        if n == 0:
            return TrajectoryMetrics(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, "continue")

        statuses = [_status(action) for action in rows]
        successes = sum(1 for status in statuses if status in _SUCCESS)
        failures = sum(1 for status in statuses if status in _FAILURE)
        success_ratio = successes / n
        failure_ratio = failures / n
        unique_count = len(set(signatures))
        unique_ratio = unique_count / n
        repetition_ratio = max(0.0, 1.0 - unique_ratio)
        entropy = _entropy_bits(signatures)
        entropy_ceiling = math.log2(n) if n > 1 else 0.0
        normalized_entropy = entropy / entropy_ceiling if entropy_ceiling else 0.0
        near_misses = sum(
            1
            for action in rows
            if isinstance(action, Mapping)
            and bool(action.get("policy_near_miss") or action.get("near_miss"))
        )
        policy_near_miss_ratio = near_misses / n

        exploration_error = min(1.0, unique_ratio * failure_ratio)
        exploitation_error = min(1.0, repetition_ratio * failure_ratio)

        if exploitation_error >= self.exploitation_threshold:
            adaptation = "reroute"
        elif exploration_error >= self.exploration_threshold:
            adaptation = "narrow"
        else:
            adaptation = "continue"

        return TrajectoryMetrics(
            event_count=n,
            unique_action_count=unique_count,
            success_ratio=round(success_ratio, 6),
            failure_ratio=round(failure_ratio, 6),
            repetition_ratio=round(repetition_ratio, 6),
            entropy_bits=round(entropy, 6),
            normalized_entropy=round(normalized_entropy, 6),
            lz_complexity=_lz_complexity(signatures),
            exploration_error=round(exploration_error, 6),
            exploitation_error=round(exploitation_error, 6),
            policy_near_miss_ratio=round(policy_near_miss_ratio, 6),
            adaptation=adaptation,
        )
