#!/usr/bin/env python3
"""Privacy-preserving OpenTelemetry bridge for Hermes.

The bridge always writes a compact append-only local span record unless disabled.
OTLP/HTTP JSON export is optional and fail-open by default so observability cannot
become a new availability dependency. Prompt/completion/tool payload content is
omitted by default and sensitive Hermes classifications are metadata-only.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "hermes-otel-span-v1"
SENSITIVE_CLASSES = {"LEGAL_PRIVILEGED", "FINANCIAL", "SECURITY_SENSITIVE", "CREDENTIAL"}
SECRET_KEY_RE = re.compile(r"(api[_-]?key|authorization|bearer|cookie|credential|otp|pass(word)?|secret|session|token)", re.I)
CONTENT_KEY_RE = re.compile(r"(^|[._-])(prompt|completion|message|body|content|tool[_-]?(input|output)|input[_-]?text|output[_-]?text)($|[._-])", re.I)
SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
)
HEX_TRACE_RE = re.compile(r"^[0-9a-f]{32}$")
HEX_SPAN_RE = re.compile(r"^[0-9a-f]{16}$")


def normalize_classification(value: str | None) -> str:
    normalized = (value or "INTERNAL").strip().replace("-", "_").replace(" ", "_").upper()
    aliases = {
        "PUBLIC": "PUBLIC",
        "INTERNAL": "INTERNAL",
        "CONFIDENTIAL": "CONFIDENTIAL",
        "LEGAL": "LEGAL_PRIVILEGED",
        "LEGAL_PRIVILEGED": "LEGAL_PRIVILEGED",
        "FINANCIAL": "FINANCIAL",
        "CREDENTIAL": "CREDENTIAL",
        "CREDENTIALS": "CREDENTIAL",
        "SECURITY": "SECURITY_SENSITIVE",
        "SECURITY_SENSITIVE": "SECURITY_SENSITIVE",
        "RESTRICTED": "SECURITY_SENSITIVE",
    }
    if normalized not in aliases:
        raise ValueError(f"unsupported security classification: {value}")
    return aliases[normalized]


def new_trace_context(parent_trace_id: str | None = None) -> dict[str, str]:
    trace_id = (parent_trace_id or "").lower()
    if trace_id and not HEX_TRACE_RE.fullmatch(trace_id):
        raise ValueError("parent trace id must be 32 lowercase hex characters")
    if not trace_id:
        trace_id = secrets.token_hex(16)
        while trace_id == "0" * 32:
            trace_id = secrets.token_hex(16)
    span_id = secrets.token_hex(8)
    while span_id == "0" * 16:
        span_id = secrets.token_hex(8)
    return {"trace_id": trace_id, "span_id": span_id}


def _contains_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS)


def _sanitize_mapping(mapping: dict[Any, Any], *, omit_content: bool) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_key, value in list(mapping.items())[:64]:
        key = str(raw_key)[:160]
        if SECRET_KEY_RE.search(key):
            result[key] = "[REDACTED_SECRET]"
        elif CONTENT_KEY_RE.search(key) and omit_content:
            result[key] = "[CONTENT_OMITTED]"
        else:
            result[key] = _sanitize_value(value, omit_content=omit_content)
    return result


def _sanitize_value(value: Any, *, omit_content: bool) -> Any:
    if isinstance(value, str):
        if _contains_secret(value):
            return "[REDACTED_SECRET]"
        return value[:4096]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, list):
        return [_sanitize_value(item, omit_content=omit_content) for item in value[:64]]
    if isinstance(value, dict):
        return _sanitize_mapping(value, omit_content=omit_content)
    return str(value)[:4096]


def sanitize_attributes(
    attributes: dict[str, Any],
    *,
    classification: str = "INTERNAL",
    include_content: bool = False,
) -> dict[str, Any]:
    normalized = normalize_classification(classification)
    metadata_only = normalized in SENSITIVE_CLASSES
    return _sanitize_mapping(attributes, omit_content=metadata_only or not include_content)


def _validate_ids(trace_id: str, span_id: str, parent_span_id: str = "") -> None:
    if not HEX_TRACE_RE.fullmatch(trace_id):
        raise ValueError("trace_id must be 32 lowercase hex characters")
    if not HEX_SPAN_RE.fullmatch(span_id):
        raise ValueError("span_id must be 16 lowercase hex characters")
    if parent_span_id and not HEX_SPAN_RE.fullmatch(parent_span_id):
        raise ValueError("parent_span_id must be 16 lowercase hex characters")


def build_span(
    *,
    name: str,
    kind: str,
    trace_id: str,
    span_id: str,
    parent_span_id: str = "",
    start_ns: int,
    end_ns: int,
    status: str,
    classification: str,
    attributes: dict[str, Any],
    include_content: bool = False,
) -> dict[str, Any]:
    _validate_ids(trace_id, span_id, parent_span_id)
    if not name or len(name) > 200:
        raise ValueError("span name is required and must be <= 200 characters")
    if end_ns < start_ns:
        raise ValueError("end_ns must be >= start_ns")
    normalized = normalize_classification(classification)
    return {
        "schema_version": SCHEMA_VERSION,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "name": name,
        "kind": kind or "internal",
        "start_time_unix_nano": int(start_ns),
        "end_time_unix_nano": int(end_ns),
        "duration_ms": round((int(end_ns) - int(start_ns)) / 1_000_000, 3),
        "status": status.upper(),
        "security_classification": normalized,
        "attributes": sanitize_attributes(attributes, classification=normalized, include_content=include_content),
    }


def append_local_span(path: Path, span: dict[str, Any]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("telemetry output must not be a symlink")
    line = (json.dumps(span, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def _otel_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_otel_value(item) for item in value]}}
    if isinstance(value, dict):
        return {
            "kvlistValue": {
                "values": [{"key": str(k), "value": _otel_value(v)} for k, v in sorted(value.items())]
            }
        }
    return {"stringValue": "" if value is None else str(value)}


def build_otlp_json(span: dict[str, Any]) -> dict[str, Any]:
    status_code = 1 if span["status"] in {"OK", "SUCCESS", "COMPLETED"} else 2 if span["status"] in {"ERROR", "FAILED"} else 0
    otel_span: dict[str, Any] = {
        "traceId": base64.b64encode(bytes.fromhex(span["trace_id"])).decode("ascii"),
        "spanId": base64.b64encode(bytes.fromhex(span["span_id"])).decode("ascii"),
        "name": span["name"],
        "kind": 1,
        "startTimeUnixNano": str(span["start_time_unix_nano"]),
        "endTimeUnixNano": str(span["end_time_unix_nano"]),
        "attributes": [
            {"key": str(key), "value": _otel_value(value)}
            for key, value in sorted(span["attributes"].items())
        ] + [
            {"key": "hermes.security.classification", "value": {"stringValue": span["security_classification"]}},
            {"key": "hermes.span.kind", "value": {"stringValue": span["kind"]}},
        ],
        "status": {"code": status_code},
    }
    if span.get("parent_span_id"):
        otel_span["parentSpanId"] = base64.b64encode(bytes.fromhex(span["parent_span_id"])).decode("ascii")
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": os.environ.get("HERMES_OTEL_SERVICE_NAME", "hermes-max")}}
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "hermes.otel-bridge", "version": "1"},
                        "spans": [otel_span],
                    }
                ],
            }
        ]
    }


def export_otlp_json(endpoint: str, span: dict[str, Any], *, timeout: float = 2.0) -> None:
    body = json.dumps(build_otlp_json(span), separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if not 200 <= int(response.status) < 300:
            raise RuntimeError(f"OTLP exporter returned HTTP {response.status}")


def emit_span(
    *,
    output_path: Path,
    name: str,
    kind: str,
    trace_id: str,
    span_id: str,
    start_ns: int,
    end_ns: int,
    status: str,
    classification: str,
    attributes: dict[str, Any],
    parent_span_id: str = "",
    include_content: bool = False,
    endpoint: str = "",
    export_enabled: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    span = build_span(
        name=name,
        kind=kind,
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        start_ns=start_ns,
        end_ns=end_ns,
        status=status,
        classification=classification,
        attributes=attributes,
        include_content=include_content,
    )
    append_local_span(output_path, span)
    exported = False
    export_error = ""
    if export_enabled and endpoint:
        try:
            export_otlp_json(endpoint, span, timeout=float(os.environ.get("HERMES_OTEL_EXPORT_TIMEOUT_SECONDS", "2")))
            exported = True
        except Exception as exc:
            export_error = f"{type(exc).__name__}: {exc}"[:240]
            if strict:
                raise
    return {
        "schema_version": "hermes-otel-emit-result-v1",
        "trace_id": trace_id,
        "span_id": span_id,
        "local_written": True,
        "exported": exported,
        "export_error": export_error,
        "span_hash": "sha256:" + hashlib.sha256(json.dumps(span, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }


def _parse_attributes(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("attributes JSON must be an object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes privacy-preserving OTel bridge")
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new")
    new.add_argument("--parent-trace-id", default=os.environ.get("HERMES_TRACE_ID", ""))

    emit = sub.add_parser("emit")
    emit.add_argument("--name", required=True)
    emit.add_argument("--kind", default="internal")
    emit.add_argument("--trace-id", default=os.environ.get("HERMES_TRACE_ID", ""))
    emit.add_argument("--span-id", default=os.environ.get("HERMES_TRACE_SPAN_ID", ""))
    emit.add_argument("--parent-span-id", default=os.environ.get("HERMES_PARENT_SPAN_ID", ""))
    emit.add_argument("--start-ns", type=int, required=True)
    emit.add_argument("--end-ns", type=int, default=0)
    emit.add_argument("--status", default="OK")
    emit.add_argument("--classification", default=os.environ.get("HERMES_SECURITY_CLASSIFICATION", "INTERNAL"))
    emit.add_argument("--attributes-json", default="{}")
    emit.add_argument("--include-content", action="store_true")
    emit.add_argument("--output", default=os.environ.get("HERMES_OTEL_OUTPUT", ".hermes/telemetry/spans.jsonl"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "new":
        parent = args.parent_trace_id or None
        print(json.dumps(new_trace_context(parent), sort_keys=True))
        return 0

    trace_id = args.trace_id
    span_id = args.span_id
    if not trace_id or not span_id:
        ctx = new_trace_context(trace_id or None)
        trace_id = ctx["trace_id"]
        span_id = ctx["span_id"]
    end_ns = args.end_ns or time.time_ns()
    result = emit_span(
        output_path=Path(args.output),
        name=args.name,
        kind=args.kind,
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=args.parent_span_id,
        start_ns=args.start_ns,
        end_ns=end_ns,
        status=args.status,
        classification=args.classification,
        attributes=_parse_attributes(args.attributes_json),
        include_content=bool(args.include_content and os.environ.get("HERMES_OTEL_ALLOW_CONTENT", "0") == "1"),
        endpoint=os.environ.get("HERMES_OTEL_EXPORTER_OTLP_ENDPOINT", ""),
        export_enabled=os.environ.get("HERMES_OTEL_EXPORT_ENABLED", "0") == "1",
        strict=os.environ.get("HERMES_OTEL_EXPORT_STRICT", "0") == "1",
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"otel bridge error: {exc}", file=sys.stderr)
        raise SystemExit(2)
