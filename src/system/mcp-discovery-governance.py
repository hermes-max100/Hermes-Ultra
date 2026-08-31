#!/usr/bin/env python3
"""Govern MCP discovery sources before candidates enter Hermes trust promotion.

This module is deliberately read/collect only. Discovery evidence can create a
DISCOVERED candidate, but it cannot promote lifecycle state, install a server,
or activate runtime execution. Provider activation remains owned by the
existing Hermes Trust Gate and canonical MCP provider registry.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

SCHEMA_VERSION = "hermes-mcp-discovery-sources-v1"
AUTHORITIES = {
    "canonical",
    "provenance_verification",
    "supplemental_discovery",
    "long_tail_discovery",
    "weak_discovery",
}
TRUST_LEVELS = {
    "CANONICAL_DISCOVERY",
    "VERIFICATION_SOURCE",
    "UNTRUSTED_DISCOVERY",
    "UNTRUSTED_DISCOVERY_ONLY",
}
INTERFACE_TYPES = {
    "native",
    "cli_skill",
    "official_api",
    "official_mcp",
    "verified_community_mcp",
    "browser_automation",
}
EXPECTED_INTERFACE_PREFERENCE = (
    "native",
    "cli_skill",
    "official_api",
    "official_mcp",
    "verified_community_mcp",
    "browser_automation",
)
CONTROL_FIELDS = ("can_promote", "can_install", "can_activate")
REQUIRED_SOURCE_CONSTRAINTS: dict[str, dict[str, Any]] = {
    "official_mcp_registry": {
        "url": "https://registry.modelcontextprotocol.io/",
        "authority": "canonical",
        "trust": "CANONICAL_DISCOVERY",
        "priority": 1000,
        "can_verify": False,
    },
    "vendor_repositories": {
        "url": "https://github.com/",
        "authority": "provenance_verification",
        "trust": "VERIFICATION_SOURCE",
        "priority": 900,
        "can_verify": True,
    },
    "allmcpservers": {
        "url": "https://www.allmcpservers.com/",
        "authority": "supplemental_discovery",
        "trust": "UNTRUSTED_DISCOVERY_ONLY",
        "priority": 500,
        "can_verify": False,
    },
}


class DiscoveryGovernanceError(ValueError):
    pass


def load_source_registry(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DiscoveryGovernanceError("MCP discovery source registry must be a JSON object")
    return value


def _https_url(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
    )


def validate_source_registry(data: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    preference = data.get("interface_preference")
    if not isinstance(preference, list) or not preference:
        errors.append("interface_preference must be a non-empty list")
    elif (
        any(not isinstance(item, str) or item not in INTERFACE_TYPES for item in preference)
        or len(set(preference)) != len(preference)
    ):
        errors.append("interface_preference contains invalid or duplicate interface IDs")
    elif preference != list(EXPECTED_INTERFACE_PREFERENCE):
        errors.append(
            "interface_preference must remain native, cli_skill, official_api, "
            "official_mcp, verified_community_mcp, browser_automation"
        )

    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        return errors + ["sources must be a non-empty list"]

    seen: set[str] = set()
    canonical_ids: list[str] = []
    source_by_id: dict[str, Mapping[str, Any]] = {}
    for index, source in enumerate(sources):
        prefix = f"sources[{index}]"
        if not isinstance(source, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id:
            errors.append(f"{prefix}.id must be a non-empty string")
            continue
        if source_id in seen:
            errors.append(f"duplicate source id: {source_id}")
        seen.add(source_id)
        source_by_id[source_id] = source

        if not _https_url(source.get("url")):
            errors.append(f"{source_id}: url must be credential-free HTTPS without fragment")
        if source.get("authority") not in AUTHORITIES:
            errors.append(f"{source_id}: invalid authority")
        if source.get("trust") not in TRUST_LEVELS:
            errors.append(f"{source_id}: invalid trust level")
        priority = source.get("priority")
        if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 1000:
            errors.append(f"{source_id}: priority must be an integer from 0 to 1000")
        if source.get("can_discover") is not True:
            errors.append(f"{source_id}: can_discover must be true")
        if not isinstance(source.get("can_verify"), bool):
            errors.append(f"{source_id}: can_verify must be boolean")
        for field in CONTROL_FIELDS:
            if source.get(field) is not False:
                errors.append(f"{source_id}: {field} must remain false")
        if source.get("can_verify") is True and source.get("authority") != "provenance_verification":
            errors.append(f"{source_id}: only provenance_verification sources may set can_verify=true")
        if source.get("authority") == "canonical":
            canonical_ids.append(source_id)

    for source_id, constraints in REQUIRED_SOURCE_CONSTRAINTS.items():
        source = source_by_id.get(source_id)
        if source is None:
            errors.append(f"required source missing: {source_id}")
            continue
        for field, expected in constraints.items():
            if source.get(field) != expected:
                if field == "url":
                    errors.append(f"{source_id}: url must remain {expected}")
                else:
                    rendered = str(expected).lower() if isinstance(expected, bool) else str(expected)
                    errors.append(f"{source_id}: {field} must remain {rendered}")

    canonical_source = data.get("canonical_source")
    if not isinstance(canonical_source, str) or canonical_source not in source_by_id:
        errors.append("canonical_source must reference a configured source")
    else:
        canonical = source_by_id[canonical_source]
        if canonical_source != "official_mcp_registry":
            errors.append("canonical_source must remain official_mcp_registry")
        if canonical.get("authority") != "canonical":
            errors.append("canonical_source must have authority=canonical")
        if canonical.get("trust") != "CANONICAL_DISCOVERY":
            errors.append("canonical_source must have trust=CANONICAL_DISCOVERY")
        priorities = [source.get("priority") for source in sources if isinstance(source, Mapping)]
        numeric_priorities = [value for value in priorities if isinstance(value, int) and not isinstance(value, bool)]
        if numeric_priorities and canonical.get("priority") != max(numeric_priorities):
            errors.append("canonical_source must have highest priority")
    if len(canonical_ids) != 1:
        errors.append("exactly one source must have authority=canonical")

    return errors


def ordered_sources(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    errors = validate_source_registry(data)
    if errors:
        raise DiscoveryGovernanceError("; ".join(errors))
    return sorted(
        (dict(source) for source in data["sources"]),
        key=lambda source: (-source["priority"], source["id"]),
    )


def _candidate_url(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    if not _https_url(value):
        raise DiscoveryGovernanceError(f"candidate {field} must be credential-free HTTPS without fragment")
    return value


def normalize_candidate(
    data: Mapping[str, Any],
    *,
    source_id: str,
    name: str,
    homepage: str | None = None,
    repository: str | None = None,
) -> dict[str, Any]:
    errors = validate_source_registry(data)
    if errors:
        raise DiscoveryGovernanceError("; ".join(errors))
    if not isinstance(name, str) or not name.strip():
        raise DiscoveryGovernanceError("candidate name must be a non-empty string")
    sources = {source["id"]: source for source in data["sources"]}
    source = sources.get(source_id)
    if source is None:
        raise DiscoveryGovernanceError(f"unknown discovery source: {source_id}")

    candidate: dict[str, Any] = {
        "schema_version": "hermes-mcp-discovery-candidate-v1",
        "name": name.strip(),
        "lifecycle_state": "DISCOVERED",
        "runtime_enabled": False,
        "verification_required": True,
        "can_promote": False,
        "can_install": False,
        "can_activate": False,
        "source": {
            "id": source["id"],
            "authority": source["authority"],
            "trust": source["trust"],
            "priority": source["priority"],
        },
    }
    normalized_homepage = _candidate_url(homepage, field="homepage")
    normalized_repository = _candidate_url(repository, field="repository")
    if normalized_homepage is not None:
        candidate["homepage"] = normalized_homepage
    if normalized_repository is not None:
        candidate["repository"] = normalized_repository
    return candidate


def choose_interface(data: Mapping[str, Any], available: Sequence[str]) -> str | None:
    errors = validate_source_registry(data)
    if errors:
        raise DiscoveryGovernanceError("; ".join(errors))
    if isinstance(available, (str, bytes)):
        raise DiscoveryGovernanceError("available interfaces must be a sequence of interface IDs")
    offered = set(available)
    unknown = offered - INTERFACE_TYPES
    if unknown:
        raise DiscoveryGovernanceError(f"unknown interface IDs: {', '.join(sorted(unknown))}")
    for interface_id in data["interface_preference"]:
        if interface_id in offered:
            return interface_id
    return None


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--registry", default="config/mcp-discovery-sources.json")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("sources")
    candidate = sub.add_parser("candidate")
    candidate.add_argument("--source", required=True)
    candidate.add_argument("--name", required=True)
    candidate.add_argument("--homepage")
    candidate.add_argument("--repository")
    interface = sub.add_parser("choose-interface")
    interface.add_argument("interfaces", nargs="*")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        data = load_source_registry(args.registry)
        errors = validate_source_registry(data)
        if errors:
            print(json.dumps({"valid": False, "errors": errors}, indent=2, sort_keys=True))
            return 2
        if args.command == "validate":
            result: Any = {
                "valid": True,
                "sources": len(data["sources"]),
                "canonical_source": data["canonical_source"],
            }
        elif args.command == "sources":
            result = ordered_sources(data)
        elif args.command == "candidate":
            result = normalize_candidate(
                data,
                source_id=args.source,
                name=args.name,
                homepage=args.homepage,
                repository=args.repository,
            )
        else:
            result = {"interface": choose_interface(data, args.interfaces)}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, DiscoveryGovernanceError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
