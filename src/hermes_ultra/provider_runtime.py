from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Mapping


_LIMIT_PATTERNS = (
    re.compile(r"(?i)max_tokens\s+must\s+be\s+less\s+than\s+or\s+equal\s+to\s+([0-9][0-9,]*)"),
    re.compile(r"(?i)max_output_tokens\s+must\s+be\s+less\s+than\s+or\s+equal\s+to\s+([0-9][0-9,]*)"),
    re.compile(r"(?i)maximum\s+output\s+tokens(?:\s+is|\s*:)?\s*([0-9][0-9,]*)"),
    re.compile(r"(?i)(?:max_tokens|max_output_tokens)[^0-9]{0,40}([0-9][0-9,]*)"),
)
_LIMIT_ERROR_RE = re.compile(
    r"(?i)(context\s+(?:length|window)|maximum\s+context|max_tokens|max_output_tokens|output\s+token|token\s+limit)"
)


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _first_limit(metadata: Mapping[str, object], names: tuple[str, ...]) -> int | None:
    for name in names:
        value = _positive_int(metadata.get(name))
        if value is not None:
            return value
    return None


@dataclass(frozen=True)
class RequestLimits:
    context_window: int | None
    max_output_tokens: int | None
    source: str

    def to_dict(self) -> dict[str, object]:
        return {
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "source": self.source,
        }


class ProviderRequestPolicy:
    """Provider-scoped context/output limits and deterministic retry correction.

    Cloud routes never inherit local-runtime context knobs such as
    ``ollama_num_ctx``. Local providers may use those values only when explicit
    provider/model metadata is absent. Limit retries always return a new payload
    with the corrected cap applied, preventing a calculate-but-don't-use loop.
    """

    def __init__(self, *, local_providers: set[str] | None = None) -> None:
        self.local_providers = frozenset(
            item.lower() for item in (local_providers or {"local", "onith", "ollama"})
        )

    def resolve_limits(
        self,
        *,
        provider: str,
        model: str,
        model_metadata: Mapping[str, object] | None = None,
        local_runtime_settings: Mapping[str, object] | None = None,
    ) -> RequestLimits:
        del model  # model id is part of the caller's lookup key, not a fallback authority.
        metadata = model_metadata or {}
        context_window = _first_limit(
            metadata,
            ("context_window", "context_length", "max_context_tokens", "max_input_tokens"),
        )
        max_output = _first_limit(
            metadata,
            ("max_output_tokens", "output_token_limit", "max_completion_tokens"),
        )
        if context_window is not None or max_output is not None:
            return RequestLimits(context_window, max_output, "provider_model_metadata")

        if provider.lower() in self.local_providers:
            settings = local_runtime_settings or {}
            local_context = _first_limit(settings, ("ollama_num_ctx", "num_ctx", "context_window"))
            local_output = _first_limit(settings, ("max_output_tokens", "num_predict"))
            if local_context is not None or local_output is not None:
                return RequestLimits(local_context, local_output, "local_runtime")

        return RequestLimits(None, None, "provider_default")

    @staticmethod
    def is_limit_error(error_text: str) -> bool:
        return bool(_LIMIT_ERROR_RE.search(str(error_text or "")))

    @staticmethod
    def _explicit_limit(error_text: str) -> int | None:
        text = str(error_text or "")
        for pattern in _LIMIT_PATTERNS:
            match = pattern.search(text)
            if match:
                try:
                    value = int(match.group(1).replace(",", ""))
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    return value
        return None

    def build_retry_payload(
        self,
        payload: Mapping[str, Any],
        *,
        error_text: str,
        limits: RequestLimits,
    ) -> dict[str, Any]:
        if not self.is_limit_error(error_text):
            raise ValueError("retry correction requires a token/context limit error")

        retry = copy.deepcopy(dict(payload))
        field = "max_output_tokens" if "max_output_tokens" in retry else "max_tokens"
        current = _positive_int(retry.get(field))
        explicit = self._explicit_limit(error_text)

        candidates = [value for value in (explicit, limits.max_output_tokens) if value is not None]
        if current is not None and candidates:
            corrected = min([current, *candidates])
            if corrected >= current:
                corrected = max(1, current // 2)
        elif candidates:
            corrected = min(candidates)
        elif current is not None:
            corrected = max(1, current // 2)
        else:
            raise ValueError("cannot derive corrected output cap from limit error")

        retry[field] = corrected
        return retry

    def apply_limits(self, payload: Mapping[str, Any], limits: RequestLimits) -> dict[str, Any]:
        request = copy.deepcopy(dict(payload))
        if limits.max_output_tokens is not None and not any(
            name in request for name in ("max_tokens", "max_output_tokens")
        ):
            request["max_tokens"] = limits.max_output_tokens
        return request
