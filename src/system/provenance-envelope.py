#!/usr/bin/env python3
"""Deterministic trust boundary for external tool/web/MCP data.

External observations are data only. They cannot self-promote into runtime
configuration, authority, policy, or execution semantics.
"""
from __future__ import annotations
import argparse, hashlib, json, time
from typing import Any

SCHEMA = "hermes-external-provenance-v1"
TRUST_CLASSES = {"external_untrusted", "external_verified", "internal_trusted"}
FORBIDDEN_AUTHORITY_KEYS = {
    "authority", "permissions", "runtime_config", "tool_config", "policy",
    "system_prompt", "execution_semantics", "trusted", "trust_class",
}

def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()

def envelope(content: Any, *, source: str, origin: str, trust_class: str="external_untrusted", timestamp: int|None=None) -> dict[str, Any]:
    if not source or not origin: raise ValueError("source and origin are required")
    if trust_class not in TRUST_CLASSES: raise ValueError("invalid trust class")
    # Only Hermes-internal callers may create trusted envelopes.
    if trust_class == "internal_trusted" and origin != "hermes-runtime":
        raise ValueError("external origin cannot assert internal trust")
    return {
        "schema_version": SCHEMA,
        "source": source,
        "origin": origin,
        "timestamp": int(time.time() if timestamp is None else timestamp),
        "content_hash": digest(content),
        "trust_class": trust_class,
        "authority": "data_only" if trust_class.startswith("external_") else "runtime_asserted",
        "content": content,
    }

def authority_claims(content: Any, path: str="$" ) -> list[str]:
    out=[]
    if isinstance(content, dict):
        for k,v in content.items():
            p=f"{path}.{k}"
            if str(k).lower() in FORBIDDEN_AUTHORITY_KEYS: out.append(p)
            out.extend(authority_claims(v,p))
    elif isinstance(content,list):
        for i,v in enumerate(content): out.extend(authority_claims(v,f"{path}[{i}]"))
    return out

def validate(value: dict[str,Any]) -> list[str]:
    errors=[]
    if value.get("schema_version") != SCHEMA: errors.append("schema mismatch")
    tc=value.get("trust_class")
    if tc not in TRUST_CLASSES: errors.append("invalid trust class")
    if tc and tc.startswith("external_") and value.get("authority") != "data_only": errors.append("external content must be data_only")
    if tc=="internal_trusted" and value.get("origin") != "hermes-runtime": errors.append("external origin cannot assert internal trust")
    if "content" not in value or value.get("content_hash") != digest(value.get("content")): errors.append("content hash mismatch")
    return errors

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--source',required=True); ap.add_argument('--origin',required=True); ap.add_argument('--trust-class',default='external_untrusted'); ap.add_argument('--reject-authority-claims',action='store_true'); a=ap.parse_args()
    content=json.load(__import__('sys').stdin)
    claims=authority_claims(content)
    if a.reject_authority_claims and claims:
        print(json.dumps({"error":"external authority claims rejected","paths":claims},sort_keys=True)); return 2
    print(json.dumps(envelope(content,source=a.source,origin=a.origin,trust_class=a.trust_class),sort_keys=True)); return 0
if __name__=='__main__': raise SystemExit(main())
