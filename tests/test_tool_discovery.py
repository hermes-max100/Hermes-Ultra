#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/system/tool-discovery.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_tool_discovery", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ToolDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.registry = {
            "schema_version": "hermes-tool-registry-v1",
            "tools": [
                {"name":"memory.search","namespace":"memory","description":"Search Memory Fabric facts decisions failures and provenance","keywords":["memory","recall","facts","history"],"mutating":False,"data_classes":["PUBLIC","INTERNAL","CONFIDENTIAL","LEGAL_PRIVILEGED","FINANCIAL","SECURITY_SENSITIVE"],"required_capabilities":[],"input_schema":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]},"source":"src/system/memory-fabric.py"},
                {"name":"skills.find","namespace":"skills","description":"Find relevant Hermes skills for a task","keywords":["skills","routing","capabilities"],"mutating":False,"data_classes":["PUBLIC","INTERNAL"],"required_capabilities":[],"input_schema":{"type":"object","properties":{"query":{"type":"string"}}},"source":"src/system/skill-router-v3.sh"},
                {"name":"jarvis.browser","namespace":"jarvis","description":"Open a governed public website in the JARVIS browser","keywords":["browser","website","playwright","web"],"mutating":True,"data_classes":["PUBLIC","INTERNAL"],"required_capabilities":["network.public.browser"],"input_schema":{"type":"object","properties":{"url":{"type":"string"}}},"source":"src/system/jarvis-armory.sh"}
            ]
        }

    def test_search_prefers_semantically_relevant_tool(self):
        rows = self.mod.search_tools(self.registry, "recall a prior fact from memory", limit=2, data_class="INTERNAL")
        self.assertEqual(rows[0]["name"], "memory.search")
        self.assertGreater(rows[0]["score"], rows[-1]["score"])

    def test_mutating_and_capability_tools_are_filtered_before_schema_exposure(self):
        rows = self.mod.search_tools(self.registry, "open website in browser", limit=5, data_class="INTERNAL")
        self.assertNotIn("jarvis.browser", [row["name"] for row in rows])
        rows = self.mod.search_tools(self.registry, "open website in browser", limit=5, data_class="INTERNAL", allow_mutating=True, available_capabilities={"network.public.browser"})
        self.assertEqual(rows[0]["name"], "jarvis.browser")

    def test_data_class_filter_happens_before_tool_is_returned(self):
        rows = self.mod.search_tools(self.registry, "memory search find skills", limit=5, data_class="LEGAL_PRIVILEGED")
        self.assertNotIn("skills.find", [row["name"] for row in rows])
        self.assertIn("memory.search", [row["name"] for row in rows])

    def test_unrelated_query_exposes_no_tool_schemas(self):
        rows = self.mod.search_tools(self.registry, "quantum banana astronomy", limit=5, data_class="INTERNAL")
        self.assertEqual(rows, [])

    def test_compact_context_only_contains_selected_schemas(self):
        rows = self.mod.search_tools(self.registry, "memory recall", limit=1, data_class="INTERNAL")
        context = self.mod.compact_context(self.registry, rows)
        self.assertEqual([tool["name"] for tool in context["tools"]], ["memory.search"])
        self.assertIn("input_schema", context["tools"][0])
        self.assertNotIn("keywords", context["tools"][0])
        self.assertNotIn("jarvis.browser", json.dumps(context))

    def test_registry_hash_is_stable_across_key_order(self):
        self.assertEqual(self.mod.registry_hash(self.registry), self.mod.registry_hash(json.loads(json.dumps(self.registry, sort_keys=True))))

    def test_load_registry_rejects_duplicate_tool_names(self):
        bad = json.loads(json.dumps(self.registry)); bad["tools"].append(json.loads(json.dumps(bad["tools"][0])))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "registry.json"; path.write_text(json.dumps(bad), encoding="utf-8")
            with self.assertRaises(ValueError): self.mod.load_registry(path)


if __name__ == "__main__": unittest.main(verbosity=2)
