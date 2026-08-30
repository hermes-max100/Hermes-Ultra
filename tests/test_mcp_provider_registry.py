#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/system/mcp-provider-registry.py"
ROUTER = ROOT / "src/system/mcp-provider-router.py"
REGISTRY = ROOT / "config/mcp-provider-registry.json"

EXPECTED_MCP = {
    "github", "composio", "exa", "context7", "sentry", "supabase",
    "brightdata", "playwright", "kubernetes", "darknet", "malware_patrol",
    "whoisxml", "pentest_tools", "pentest_mcp", "coinrule", "alpaca",
    "tastytrade", "moltpe", "upload_post", "bundle_social", "socialbu",
    "telegram", "devops_mcp",
}


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MCPProviderRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module(MODULE, "hermes_mcp_provider_registry")
        cls.data = cls.mod.load_registry(REGISTRY)
        cls.providers = {row["id"]: row for row in cls.data["providers"]}

    def test_registry_covers_requested_universe(self):
        self.assertEqual(set(self.providers), EXPECTED_MCP)
        tools = {row["id"]: row for row in self.data["platform_tools"]}
        self.assertEqual(set(tools), {"mcpc"})
        self.assertFalse(tools["mcpc"]["runtime_enabled"])
        self.assertEqual(tools["mcpc"]["role"], "platform_tooling")

    def test_registry_is_valid_and_scout_is_discovery_only(self):
        self.assertEqual(self.mod.validate_registry(self.data), [])
        self.assertEqual(self.data["scout"]["role"], "discovery_proposal_only")
        self.assertFalse(self.data["scout"]["can_promote"])
        for provider in self.providers.values():
            self.assertIn(provider["lifecycle_state"], self.mod.LIFECYCLE_STATES)
            self.assertTrue(provider["profiles"])
            self.assertTrue(provider["capabilities"])
            self.assertTrue(provider["effects"])
            self.assertTrue(provider["provenance"]["url"].startswith("https://"))

    def test_remote_endpoints_are_https_and_secrets_are_references(self):
        raw = REGISTRY.read_text(encoding="utf-8")
        forbidden = ["sk_live_", "sk-test-", "ghp_", "Bearer ey", "password="]
        self.assertFalse(any(token in raw for token in forbidden))
        for provider in self.providers.values():
            transport = provider["transport"]
            if transport["type"] == "streamable-http" and "url" in transport:
                self.assertTrue(transport["url"].startswith("https://"))
                self.assertNotIn("token=", transport["url"].lower())
                self.assertNotIn("apikey=", transport["url"].lower())
            auth = provider["auth"]
            for key in auth.get("required_env", []):
                self.assertRegex(key, r"^[A-Z][A-Z0-9_]+$")

    def test_current_verified_routes_are_encoded(self):
        self.assertEqual(self.providers["github"]["transport"]["url"], "https://api.githubcopilot.com/mcp/")
        self.assertEqual(self.providers["exa"]["transport"]["url"], "https://mcp.exa.ai/mcp")
        self.assertEqual(self.providers["context7"]["transport"]["url"], "https://mcp.context7.com/mcp/oauth")
        self.assertEqual(self.providers["supabase"]["transport"]["url"], "https://mcp.supabase.com/mcp?read_only=true&features=docs,database,debugging")
        self.assertEqual(self.providers["coinrule"]["transport"]["url"], "https://cloud.coinrule.com/mcp")
        self.assertEqual(self.providers["whoisxml"]["transport"]["url"], "https://mcp-hosted.whoisxmlapi.com/mcp")
        self.assertEqual(self.providers["upload_post"]["transport"]["url"], "https://mcp.upload-post.com/mcp")
        self.assertEqual(self.providers["socialbu"]["transport"]["url"], "https://socialbu.com/mcp")

    def test_playwright_is_pinned_isolated_and_active(self):
        row = self.providers["playwright"]
        self.assertEqual(row["lifecycle_state"], "ACTIVE")
        self.assertEqual(row["transport"]["command"], "npx")
        self.assertIn("@playwright/mcp@0.0.79", row["transport"]["args"])
        self.assertIn("--headless", row["transport"]["args"])
        self.assertIn("--isolated", row["transport"]["args"])

    def test_renderer_enables_only_ready_automatic_providers(self):
        rendered = self.mod.render_hermes_servers(self.data, environ={})
        self.assertTrue(rendered["exa"]["enabled"])
        self.assertTrue(rendered["playwright"]["enabled"])
        self.assertFalse(rendered["context7"]["enabled"])
        self.assertEqual(rendered["context7"]["auth"], "oauth")
        self.assertFalse(rendered["coinrule"]["enabled"])
        self.assertFalse(rendered["kubernetes"]["enabled"])
        self.assertNotIn("malware_patrol", rendered)

    def test_renderer_preserves_custom_auth_templates_without_secret_values(self):
        rendered = self.mod.render_hermes_servers(self.data, environ={"MALWARE_PATROL_MCP_URL": "https://example.invalid/mcp"})
        self.assertEqual(rendered["upload_post"]["headers"]["Authorization"], "ApiKey ${UPLOAD_POST_API_KEY}")
        self.assertEqual(rendered["composio"]["headers"]["x-api-key"], "${COMPOSIO_API_KEY}")
        self.assertEqual(rendered["brightdata"]["env"]["API_TOKEN"], "${BRIGHTDATA_API_TOKEN}")
        self.assertEqual(rendered["malware_patrol"]["url"], "https://example.invalid/mcp")
        self.assertFalse(rendered["malware_patrol"]["enabled"])

    def test_spend_trade_and_security_execution_are_not_automatic(self):
        for provider_id in ("coinrule", "alpaca", "tastytrade", "moltpe", "pentest_tools", "pentest_mcp", "devops_mcp"):
            row = self.providers[provider_id]
            self.assertFalse(row["runtime_enabled"])
        self.assertIn("spend_money", self.providers["moltpe"]["effects"])
        self.assertIn("live_trade", self.providers["alpaca"]["effects"])
        self.assertIn("authorized_security_execution", self.providers["pentest_mcp"]["effects"])

    def test_candidate_selection_respects_profile_capability_effect_and_state(self):
        coding = self.mod.select_candidates(self.data, profile="coding", capability="browser.automate", effect="external_write")
        self.assertEqual([row["id"] for row in coding], ["playwright"])
        research = self.mod.select_candidates(self.data, profile="research", capability="web.search", effect="read")
        self.assertIn("exa", [row["id"] for row in research])
        security = self.mod.select_candidates(self.data, profile="security_research", capability="security.scan", effect="authorized_security_execution")
        self.assertEqual(security, [])
        security_all = self.mod.select_candidates(self.data, profile="security_research", capability="security.scan", effect="authorized_security_execution", include_inactive=True)
        self.assertTrue({"pentest_tools", "pentest_mcp"}.intersection({row["id"] for row in security_all}))

    def test_router_uses_same_progressive_registry_selection(self):
        router = load_module(ROUTER, "hermes_mcp_provider_router_test")
        rows = router.select_registry_providers(profile="coding", capability="browser.automate", effect="external_write", registry_path=REGISTRY)
        self.assertEqual([row["id"] for row in rows], ["playwright"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
