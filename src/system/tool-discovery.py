#!/usr/bin/env python3
"""Hermes progressive tool discovery.

Eligibility is evaluated before scoring or schema exposure. This module discovers
candidate tool schemas only; it never grants execution authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "hermes-tool-registry-v1"
DATA_CLASSES = {"PUBLIC", "INTERNAL", "CONFIDENTIAL", "LEGAL_PRIVILEGED", "FINANCIAL", "CREDENTIAL", "SECURITY_SENSITIVE"}
TOOL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,127}$")
TOKEN_RE = re.compile(r"[a-z0-9]+")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def registry_hash(registry: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(registry)).hexdigest()


def schema_hash(schema: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(schema)).hexdigest()


def normalize_data_class(value: str) -> str:
    normalized = value.strip().replace("-", "_").replace(" ", "_").upper()
    if normalized not in DATA_CLASSES:
        raise ValueError(f"unsupported data class: {value}")
    return normalized


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return list(value)


def validate_registry(registry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(registry, dict) or registry.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported tool registry schema")
    tools = registry.get("tools")
    if not isinstance(tools, list):
        raise ValueError("tools must be a list")
    seen: set[str] = set()
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            raise ValueError(f"tool {index} must be an object")
        name = tool.get("name")
        if not isinstance(name, str) or not TOOL_NAME_RE.fullmatch(name) or "." not in name:
            raise ValueError(f"invalid tool name at index {index}")
        if name in seen:
            raise ValueError(f"duplicate tool name: {name}")
        seen.add(name)
        namespace = tool.get("namespace")
        if not isinstance(namespace, str) or not namespace or name.split(".", 1)[0] != namespace:
            raise ValueError(f"invalid namespace for {name}")
        if not isinstance(tool.get("description"), str) or not tool["description"].strip():
            raise ValueError(f"missing description for {name}")
        _string_list(tool.get("keywords", []), f"{name}.keywords")
        if type(tool.get("mutating")) is not bool:
            raise ValueError(f"{name}.mutating must be boolean")
        data_classes = _string_list(tool.get("data_classes"), f"{name}.data_classes")
        for data_class in data_classes:
            normalize_data_class(data_class)
        _string_list(tool.get("required_capabilities", []), f"{name}.required_capabilities")
        schema = tool.get("input_schema")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ValueError(f"{name}.input_schema must be an object schema")
        if not isinstance(tool.get("source"), str) or not tool["source"].strip():
            raise ValueError(f"missing source for {name}")
        if "enabled" in tool and type(tool["enabled"]) is not bool:
            raise ValueError(f"{name}.enabled must be boolean")
    return registry


def load_registry(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("tool registry symlink is forbidden")
    data = json.loads(path.read_text(encoding="utf-8"))
    return validate_registry(data)


def _tokens(value: str) -> list[str]:
    return TOKEN_RE.findall(value.lower())


def _score(tool: dict[str, Any], query: str) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    token_set = set(query_tokens)
    name_tokens = set(_tokens(tool["name"].replace(".", " ")))
    namespace_tokens = set(_tokens(tool["namespace"]))
    keyword_tokens = set()
    for item in tool.get("keywords", []):
        keyword_tokens.update(_tokens(item))
    desc_tokens = set(_tokens(tool["description"]))
    score = 0.0
    score += 8.0 * len(token_set & name_tokens)
    score += 5.0 * len(token_set & namespace_tokens)
    score += 4.0 * len(token_set & keyword_tokens)
    score += 2.0 * len(token_set & desc_tokens)
    q = " ".join(query_tokens)
    if tool["name"] in query.lower():
        score += 12.0
    for keyword in tool.get("keywords", []):
        if keyword.lower() in q:
            score += 2.0
    return score


def _eligible(tool: dict[str, Any], *, data_class: str, allow_mutating: bool, available_capabilities: set[str]) -> bool:
    if tool.get("enabled", True) is False:
        return False
    if data_class not in {normalize_data_class(item) for item in tool["data_classes"]}:
        return False
    if tool["mutating"] and not allow_mutating:
        return False
    return set(tool.get("required_capabilities", [])).issubset(available_capabilities)


def search_tools(registry: dict[str, Any], query: str, *, limit: int = 5, data_class: str = "INTERNAL", allow_mutating: bool = False, available_capabilities: set[str] | None = None) -> list[dict[str, Any]]:
    validate_registry(registry)
    if limit < 1 or limit > 50:
        raise ValueError("limit must be between 1 and 50")
    normalized_class = normalize_data_class(data_class)
    capabilities = set(available_capabilities or set())
    rows: list[dict[str, Any]] = []
    for tool in registry["tools"]:
        if not _eligible(tool, data_class=normalized_class, allow_mutating=allow_mutating, available_capabilities=capabilities):
            continue
        score = round(_score(tool, query), 6)
        if score <= 0:
            continue
        rows.append({
            "name": tool["name"], "namespace": tool["namespace"], "description": tool["description"],
            "score": score, "mutating": tool["mutating"],
            "required_capabilities": list(tool["required_capabilities"]),
            "schema_hash": schema_hash(tool["input_schema"]),
        })
    rows.sort(key=lambda row: (-float(row["score"]), row["name"]))
    return rows[:limit]


def compact_context(registry: dict[str, Any], rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    validate_registry(registry)
    by_name = {tool["name"]: tool for tool in registry["tools"]}
    selected: list[dict[str, Any]] = []
    for row in rows:
        name = row.get("name")
        if name not in by_name:
            raise ValueError(f"selected tool not present in registry: {name}")
        tool = by_name[name]
        selected.append({
            "name": tool["name"], "description": tool["description"], "input_schema": tool["input_schema"],
            "mutating": tool["mutating"], "required_capabilities": list(tool["required_capabilities"]),
            "schema_hash": schema_hash(tool["input_schema"]),
        })
    return {"schema_version": "hermes-tool-context-v1", "registry_hash": registry_hash(registry), "tool_count": len(selected), "tools": selected}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    search = sub.add_parser("search")
    search.add_argument("--registry", required=True); search.add_argument("--query", required=True); search.add_argument("--limit", type=int, default=5)
    search.add_argument("--data-class", default="INTERNAL"); search.add_argument("--allow-mutating", action="store_true"); search.add_argument("--capability", action="append", default=[]); search.add_argument("--context", action="store_true")
    describe = sub.add_parser("describe"); describe.add_argument("--registry", required=True); describe.add_argument("--name", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        registry = load_registry(Path(args.registry))
        if args.command == "search":
            rows = search_tools(registry, args.query, limit=args.limit, data_class=args.data_class, allow_mutating=args.allow_mutating, available_capabilities=set(args.capability))
            result: Any = compact_context(registry, rows) if args.context else rows
        else:
            matches = [row for row in registry["tools"] if row["name"] == args.name]
            if not matches:
                raise ValueError(f"tool not found: {args.name}")
            tool = matches[0]
            result = {"name": tool["name"], "description": tool["description"], "input_schema": tool["input_schema"], "mutating": tool["mutating"], "required_capabilities": tool["required_capabilities"], "schema_hash": schema_hash(tool["input_schema"])}
        print(json.dumps(result, indent=2, sort_keys=True)); return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True), file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
