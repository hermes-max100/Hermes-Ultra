#!/usr/bin/env python3
"""Hermes compatibility boundary for MCP protocol 2026-07-28 stateless core.

The adapter validates self-describing MCP requests and maps them into existing
Hermes approval/containment primitives. It does not retain protocol sessions.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

PROTOCOL_VERSION = "2026-07-28"
LEGACY_VERSIONS = {"2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"}
RETIRED_METHODS = {"initialize", "notifications/initialized"}
DATA_CLASSES = {"PUBLIC","INTERNAL","CONFIDENTIAL","LEGAL_PRIVILEGED","FINANCIAL","CREDENTIAL","SECURITY_SENSITIVE"}
CLIENT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
METHOD_RE = re.compile(r"^[a-z][a-z0-9._-]*(?:/[a-zA-Z0-9._-]+)*$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
CACHEABLE_FIELDS = {"tools/list":("tools","name"),"prompts/list":("prompts","name"),"resources/list":("resources","uri"),"resources/read":("contents","uri")}


def _headers(headers: dict[str, Any]) -> dict[str, str]:
    if not isinstance(headers, dict): raise ValueError("headers must be an object")
    result: dict[str,str] = {}
    for key,value in headers.items():
        if not isinstance(key,str) or not isinstance(value,str): raise ValueError("headers must be string pairs")
        low=key.lower()
        if low in result: raise ValueError(f"duplicate header ignoring case: {key}")
        result[low]=value.strip()
    return result


def _client_info(body: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    params=body.get("params")
    if not isinstance(params,dict): raise ValueError("MCP request params object is required")
    meta=params.get("_meta")
    if not isinstance(meta,dict): raise ValueError("MCP client _meta is required")
    info=meta.get("io.modelcontextprotocol/clientInfo")
    if not isinstance(info,dict): raise ValueError("MCP clientInfo metadata is required")
    name=info.get("name"); version=info.get("version")
    if not isinstance(name,str) or not CLIENT_NAME_RE.fullmatch(name): raise ValueError("invalid MCP client name")
    if not isinstance(version,str) or not version or len(version)>128: raise ValueError("invalid MCP client version")
    caps=meta.get("io.modelcontextprotocol/clientCapabilities",{})
    if not isinstance(caps,dict): raise ValueError("clientCapabilities metadata must be an object")
    return {"name":name,"version":version}, caps


def validate_request(headers: dict[str, Any], body: dict[str, Any], *, allow_legacy: bool=False) -> dict[str, Any]:
    normalized=_headers(headers)
    version=normalized.get("mcp-protocol-version","")
    if version != PROTOCOL_VERSION:
        if allow_legacy and version in LEGACY_VERSIONS:
            return {"valid":False,"stateless":False,"protocol_version":version,"migration_action":"legacy_adapter_required"}
        raise ValueError(f"unsupported MCP protocol version: {version or 'missing'}")
    if "mcp-session-id" in normalized: raise ValueError("Mcp-Session-Id is forbidden in MCP 2026-07-28 stateless mode")
    if not isinstance(body,dict) or body.get("jsonrpc")!="2.0": raise ValueError("JSON-RPC 2.0 object required")
    method=body.get("method")
    if not isinstance(method,str) or not METHOD_RE.fullmatch(method): raise ValueError("invalid MCP JSON-RPC method")
    if method in RETIRED_METHODS: raise ValueError(f"retired MCP method is forbidden in stateless mode: {method}")
    header_method=normalized.get("mcp-method","")
    header_name=normalized.get("mcp-name","")
    if not header_method or not header_name: raise ValueError("Mcp-Method and Mcp-Name headers are required")
    if header_method != method: raise ValueError("Mcp-Method header does not match JSON-RPC method")
    if not NAME_RE.fullmatch(header_name): raise ValueError("invalid Mcp-Name header")
    params=body.get("params")
    if not isinstance(params,dict): raise ValueError("MCP params object is required")
    body_name=params.get("name")
    if body_name is not None and body_name != header_name: raise ValueError("Mcp-Name header does not match params.name")
    client, capabilities=_client_info(body)
    route={"protocol_version":version,"method":method,"name":header_name,"client":client}
    route_hash="sha256:"+hashlib.sha256(json.dumps(route,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {"valid":True,"stateless":True,**route,"client_capabilities":capabilities,"route_hash":route_hash}


def build_containment_scope(validated: dict[str, Any], *, destination: str, data_class: str) -> dict[str, str]:
    if not validated.get("valid") or not validated.get("stateless"): raise ValueError("validated stateless MCP request required")
    dc=data_class.strip().replace("-","_").replace(" ","_").upper()
    if dc not in DATA_CLASSES: raise ValueError("invalid Hermes data class")
    client=validated.get("client",{}).get("name","")
    method=validated.get("method",""); name=validated.get("name","")
    if not CLIENT_NAME_RE.fullmatch(client) or not METHOD_RE.fullmatch(method) or not NAME_RE.fullmatch(name): raise ValueError("invalid routed MCP identity")
    return {"principal":f"mcp:{client}","tool":f"mcp:{name}","destination":destination,"resource":f"mcp:{method}:{name}","data_class":dc}


def _validated_issuer(value: str) -> str:
    if not isinstance(value,str) or not value or len(value)>2048: raise ValueError("issuer must be a bounded URL")
    parsed=urlsplit(value)
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("issuer must be an HTTPS URL without userinfo/query/fragment")
    return value


def validate_issuer(actual_issuer: str, expected_issuer: str) -> bool:
    actual=_validated_issuer(actual_issuer); expected=_validated_issuer(expected_issuer)
    if not hmac.compare_digest(actual,expected): raise ValueError("authorization issuer mismatch")
    return True


def normalize_cacheable_result(method: str, result: dict[str, Any], *, max_ttl_ms: int=300_000) -> dict[str, Any]:
    if method not in CACHEABLE_FIELDS: raise ValueError("method does not support Hermes MCP cache normalization")
    if not isinstance(result,dict): raise ValueError("MCP result must be an object")
    ttl=result.get("ttlMs",0)
    if type(ttl) is not int or ttl<0 or ttl>max_ttl_ms: raise ValueError("ttlMs exceeds Hermes cache policy")
    scope=result.get("cacheScope","private")
    if not isinstance(scope,str) or not scope or len(scope)>64 or not re.fullmatch(r"[A-Za-z0-9._-]+",scope): raise ValueError("invalid cacheScope")
    field,key=CACHEABLE_FIELDS[method]
    rows=result.get(field,[])
    if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows): raise ValueError(f"{field} must be an object list")
    normalized=dict(result)
    normalized[field]=sorted(rows,key=lambda row:(str(row.get(key,"")),json.dumps(row,sort_keys=True,separators=(",",":"))))
    normalized["ttlMs"]=ttl; normalized["cacheScope"]=scope
    return normalized


def map_input_required(value: dict[str, Any], *, request_id: str) -> dict[str, Any]:
    if not isinstance(value,dict) or value.get("resultType")!="input_required": raise ValueError("MRTR input_required result required")
    requests=value.get("requests")
    if not isinstance(requests,list) or not requests or any(not isinstance(item,dict) for item in requests): raise ValueError("input_required requests must be a non-empty object list")
    if not isinstance(request_id,str) or not request_id or len(request_id)>128: raise ValueError("invalid request_id")
    return {"schema_version":"hermes-mcp-input-required-v1","state":"input_required","request_id":request_id,"approval_boundary":"hermes-approvals","requests":requests}


def verify_containment_token(validated: dict[str, Any], *, token: dict[str, Any], destination: str, data_class: str, containment_path: Path, secret: str, state_dir: Path) -> dict[str, Any]:
    spec=importlib.util.spec_from_file_location("hermes_containment_gateway",containment_path)
    if spec is None or spec.loader is None: raise ValueError("containment gateway unavailable")
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    scope_data=build_containment_scope(validated,destination=destination,data_class=data_class)
    requested=module.RequestScope.make(scope_data["principal"],scope_data["tool"],scope_data["destination"],scope_data["resource"],scope_data["data_class"])
    return module.verify_capability(token=token,secret=secret,requested=requested,state_dir=state_dir,consume=True,max_ttl_seconds=module.trusted_max_ttl_seconds())


def load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink(): raise ValueError("JSON input symlink forbidden")
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise ValueError("JSON input must be an object")
    return value


def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest="command",required=True)
    val=sub.add_parser("validate"); val.add_argument("--headers",required=True); val.add_argument("--body",required=True); val.add_argument("--allow-legacy",action="store_true")
    auth=sub.add_parser("authorize"); auth.add_argument("--headers",required=True); auth.add_argument("--body",required=True); auth.add_argument("--token",required=True); auth.add_argument("--destination",required=True); auth.add_argument("--data-class",required=True); auth.add_argument("--containment",default="src/system/containment-gateway.py")
    return p


def main(argv: list[str] | None=None) -> int:
    args=parser().parse_args(argv)
    try:
        validated=validate_request(load_json(Path(args.headers)),load_json(Path(args.body)),allow_legacy=getattr(args,"allow_legacy",False))
        if args.command=="validate": result=validated
        else:
            secret=os.environ.get("HERMES_CONTAINMENT_SECRET","")
            if not secret: raise ValueError("HERMES_CONTAINMENT_SECRET is required")
            receipt=verify_containment_token(validated,token=load_json(Path(args.token)),destination=args.destination,data_class=args.data_class,containment_path=Path(args.containment),secret=secret,state_dir=Path(os.environ.get("HERMES_CONTAINMENT_STATE_DIR",".hermes/containment")))
            result={"validated":validated,"containment_receipt":receipt}
        print(json.dumps(result,indent=2,sort_keys=True)); return 0
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        print(json.dumps({"decision":"DENY","reason":str(exc)},sort_keys=True),file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
