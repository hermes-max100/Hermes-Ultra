from __future__ import annotations

from hermes_ultra.model_candidates import GEMINI_3_8_FLASH
from hermes_ultra.provider_runtime import ProviderRequestPolicy


def test_gemini_3_8_flash_is_evaluation_only_with_official_limits() -> None:
    candidate = GEMINI_3_8_FLASH

    assert candidate.provider == "google"
    assert candidate.model_id == "gemini-3.8-flash"
    assert candidate.evaluation_only is True
    assert candidate.production_default is False
    assert candidate.context_window == 1_048_576
    assert candidate.max_output_tokens == 65_536
    assert candidate.default_thinking_level == "medium"
    assert candidate.thinking_levels == frozenset({"low", "medium", "high"})
    assert "function_calling" in candidate.capabilities
    assert "code_execution" in candidate.capabilities
    assert "computer_use_preview" in candidate.capabilities


def test_gemini_candidate_metadata_plugs_into_provider_limit_policy() -> None:
    candidate = GEMINI_3_8_FLASH
    policy = ProviderRequestPolicy()

    limits = policy.resolve_limits(
        provider=candidate.provider,
        model=candidate.model_id,
        model_metadata=candidate.provider_metadata(),
    )

    assert limits.context_window == 1_048_576
    assert limits.max_output_tokens == 65_536
    assert limits.source == "provider_model_metadata"
