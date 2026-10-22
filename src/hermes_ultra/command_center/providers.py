"""Provider adapters for council members.

Credentials are read from the server environment by variable *name*; the value
never enters the store, the API or the browser. A member whose provider cannot
run reports ``available=False`` with a reason, and the council records that as
an offline notice instead of inventing a reply.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

# USD per million tokens (input, output) for models with published first-party
# pricing. Members can override with price_in_per_m / price_out_per_m.
CLAUDE_PRICING = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
# Models that accept the server-side refusal fallback in its "default" form.
CLAUDE_FALLBACK_MODELS = frozenset({"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"})
CLAUDE_FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str


@dataclass(frozen=True)
class ProviderReply:
    status: str  # ok | error | refused
    text: str
    model: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int | None = None


def estimate_cost(member: Mapping[str, Any], tokens_in: int | None, tokens_out: int | None) -> float | None:
    if tokens_in is None and tokens_out is None:
        return None
    price_in, price_out = member.get("price_in_per_m"), member.get("price_out_per_m")
    if price_in is None or price_out is None:
        default = CLAUDE_PRICING.get(str(member.get("model"))) if member.get("provider") == "anthropic" else None
        if default is None:
            return None
        price_in = default[0] if price_in is None else price_in
        price_out = default[1] if price_out is None else price_out
    return round(((tokens_in or 0) * price_in + (tokens_out or 0) * price_out) / 1_000_000, 6)


class AnthropicProvider:
    """Calls Claude through the official ``anthropic`` SDK (optional dependency)."""

    def __init__(self, client_factory: Callable[[], Any] | None = None) -> None:
        self._client_factory = client_factory
        self._client = None

    def availability(self, member: Mapping[str, Any]) -> Availability:
        if self._client_factory is None:
            try:
                import anthropic  # noqa: F401
            except ImportError:
                return Availability(False, "anthropic SDK not installed (pip install 'hermes-ultra[command-center]')")
        env = member.get("credential_env")
        if env and not os.environ.get(env) and not os.environ.get("ANTHROPIC_AUTH_TOKEN") and not os.environ.get("ANTHROPIC_PROFILE"):
            return Availability(True, f"{env} unset; relying on SDK credential resolution (ant auth profile)")
        return Availability(True, "ready")

    def _get_client(self) -> Any:
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                import anthropic

                self._client = anthropic.Anthropic()
        return self._client

    def complete(self, member: Mapping[str, Any], system: str, prompt: str) -> ProviderReply:
        model = str(member["model"])
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": 16000,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_config": {"effort": member.get("effort") or "medium"},
        }
        started = time.monotonic()
        client = self._get_client()
        try:
            if model in CLAUDE_FALLBACK_MODELS:
                response = client.beta.messages.create(betas=[CLAUDE_FALLBACK_BETA], fallbacks="default", **request)
            else:
                response = client.messages.create(**request)
        except Exception as exc:  # SDK raises typed errors; surface the class and message.
            return ProviderReply("error", f"{type(exc).__name__}: {exc}", model, latency_ms=_elapsed(started))
        usage = getattr(response, "usage", None)
        tokens_in = getattr(usage, "input_tokens", None)
        tokens_out = getattr(usage, "output_tokens", None)
        served_model = getattr(response, "model", None) or model
        if getattr(response, "stop_reason", None) == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            return ProviderReply(
                "refused", f"Declined by safety classifier (category: {category or 'unspecified'}).", served_model,
                tokens_in, tokens_out, _elapsed(started),
            )
        text = "\n".join(
            getattr(block, "text", "") for block in getattr(response, "content", []) if getattr(block, "type", "") == "text"
        ).strip()
        if not text:
            return ProviderReply("error", f"empty response (stop_reason={getattr(response, 'stop_reason', None)})",
                                 served_model, tokens_in, tokens_out, _elapsed(started))
        return ProviderReply("ok", text, served_model, tokens_in, tokens_out, _elapsed(started))


Transport = Callable[[str, Mapping[str, str], bytes, float], tuple[int, bytes]]


def urllib_transport(url: str, headers: Mapping[str, str], body: bytes, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class OpenAICompatibleProvider:
    """Chat Completions over HTTP: OpenAI, Llama API, Gemini's OpenAI endpoint, Ollama, OpenRouter."""

    def __init__(self, transport: Transport | None = None, timeout: float = 120.0) -> None:
        self._transport = transport or urllib_transport
        self._timeout = timeout

    def availability(self, member: Mapping[str, Any]) -> Availability:
        if not member.get("base_url"):
            return Availability(False, "no base_url configured")
        env = member.get("credential_env")
        if env and not os.environ.get(env):
            return Availability(False, f"credential env {env} is not set on the server")
        return Availability(True, "ready" if env else "ready (no credential; local endpoint)")

    def complete(self, member: Mapping[str, Any], system: str, prompt: str) -> ProviderReply:
        model = str(member["model"])
        url = str(member["base_url"]).rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        env = member.get("credential_env")
        if env:
            headers["Authorization"] = "Bearer " + os.environ.get(env, "")
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        started = time.monotonic()
        try:
            status, raw = self._transport(url, headers, json.dumps(payload).encode("utf-8"), self._timeout)
        except (OSError, urllib.error.URLError) as exc:
            return ProviderReply("error", f"{type(exc).__name__}: {exc}", model, latency_ms=_elapsed(started))
        latency = _elapsed(started)
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = {}
        if status >= 400:
            message = (data.get("error") or {}).get("message") if isinstance(data.get("error"), dict) else data.get("error")
            return ProviderReply("error", f"HTTP {status}: {message or raw[:300].decode('utf-8', 'replace')}", model,
                                 latency_ms=latency)
        try:
            choice = data["choices"][0]
            text = (choice.get("message") or {}).get("content") or ""
        except (KeyError, IndexError, TypeError):
            return ProviderReply("error", "malformed chat completion response", model, latency_ms=latency)
        usage = data.get("usage") or {}
        tokens_in, tokens_out = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if choice.get("finish_reason") == "content_filter":
            return ProviderReply("refused", "Declined by provider content filter.", data.get("model") or model,
                                 tokens_in, tokens_out, latency)
        if not str(text).strip():
            return ProviderReply("error", "empty response", data.get("model") or model, tokens_in, tokens_out, latency)
        return ProviderReply("ok", str(text).strip(), data.get("model") or model, tokens_in, tokens_out, latency)


class ManualProvider:
    """A seat held by a human or an external agent that posts through the API."""

    def availability(self, member: Mapping[str, Any]) -> Availability:
        return Availability(False, "manual seat; replies arrive through POST /api/council/messages")

    def complete(self, member: Mapping[str, Any], system: str, prompt: str) -> ProviderReply:
        raise RuntimeError("manual seats do not auto-reply")


def default_providers() -> dict[str, Any]:
    openai_compatible = OpenAICompatibleProvider()
    return {
        "anthropic": AnthropicProvider(),
        "openai": openai_compatible,
        "openai_compatible": openai_compatible,
        "manual": ManualProvider(),
    }


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
