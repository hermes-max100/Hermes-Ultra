#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/system/otel-bridge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_otel_bridge", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load otel bridge")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OTelBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_module()

    def test_trace_context_has_w3c_sized_hex_ids(self) -> None:
        ctx = self.mod.new_trace_context()
        self.assertRegex(ctx["trace_id"], re.compile(r"^[0-9a-f]{32}$"))
        self.assertRegex(ctx["span_id"], re.compile(r"^[0-9a-f]{16}$"))
        self.assertNotEqual(ctx["trace_id"], "0" * 32)
        self.assertNotEqual(ctx["span_id"], "0" * 16)

    def test_content_and_secret_values_are_not_exported_by_default(self) -> None:
        attrs = self.mod.sanitize_attributes(
            {
                "gen_ai.agent.name": "hermes",
                "prompt": "private customer prompt",
                "tool_output": "private result",
                "api_key": "sk-super-secret-value-123456",
                "authorization": "Bearer abcdefghijklmnopqrstuvwxyz",
            },
            classification="INTERNAL",
            include_content=False,
        )
        self.assertEqual(attrs["gen_ai.agent.name"], "hermes")
        self.assertEqual(attrs["prompt"], "[CONTENT_OMITTED]")
        self.assertEqual(attrs["tool_output"], "[CONTENT_OMITTED]")
        self.assertEqual(attrs["api_key"], "[REDACTED_SECRET]")
        self.assertEqual(attrs["authorization"], "[REDACTED_SECRET]")
        serialized = json.dumps(attrs)
        self.assertNotIn("private customer prompt", serialized)
        self.assertNotIn("sk-super-secret", serialized)

    def test_nested_content_and_secret_keys_are_redacted(self) -> None:
        attrs = self.mod.sanitize_attributes(
            {
                "metadata": {
                    "prompt": "nested private prompt",
                    "nested": {"token": "plain-looking-token-value", "safe": "visible"},
                }
            },
            classification="INTERNAL",
            include_content=False,
        )
        self.assertEqual(attrs["metadata"]["prompt"], "[CONTENT_OMITTED]")
        self.assertEqual(attrs["metadata"]["nested"]["token"], "[REDACTED_SECRET]")
        self.assertEqual(attrs["metadata"]["nested"]["safe"], "visible")
        serialized = json.dumps(attrs)
        self.assertNotIn("nested private prompt", serialized)
        self.assertNotIn("plain-looking-token-value", serialized)

    def test_sensitive_classifications_remain_metadata_only(self) -> None:
        for classification in ("LEGAL_PRIVILEGED", "FINANCIAL", "SECURITY_SENSITIVE", "CREDENTIAL"):
            attrs = self.mod.sanitize_attributes(
                {"message": "sensitive body", "run_id": "run-1"},
                classification=classification,
                include_content=True,
            )
            self.assertEqual(attrs["message"], "[CONTENT_OMITTED]")
            self.assertEqual(attrs["run_id"], "run-1")

    def test_local_span_store_is_append_only_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "spans.jsonl"
            ctx = self.mod.new_trace_context()
            span = self.mod.build_span(
                name="hermes.dispatch",
                kind="agent",
                trace_id=ctx["trace_id"],
                span_id=ctx["span_id"],
                parent_span_id="",
                start_ns=10,
                end_ns=20,
                status="OK",
                classification="INTERNAL",
                attributes={"run_id": "r1"},
            )
            self.mod.append_local_span(path, span)
            self.mod.append_local_span(path, span)
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["trace_id"], ctx["trace_id"])
            self.assertEqual(rows[0]["name"], "hermes.dispatch")

    def test_non_strict_export_failure_does_not_break_local_span(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "spans.jsonl"
            ctx = self.mod.new_trace_context()
            result = self.mod.emit_span(
                output_path=path,
                name="test",
                kind="internal",
                trace_id=ctx["trace_id"],
                span_id=ctx["span_id"],
                start_ns=1,
                end_ns=2,
                status="OK",
                classification="INTERNAL",
                attributes={},
                endpoint="http://127.0.0.1:1/v1/traces",
                export_enabled=True,
                strict=False,
            )
            self.assertTrue(path.is_file())
            self.assertFalse(result["exported"])
            self.assertTrue(result["local_written"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
