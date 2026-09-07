from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ModelCandidate:
    provider: str
    model_id: str
    context_window: int
    max_output_tokens: int
    capabilities: frozenset[str]
    thinking_levels: frozenset[str]
    default_thinking_level: str
    evaluation_only: bool = True
    production_default: bool = False

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model_id.strip():
            raise ValueError("provider and model_id are required")
        if self.context_window <= 0 or self.max_output_tokens <= 0:
            raise ValueError("model token limits must be positive")
        if self.default_thinking_level not in self.thinking_levels:
            raise ValueError("default thinking level must be supported")
        if self.evaluation_only and self.production_default:
            raise ValueError("an evaluation-only model cannot be a production default")

    def provider_metadata(self) -> Mapping[str, object]:
        return {
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "thinking_levels": tuple(sorted(self.thinking_levels)),
            "default_thinking_level": self.default_thinking_level,
            "capabilities": tuple(sorted(self.capabilities)),
            "evaluation_only": self.evaluation_only,
            "production_default": self.production_default,
        }


GEMINI_3_8_FLASH = ModelCandidate(
    provider="google",
    model_id="gemini-3.8-flash",
    context_window=1_048_576,
    max_output_tokens=65_536,
    capabilities=frozenset(
        {
            "caching",
            "code_execution",
            "computer_use_preview",
            "file_search",
            "function_calling",
            "search_grounding",
            "structured_outputs",
            "thinking",
            "url_context",
        }
    ),
    thinking_levels=frozenset({"low", "medium", "high"}),
    default_thinking_level="medium",
    evaluation_only=True,
    production_default=False,
)


EVALUATION_CANDIDATES: tuple[ModelCandidate, ...] = (GEMINI_3_8_FLASH,)
