#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/system/mcp-discovery-governance.py"
SOURCES = ROOT / "config/mcp-discovery-sources.json"
AGENT_REACH = ROOT / "src/system/agent-reach.sh"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MCPDiscoveryGovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module(MODULE, "hermes_mcp_discovery_governance")
        cls.data = cls.mod.load_source_registry(SOURCES)
        cls.sources = {row["id"]: row for row in cls.data["sources"]}

    def test_source_registry_is_valid_and_official_registry_is_canonical(self):
        self.assertEqual(self.mod.validate_source_registry(self.data), [])
        self.assertEqual(self.data["canonical_source"], "official_mcp_registry")
        canonical = self.sources["official_mcp_registry"]
        self.assertEqual(canonical["authority"], "canonical")
        self.assertEqual(canonical["trust"], "CANONICAL_DISCOVERY")
        self.assertTrue(canonical["url"].startswith("https://registry.modelcontextprotocol.io"))

    def test_allmcpservers_is_untrusted_discovery_only(self):
        source = self.sources["allmcpservers"]
        self.assertEqual(source["url"], "https://www.allmcpservers.com/")
        self.assertEqual(source["trust"], "UNTRUSTED_DISCOVERY_ONLY")
        self.assertEqual(source["authority"], "supplemental_discovery")
        self.assertFalse(source["can_verify"])
        self.assertFalse(source["can_promote"])
        self.assertFalse(source["can_install"])
        self.assertFalse(source["can_activate"])

    def test_vendor_repositories_are_provenance_verification_not_activation_authority(self):
        source = self.sources["vendor_repositories"]
        self.assertEqual(source["authority"], "provenance_verification")
        self.assertTrue(source["can_verify"])
        self.assertFalse(source["can_promote"])
        self.assertFalse(source["can_install"])
        self.assertFalse(source["can_activate"])

    def test_every_discovery_source_is_read_only_and_cannot_promote(self):
        for source in self.sources.values():
            self.assertTrue(source["can_discover"])
            self.assertFalse(source["can_promote"])
            self.assertFalse(source["can_install"])
            self.assertFalse(source["can_activate"])

    def test_source_order_puts_canonical_then_provenance_before_supplemental_sources(self):
        ordered = self.mod.ordered_sources(self.data)
        ids = [row["id"] for row in ordered]
        self.assertEqual(ids[0], "official_mcp_registry")
        self.assertLess(ids.index("vendor_repositories"), ids.index("allmcpservers"))
        self.assertLess(ids.index("allmcpservers"), ids.index("github_search"))

    def test_untrusted_candidate_normalization_cannot_escalate_lifecycle(self):
        candidate = self.mod.normalize_candidate(
            self.data,
            source_id="allmcpservers",
            name="Example MCP",
            homepage="https://example.invalid/mcp",
            repository="https://github.com/example/example-mcp",
        )
        self.assertEqual(candidate["lifecycle_state"], "DISCOVERED")
        self.assertFalse(candidate["runtime_enabled"])
        self.assertTrue(candidate["verification_required"])
        self.assertFalse(candidate["can_promote"])
        self.assertFalse(candidate["can_install"])
        self.assertFalse(candidate["can_activate"])
        self.assertEqual(candidate["source"]["trust"], "UNTRUSTED_DISCOVERY_ONLY")

    def test_normalizer_rejects_unknown_source_and_non_https_candidate_urls(self):
        with self.assertRaises(self.mod.DiscoveryGovernanceError):
            self.mod.normalize_candidate(self.data, source_id="unknown", name="bad")
        with self.assertRaises(self.mod.DiscoveryGovernanceError):
            self.mod.normalize_candidate(
                self.data,
                source_id="allmcpservers",
                name="bad",
                homepage="http://example.invalid/mcp",
            )

    def test_interface_choice_is_best_fit_not_mcp_by_default(self):
        choose = self.mod.choose_interface
        self.assertEqual(choose(self.data, ["official_mcp", "cli_skill"]), "cli_skill")
        self.assertEqual(choose(self.data, ["official_mcp", "official_api"]), "official_api")
        self.assertEqual(choose(self.data, ["official_mcp", "native"]), "native")
        self.assertEqual(choose(self.data, ["verified_community_mcp"]), "verified_community_mcp")
        self.assertIsNone(choose(self.data, []))

    def test_registry_rejects_any_source_with_activation_power(self):
        mutated = {
            **self.data,
            "sources": [dict(row) for row in self.data["sources"]],
        }
        mutated["sources"][0]["can_activate"] = True
        errors = self.mod.validate_source_registry(mutated)
        self.assertTrue(any("can_activate" in error for error in errors))

    def test_agent_reach_exposes_governed_mcp_sources_without_installing_anything(self):
        proc = subprocess.run(
            ["bash", str(AGENT_REACH), "mcp-sources"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        rows = json.loads(proc.stdout)
        self.assertEqual(rows[0]["id"], "official_mcp_registry")
        allmcp = next(row for row in rows if row["id"] == "allmcpservers")
        self.assertEqual(allmcp["trust"], "UNTRUSTED_DISCOVERY_ONLY")
        self.assertFalse(allmcp["can_install"])
        self.assertFalse(allmcp["can_activate"])

    def test_agent_reach_exposes_best_fit_interface_choice(self):
        proc = subprocess.run(
            ["bash", str(AGENT_REACH), "mcp-interface", "official_mcp", "cli_skill"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertEqual(json.loads(proc.stdout)["interface"], "cli_skill")


if __name__ == "__main__":
    unittest.main(verbosity=2)
