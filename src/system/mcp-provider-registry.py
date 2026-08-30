#!/usr/bin/env python3
"""Canonical Hermes MCP provider catalog and native-runtime renderer.

The registry contains provider metadata and secret references only. This module
never promotes lifecycle state, acquires credentials, or executes a provider.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

SCHEMA_VERSION = "hermes-mcp-provider-registry-v1"
LIFECYCLE_STATES = {
    "DISCOVERED",
    "CANDIDATE",
    "TRUSTED",
    "INSTALLED_DISABLED",
    "CANARY",
    "ACTIVE",
}
RUNTIME_STATES = {"CANARY", "ACTIVE"}
PROFILE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
SECRET_VALUE_RE = re.compile(
    r"(?i)(?:sk[_-](?:live|test)[_-]|gh[pousr]_|bearer\s+ey|password\s*=|api[_-]?key\s*=)"
)


class RegistryError(ValueError):
    pass


def load_registry(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RegistryError("MCP provider registry must be a JSON object")
    return value


def _https_url(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password and not parsed.fragment


def _nonempty_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value)


def _validate_env_names(values: Any, *, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(values, list):
        return [f"{label} must be a list"]
    for item in values:
        if not isinstance(item, str) or ENV_RE.fullmatch(item) is None:
            errors.append(f"{label} contains invalid env name: {item!r}")
    return errors


def validate_registry(data: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    scout = data.get("scout")
    if not isinstance(scout, Mapping) or scout.get("role") != "discovery_proposal_only" or scout.get("can_promote") is not False:
        errors.append("Scout must remain discovery_proposal_only with can_promote=false")

    providers = data.get("providers")
    if not isinstance(providers, list):
        return errors + ["providers must be a list"]
    seen: set[str] = set()
    for index, provider in enumerate(providers):
        prefix = f"providers[{index}]"
        if not isinstance(provider, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        provider_id = provider.get("id")
        if not isinstance(provider_id, str) or ID_RE.fullmatch(provider_id) is None:
            errors.append(f"{prefix}.id is invalid")
            continue
        if provider_id in seen:
            errors.append(f"duplicate provider id: {provider_id}")
        seen.add(provider_id)
        if provider.get("lifecycle_state") not in LIFECYCLE_STATES:
            errors.append(f"{provider_id}: invalid lifecycle_state")
        if not isinstance(provider.get("runtime_enabled"), bool):
            errors.append(f"{provider_id}: runtime_enabled must be boolean")
        profiles = provider.get("profiles")
        if not _nonempty_strings(profiles) or any(PROFILE_RE.fullmatch(item) is None for item in profiles or []):
            errors.append(f"{provider_id}: profiles must be non-empty profile IDs")
        if not _nonempty_strings(provider.get("capabilities")):
            errors.append(f"{provider_id}: capabilities must be non-empty")
        if not _nonempty_strings(provider.get("effects")):
            errors.append(f"{provider_id}: effects must be non-empty")

        transport = provider.get("transport")
        if not isinstance(transport, Mapping):
            errors.append(f"{provider_id}: transport must be an object")
        else:
            transport_type = transport.get("type")
            if transport_type == "streamable-http":
                url = transport.get("url")
                url_env = transport.get("url_env")
                if url is None and url_env is None:
                    errors.append(f"{provider_id}: remote transport requires url or url_env")
                if url is not None and not _https_url(url):
                    errors.append(f"{provider_id}: remote URL must be HTTPS")
                if url_env is not None and (not isinstance(url_env, str) or ENV_RE.fullmatch(url_env) is None):
                    errors.append(f"{provider_id}: invalid url_env")
            elif transport_type == "stdio":
                if not isinstance(transport.get("command"), str) or not transport.get("command"):
                    errors.append(f"{provider_id}: stdio command is required")
                args = transport.get("args", [])
                if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
                    errors.append(f"{provider_id}: stdio args must be strings")
                env = transport.get("env", {})
                if not isinstance(env, Mapping) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
                    errors.append(f"{provider_id}: stdio env must be string pairs")
            else:
                errors.append(f"{provider_id}: unsupported transport type")

        auth = provider.get("auth")
        if not isinstance(auth, Mapping):
            errors.append(f"{provider_id}: auth must be an object")
        else:
            errors.extend(_validate_env_names(auth.get("required_env", []), label=f"{provider_id}.auth.required_env"))
            headers = auth.get("headers", {})
            if not isinstance(headers, Mapping) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()):
                errors.append(f"{provider_id}: auth.headers must be string pairs")

        provenance = provider.get("provenance")
        if not isinstance(provenance, Mapping) or not _https_url(provenance.get("url")):
            errors.append(f"{provider_id}: provenance URL must be HTTPS")

        serialized = json.dumps(provider, sort_keys=True)
        if SECRET_VALUE_RE.search(serialized):
            errors.append(f"{provider_id}: secret-like literal is forbidden")

    platform_tools = data.get("platform_tools")
    if not isinstance(platform_tools, list):
        errors.append("platform_tools must be a list")
    return errors


def _copy_templates(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _copy_templates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy_templates(item) for item in value]
    return value


def render_hermes_servers(data: Mapping[str, Any], *, environ: Mapping[str, str] | None = None) -> dict[str, dict[str, Any]]:
    errors = validate_registry(data)
    if errors:
        raise RegistryError("; ".join(errors))
    env = os.environ if environ is None else environ
    rendered: dict[str, dict[str, Any]] = {}
    for provider in data["providers"]:
        transport = provider["transport"]
        config: dict[str, Any] = {}
        if transport["type"] == "streamable-http":
            url = transport.get("url")
            if url is None:
                url_env = transport.get("url_env")
                url = env.get(url_env, "") if isinstance(url_env, str) else ""
                if not url:
                    continue
                if not _https_url(url):
                    raise RegistryError(f"{provider['id']}: resolved dynamic URL must be HTTPS")
            config["url"] = url
        else:
            config["command"] = transport["command"]
            if transport.get("args"):
                config["args"] = list(transport["args"])
            if transport.get("env"):
                config["env"] = _copy_templates(transport["env"])

        auth = provider["auth"]
        if auth.get("type") == "oauth":
            config["auth"] = "oauth"
        if auth.get("headers"):
            config["headers"] = _copy_templates(auth["headers"])

        required = auth.get("required_env", [])
        env_ready = all(bool(env.get(name)) for name in required)
        state_ready = provider["lifecycle_state"] in RUNTIME_STATES
        config["enabled"] = bool(provider["runtime_enabled"] and state_ready and env_ready)
        config["hermes_managed"] = True
        config["hermes_provider_id"] = provider["id"]
        rendered[provider["id"]] = config
    return rendered


def _capability_matches(advertised: str, requested: str) -> bool:
    if advertised == requested:
        return True
    if advertised.endswith(".*"):
        return requested.startswith(advertised[:-1])
    return advertised.startswith(requested + ".")


def select_candidates(
    data: Mapping[str, Any],
    *,
    profile: str,
    capability: str,
    effect: str,
    include_inactive: bool = False,
) -> list[dict[str, Any]]:
    errors = validate_registry(data)
    if errors:
        raise RegistryError("; ".join(errors))
    rows: list[dict[str, Any]] = []
    for provider in data["providers"]:
        if profile not in provider["profiles"]:
            continue
        if effect not in provider["effects"]:
            continue
        if not any(_capability_matches(item, capability) for item in provider["capabilities"]):
            continue
        if not include_inactive and not (
            provider["runtime_enabled"] and provider["lifecycle_state"] in RUNTIME_STATES
        ):
            continue
        rows.append(dict(provider))
    rows.sort(key=lambda row: (0 if row["lifecycle_state"] == "ACTIVE" else 1, row["id"]))
    return rows


def _status(data: Mapping[str, Any], environ: Mapping[str, str]) -> dict[str, Any]:
    rendered = render_hermes_servers(data, environ=environ)
    active = sorted(name for name, cfg in rendered.items() if cfg.get("enabled") is True)
    disabled = sorted(name for name, cfg in rendered.items() if cfg.get("enabled") is not True)
    unresolved = sorted(
        row["id"] for row in data["providers"]
        if row["transport"].get("url_env") and row["id"] not in rendered
    )
    return {"schema_version": data["schema_version"], "active": active, "disabled": disabled, "unresolved": unresolved}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--registry", default="config/mcp-provider-registry.json")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("render")
    sub.add_parser("status")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        data = load_registry(Path(args.registry))
        errors = validate_registry(data)
        if errors:
            print(json.dumps({"valid": False, "errors": errors}, indent=2, sort_keys=True))
            return 2
        if args.command == "validate":
            result: Any = {"valid": True, "providers": len(data["providers"]), "platform_tools": len(data.get("platform_tools", []))}
        elif args.command == "render":
            result = render_hermes_servers(data)
        else:
            result = _status(data, os.environ)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, RegistryError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
