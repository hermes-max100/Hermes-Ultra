#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/system/browser-workflow-cache.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_browser_workflow_cache", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load browser workflow cache")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def base_trace() -> dict:
    return {
        "schema_version": "browser-action-trace-v1",
        "workflow_id": "lead-contact-v1",
        "status": "success",
        "source_url": "https://example.com/contact",
        "security_classification": "INTERNAL",
        "evidence_refs": ["receipt:abc123"],
        "actions": [
            {"type": "navigate", "url": "https://example.com/contact"},
            {"type": "fill", "selector": "#email", "value": "{{email}}"},
            {"type": "fill", "selector": "#message", "value": "{{message}}"},
            {"type": "click", "selector": "button[type=submit]"},
            {"type": "assert_text", "selector": "body", "contains": "Thank you"},
        ],
    }


class BrowserWorkflowCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_module()

    def test_compile_creates_immutable_hash_bound_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = self.mod.compile_workflow(base_trace(), root)
            second = self.mod.compile_workflow(base_trace(), root)
            self.assertEqual(first["workflow_hash"], second["workflow_hash"])
            self.assertEqual(first["workflow_path"], second["workflow_path"])
            stored = json.loads(Path(first["workflow_path"]).read_text())
            self.assertEqual(stored["workflow_id"], "lead-contact-v1")
            self.assertTrue(stored["workflow_hash"].startswith("sha256:"))

            changed = base_trace()
            changed["actions"][4]["contains"] = "Message received"
            with self.assertRaises(self.mod.WorkflowSecurityError):
                self.mod.compile_workflow(changed, root)

    def test_compile_requires_success_and_evidence(self) -> None:
        trace = base_trace()
        trace["status"] = "failed"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(self.mod.WorkflowSecurityError):
                self.mod.compile_workflow(trace, Path(td))
        trace = base_trace()
        trace["evidence_refs"] = []
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(self.mod.WorkflowSecurityError):
                self.mod.compile_workflow(trace, Path(td))

    def test_cross_site_navigation_is_rejected(self) -> None:
        trace = base_trace()
        trace["actions"].insert(1, {"type": "navigate", "url": "https://attacker.example.net/form"})
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(self.mod.WorkflowSecurityError):
                self.mod.compile_workflow(trace, Path(td))

    def test_shared_hosting_sibling_is_not_same_site(self) -> None:
        trace = base_trace()
        trace["source_url"] = "https://victim.github.io/contact"
        trace["actions"][0] = {"type": "navigate", "url": "https://attacker.github.io/contact"}
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(self.mod.WorkflowSecurityError):
                self.mod.compile_workflow(trace, Path(td))

    def test_http_source_is_rejected(self) -> None:
        trace = base_trace()
        trace["source_url"] = "http://example.com/contact"
        trace["actions"][0] = {"type": "navigate", "url": "http://example.com/contact"}
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(self.mod.WorkflowSecurityError):
                self.mod.compile_workflow(trace, Path(td))

    def test_sensitive_parameters_and_fields_are_rejected(self) -> None:
        trace = base_trace()
        trace["actions"][1] = {"type": "fill", "selector": "#password", "value": "{{password}}"}
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(self.mod.WorkflowSecurityError):
                self.mod.compile_workflow(trace, Path(td))

    def test_dry_run_renders_parameters_but_receipt_contains_only_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            compiled = self.mod.compile_workflow(base_trace(), root)
            workflow = json.loads(Path(compiled["workflow_path"]).read_text())
            result = self.mod.render_workflow(workflow, {"email": "person@example.org", "message": "Hello there"})
            self.assertEqual(result["steps"][1]["value"], "person@example.org")
            receipt = self.mod.build_replay_receipt(workflow, result["steps"], status="dry_run", final_url=workflow["source_url"], duration_ms=3)
            serialized = json.dumps(receipt)
            self.assertNotIn("person@example.org", serialized)
            self.assertNotIn("Hello there", serialized)
            self.assertEqual(len(receipt["rendered_step_hashes"]), len(result["steps"]))

    def test_live_execute_requires_capability(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            compiled = self.mod.compile_workflow(base_trace(), root)
            workflow = json.loads(Path(compiled["workflow_path"]).read_text())
            with self.assertRaises(self.mod.WorkflowSecurityError):
                self.mod.require_execution_authorization(
                    workflow,
                    capability_path=None,
                    principal="agent:hermes",
                    data_class="INTERNAL",
                    repo_root=ROOT,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
