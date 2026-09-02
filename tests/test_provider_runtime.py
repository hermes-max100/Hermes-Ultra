from hermes_ultra.provider_runtime import ProviderRequestPolicy, RequestLimits


def test_cloud_policy_ignores_local_ollama_num_ctx_and_uses_provider_scope():
    policy = ProviderRequestPolicy()
    limits = policy.resolve_limits(
        provider="openai",
        model="example-cloud",
        model_metadata={"context_window": 200000, "max_output_tokens": 12000},
        local_runtime_settings={"ollama_num_ctx": 49152},
    )
    assert limits.context_window == 200000
    assert limits.max_output_tokens == 12000
    assert limits.source == "provider_model_metadata"


def test_local_policy_may_use_local_num_ctx_when_provider_metadata_absent():
    policy = ProviderRequestPolicy(local_providers={"onith", "ollama"})
    limits = policy.resolve_limits(
        provider="onith",
        model="local-model",
        model_metadata={},
        local_runtime_settings={"ollama_num_ctx": 32768},
    )
    assert limits.context_window == 32768
    assert limits.source == "local_runtime"


def test_retry_payload_applies_corrected_output_cap_not_just_calculates_it():
    policy = ProviderRequestPolicy()
    original = {"model": "x", "messages": [], "max_tokens": 8192}
    retry = policy.build_retry_payload(
        original,
        error_text="max_tokens must be less than or equal to 4096",
        limits=RequestLimits(context_window=128000, max_output_tokens=8192, source="test"),
    )
    assert retry is not original
    assert retry["max_tokens"] == 4096
    assert original["max_tokens"] == 8192


def test_retry_without_explicit_provider_limit_reduces_cap_deterministically():
    policy = ProviderRequestPolicy()
    retry = policy.build_retry_payload(
        {"model": "x", "messages": [], "max_tokens": 6000},
        error_text="request exceeds model context length",
        limits=RequestLimits(context_window=100000, max_output_tokens=None, source="test"),
    )
    assert retry["max_tokens"] == 3000
