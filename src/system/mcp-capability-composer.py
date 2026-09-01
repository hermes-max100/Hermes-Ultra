#!/usr/bin/env python3
"""Compose profile-scoped virtual MCP toolkits without becoming an authority.

The canonical MCP provider registry remains the source of provider lifecycle,
profile, capability, effect, runtime, and provenance truth. This module may
select and package those already-governed capabilities, but it cannot promote a
provider, enable a provider, authorize an effect, choose a runtime route, or
execute an external composition service.

MCP Market is supported as a provisioning-plan backend. The renderer emits a
credential-free plan that can be used to create/update a Toolkit through a
supported human/vendor workflow; it intentionally does not invent or call an
undocumented remote API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "hermes-mcp-toolkit-registry-v1"
MANIFEST_SCHEMA_VERSION = "hermes-mcp-composite-manifest-v1"
MCP_MARKET_PLAN_SCHEMA_VERSION = "hermes-mcpmarket-toolkit-plan-v1"

COMPOSABLE_STATES = {"TRUSTED", "INSTALLED_DISABLED", "CANARY", "ACTIVE"}
RUNTIME_STATES = {"CANARY", "ACTIVE"}
MCP_MARKET_MAX_SOURCES = 50
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ALIAS_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class ComposerError(ValueError):
    """Raised when a toolkit cannot be safely composed."""


def load_json(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ComposerError(f"{path}: expected a JSON object")
    return value


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_string_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(_nonempty_string(item) for item in value)


def _capability_matches(advertised: str, requested: str) -> bool:
    """Match using the same progressive semantics as mcp-provider-registry.py."""
    if advertised == requested:
        return True
    if advertised.endswith(".*"):
        return requested.startswith(advertised[:-1])
    return advertised.startswith(requested + ".")


def _provider_index(provider_registry: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    errors: list[str] = []
    providers = provider_registry.get("providers")
    if not isinstance(providers, list):
        return {}, ["provider registry providers must be a list"]
    indexed: dict[str, Mapping[str, Any]] = {}
    for index, provider in enumerate(providers):
        if not isinstance(provider, Mapping):
            errors.append(f"provider registry providers[{index}] must be an object")
            continue
        provider_id = provider.get("id")
        if not _nonempty_string(provider_id):
            errors.append(f"provider registry providers[{index}].id is required")
            continue
        if provider_id in indexed:
            errors.append(f"duplicate provider id: {provider_id}")
            continue
        indexed[str(provider_id)] = provider
    return indexed, errors


def _toolkit_index(toolkit_registry: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    errors: list[str] = []
    rows = toolkit_registry.get("toolkits")
    if not isinstance(rows, list):
        return {}, ["toolkits must be a list"]
    indexed: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            errors.append(f"toolkits[{index}] must be an object")
            continue
        toolkit_id = row.get("id")
        if not isinstance(toolkit_id, str) or ID_RE.fullmatch(toolkit_id) is None:
            errors.append(f"toolkits[{index}].id is invalid")
            continue
        if toolkit_id in indexed:
            errors.append(f"duplicate toolkit id: {toolkit_id}")
            continue
        indexed[toolkit_id] = row
    return indexed, errors


def _validate_authority(data: Mapping[str, Any]) -> list[str]:
    authority = data.get("authority")
    if not isinstance(authority, Mapping):
        return ["authority must be an object"]
    errors: list[str] = []
    if authority.get("provider_registry") != "config/mcp-provider-registry.json":
        errors.append("authority.provider_registry must reference the canonical MCP provider registry")
    if authority.get("composition_can_promote") is not False:
        errors.append("composition_can_promote must be false")
    if authority.get("composition_can_route") is not False:
        errors.append("composition_can_route must be false")
    return errors


def _validate_backends(data: Mapping[str, Any]) -> list[str]:
    backends = data.get("backends")
    if not isinstance(backends, Mapping) or not backends:
        return ["backends must be a non-empty object"]
    errors: list[str] = []
    for backend_id, backend in backends.items():
        if not isinstance(backend_id, str) or ID_RE.fullmatch(backend_id) is None:
            errors.append(f"invalid backend id: {backend_id!r}")
            continue
        if not isinstance(backend, Mapping):
            errors.append(f"backend {backend_id} must be an object")
            continue
        if backend_id == "mcp_market":
            if backend.get("kind") != "provisioning_plan":
                errors.append("mcp_market backend kind must be provisioning_plan")
            if backend.get("executes_remote_api") is not False:
                errors.append("mcp_market backend must not execute an undocumented remote API")
    return errors


def validate_toolkit_registry(
    toolkit_registry: Mapping[str, Any],
    provider_registry: Mapping[str, Any],
) -> list[str]:
    """Validate composition policy against the canonical provider inventory."""
    errors: list[str] = []
    if toolkit_registry.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    errors.extend(_validate_authority(toolkit_registry))
    errors.extend(_validate_backends(toolkit_registry))

    providers, provider_errors = _provider_index(provider_registry)
    errors.extend(provider_errors)
    toolkits, toolkit_errors = _toolkit_index(toolkit_registry)
    errors.extend(toolkit_errors)
    backends = toolkit_registry.get("backends") if isinstance(toolkit_registry.get("backends"), Mapping) else {}

    for toolkit_id, toolkit in toolkits.items():
        display_name = toolkit.get("display_name")
        if not _nonempty_string(display_name):
            errors.append(f"{toolkit_id}: display_name is required")
        profile = toolkit.get("profile")
        if not isinstance(profile, str) or ID_RE.fullmatch(profile) is None:
            errors.append(f"{toolkit_id}: profile is invalid")
            continue
        backend_id = toolkit.get("backend")
        if not isinstance(backend_id, str) or backend_id not in backends:
            errors.append(f"{toolkit_id}: unknown backend {backend_id!r}")
        if not isinstance(toolkit.get("runtime_enabled"), bool):
            errors.append(f"{toolkit_id}: runtime_enabled must be boolean")

        allowed_effects = toolkit.get("allowed_effects")
        if not _nonempty_string_list(allowed_effects):
            errors.append(f"{toolkit_id}: allowed_effects must be non-empty")
            allowed: set[str] = set()
        else:
            allowed = set(allowed_effects)
            if len(allowed) != len(allowed_effects):
                errors.append(f"{toolkit_id}: allowed_effects contains duplicates")

        selections = toolkit.get("selections")
        if not isinstance(selections, list) or not selections:
            errors.append(f"{toolkit_id}: selections must be non-empty")
            continue

        aliases: set[str] = set()
        source_keys: set[tuple[str, str, str]] = set()
        source_providers: set[str] = set()
        for index, selection in enumerate(selections):
            prefix = f"{toolkit_id}.selections[{index}]"
            if not isinstance(selection, Mapping):
                errors.append(f"{prefix} must be an object")
                continue
            provider_id = selection.get("provider_id")
            capability = selection.get("capability")
            effect = selection.get("effect")
            alias = selection.get("alias")
            if not _nonempty_string(provider_id):
                errors.append(f"{prefix}.provider_id is required")
                continue
            provider_id = str(provider_id)
            source_providers.add(provider_id)
            provider = providers.get(provider_id)
            if provider is None:
                errors.append(f"{prefix}: unknown provider {provider_id}")
                continue

            lifecycle_state = provider.get("lifecycle_state")
            if lifecycle_state not in COMPOSABLE_STATES:
                errors.append(f"{prefix}: provider {provider_id} lifecycle state {lifecycle_state} is not composable")
            profiles = provider.get("profiles")
            if not isinstance(profiles, list) or profile not in profiles:
                errors.append(f"{prefix}: provider {provider_id} is not available to profile {profile}")

            if not _nonempty_string(capability):
                errors.append(f"{prefix}.capability is required")
            else:
                advertised = provider.get("capabilities")
                if not isinstance(advertised, list) or not any(
                    isinstance(item, str) and _capability_matches(item, str(capability)) for item in advertised
                ):
                    errors.append(f"{prefix}: provider {provider_id} does not advertise capability {capability}")

            if not _nonempty_string(effect):
                errors.append(f"{prefix}.effect is required")
            else:
                provider_effects = provider.get("effects")
                if not isinstance(provider_effects, list) or effect not in provider_effects:
                    errors.append(f"{prefix}: provider {provider_id} does not advertise effect {effect}")
                if effect not in allowed:
                    errors.append(f"{prefix}: effect {effect} is not allowed by toolkit {toolkit_id}")

            if not isinstance(alias, str) or ALIAS_RE.fullmatch(alias) is None:
                errors.append(f"{prefix}.alias is invalid")
            elif alias in aliases:
                errors.append(f"{prefix}: duplicate alias {alias}")
            else:
                aliases.add(alias)

            if _nonempty_string(capability) and _nonempty_string(effect):
                source_key = (provider_id, str(capability), str(effect))
                if source_key in source_keys:
                    errors.append(
                        f"{prefix}: duplicate provider/capability/effect selection "
                        f"{provider_id}/{capability}/{effect}"
                    )
                source_keys.add(source_key)

        if backend_id == "mcp_market" and len(source_providers) > MCP_MARKET_MAX_SOURCES:
            errors.append(
                f"{toolkit_id}: MCP Market toolkit exceeds {MCP_MARKET_MAX_SOURCES} source providers"
            )

    return errors


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_valid(
    toolkit_registry: Mapping[str, Any],
    provider_registry: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    errors = validate_toolkit_registry(toolkit_registry, provider_registry)
    if errors:
        raise ComposerError("; ".join(errors))
    toolkits, _ = _toolkit_index(toolkit_registry)
    providers, _ = _provider_index(provider_registry)
    return toolkits, providers


def compose_toolkit(
    toolkit_registry: Mapping[str, Any],
    provider_registry: Mapping[str, Any],
    toolkit_id: str,
) -> dict[str, Any]:
    """Build a deterministic vendor-neutral composite manifest."""
    toolkits, providers = _require_valid(toolkit_registry, provider_registry)
    toolkit = toolkits.get(toolkit_id)
    if toolkit is None:
        raise ComposerError(f"unknown toolkit: {toolkit_id}")

    tools: list[dict[str, Any]] = []
    source_runtime_ready: list[bool] = []
    for selection in toolkit["selections"]:
        provider = providers[selection["provider_id"]]
        ready = bool(
            provider.get("runtime_enabled") is True
            and provider.get("lifecycle_state") in RUNTIME_STATES
        )
        source_runtime_ready.append(ready)
        provenance = provider.get("provenance")
        tools.append(
            {
                "alias": selection["alias"],
                "capability": selection["capability"],
                "effect": selection["effect"],
                "source": {
                    "provider_id": provider["id"],
                    "lifecycle_state": provider["lifecycle_state"],
                    "runtime_enabled": provider["runtime_enabled"],
                    "runtime_ready": ready,
                    "provenance": dict(provenance) if isinstance(provenance, Mapping) else {},
                },
            }
        )

    payload: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "toolkit_id": toolkit["id"],
        "display_name": toolkit["display_name"],
        "profile": toolkit["profile"],
        "backend": toolkit["backend"],
        "authority": "mcp-provider-registry",
        "composition_can_promote": False,
        "composition_can_route": False,
        "allowed_effects": list(toolkit["allowed_effects"]),
        "runtime_enabled": toolkit["runtime_enabled"],
        "runtime_ready": bool(toolkit["runtime_enabled"] and all(source_runtime_ready)),
        "tools": tools,
    }
    payload["manifest_digest"] = _canonical_digest(payload)
    return payload


def render_backend(
    toolkit_registry: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Render a backend-specific plan without executing or authorizing it."""
    backend_id = manifest.get("backend")
    backends = toolkit_registry.get("backends")
    if not isinstance(backends, Mapping) or backend_id not in backends:
        raise ComposerError(f"unknown backend: {backend_id}")
    backend = backends[backend_id]
    if backend_id != "mcp_market":
        raise ComposerError(f"backend renderer not implemented: {backend_id}")
    if not isinstance(backend, Mapping):
        raise ComposerError("mcp_market backend configuration is invalid")
    if backend.get("kind") != "provisioning_plan" or backend.get("executes_remote_api") is not False:
        raise ComposerError("mcp_market backend must remain a non-executing provisioning plan")

    tools = []
    for tool in manifest.get("tools", []):
        source = tool["source"]
        tools.append(
            {
                "alias": tool["alias"],
                "source_provider": source["provider_id"],
                "source_capability": tool["capability"],
                "effect": tool["effect"],
                "source_provenance": dict(source.get("provenance", {})),
                "source_runtime_ready": source["runtime_ready"],
            }
        )

    return {
        "schema_version": MCP_MARKET_PLAN_SCHEMA_VERSION,
        "backend": "mcp_market",
        "mode": "provisioning_plan",
        "executes_remote_api": False,
        "toolkit_id": manifest["toolkit_id"],
        "display_name": manifest["display_name"],
        "profile": manifest["profile"],
        "manifest_digest": manifest["manifest_digest"],
        "runtime_ready": manifest["runtime_ready"],
        "tools": tools,
        "operator_note": (
            "Create or update the MCP Market Toolkit from these governed selections using a "
            "documented vendor workflow. Hermes does not send credentials or call an undocumented API."
        ),
    }


def compose_all(
    toolkit_registry: Mapping[str, Any],
    provider_registry: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    toolkits, _ = _require_valid(toolkit_registry, provider_registry)
    return {
        toolkit_id: compose_toolkit(toolkit_registry, provider_registry, toolkit_id)
        for toolkit_id in sorted(toolkits)
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--toolkits", default="config/mcp-toolkit-registry.json")
    p.add_argument("--providers", default="config/mcp-provider-registry.json")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    compose = sub.add_parser("compose")
    compose.add_argument("toolkit_id")
    render = sub.add_parser("render")
    render.add_argument("toolkit_id")
    sub.add_parser("compose-all")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        toolkit_registry = load_json(args.toolkits)
        provider_registry = load_json(args.providers)
        errors = validate_toolkit_registry(toolkit_registry, provider_registry)
        if errors:
            print(json.dumps({"valid": False, "errors": errors}, indent=2, sort_keys=True))
            return 2
        if args.command == "validate":
            result: Any = {
                "valid": True,
                "toolkits": len(toolkit_registry["toolkits"]),
                "authority": "mcp-provider-registry",
            }
        elif args.command == "compose":
            result = compose_toolkit(toolkit_registry, provider_registry, args.toolkit_id)
        elif args.command == "render":
            manifest = compose_toolkit(toolkit_registry, provider_registry, args.toolkit_id)
            result = render_backend(toolkit_registry, manifest)
        else:
            result = compose_all(toolkit_registry, provider_registry)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, ComposerError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
