#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/system/mcp-capability-composer.py"
CONFIG = ROOT / "config/mcp-toolkit-registry.json"
PROVIDERS = ROOT / "config/mcp-provider-registry.json"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def provider_registry(*, state: str = "ACTIVE", runtime_enabled: bool = True) -> dict[str, object]:
    return {
        "schema_version": "hermes-mcp-provider-registry-v1",
        "scout": {"role": "discovery_proposal_only", "can_promote": False},
        "providers": [
            {
                "id": "alpha",
                "display_name": "Alpha MCP",
                "lifecycle_state": state,
                "runtime_enabled": runtime_enabled,
                "profiles": ["coding", "research"],
                "capabilities": ["repository.read", "repository.write"],
                "effects": ["read", "external_write"],
                "transport": {"type": "streamable-http", "url": "https://alpha.example/mcp"},
                "auth": {"type": "none", "required_env": []},
                "provenance": {"kind": "official", "url": "https://alpha.example/docs"},
            },
            {
                "id": "beta",
                "display_name": "Beta MCP",
                "lifecycle_state": "INSTALLED_DISABLED",
                "runtime_enabled": False,
                "profiles": ["coding"],
                "capabilities": ["browser.automate", "browser.capture"],
                "effects": ["read", "external_write"],
                "transport": {"type": "stdio", "command": "beta-mcp", "args": []},
                "auth": {"type": "none", "required_env": []},
                "provenance": {"kind": "official", "url": "https://beta.example/docs"},
            },
        ],
        "platform_tools": [],
    }


def toolkit_registry() -> dict[str, object]:
    return {
        "schema_version": "hermes-mcp-toolkit-registry-v1",
        "authority": {
            "provider_registry": "config/mcp-provider-registry.json",
            "composition_can_promote": False,
            "composition_can_route": False,
        },
        "backends": {
            "mcp_market": {
                "kind": "provisioning_plan",
                "executes_remote_api": False,
            }
        },
        "toolkits": [
            {
                "id": "hermes_development",
                "display_name": "Hermes Development",
                "profile": "coding",
                "backend": "mcp_market",
                "runtime_enabled": True,
                "allowed_effects": ["read", "external_write"],
                "selections": [
                    {
                        "provider_id": "alpha",
                        "capability": "repository.read",
                        "effect": "read",
                        "alias": "repo_read",
                    },
                    {
                        "provider_id": "beta",
                        "capability": "browser.capture",
                        "effect": "read",
                        "alias": "browser_capture",
                    },
                ],
            }
        ],
    }


class MCPCapabilityComposerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module(MODULE, "hermes_mcp_capability_composer")

    def test_valid_registry_composes_without_becoming_authority(self):
        toolkits = toolkit_registry()
        self.assertEqual(self.mod.validate_toolkit_registry(toolkits, provider_registry()), [])
        manifest = self.mod.compose_toolkit(toolkits, provider_registry(), "hermes_development")
        self.assertEqual(manifest["authority"], "mcp-provider-registry")
        self.assertFalse(manifest["composition_can_promote"])
        self.assertFalse(manifest["composition_can_route"])
        self.assertEqual([tool["alias"] for tool in manifest["tools"]], ["repo_read", "browser_capture"])

    def test_candidate_or_discovered_source_is_rejected(self):
        for state in ("CANDIDATE", "DISCOVERED"):
            with self.subTest(state=state):
                errors = self.mod.validate_toolkit_registry(toolkit_registry(), provider_registry(state=state))
                self.assertTrue(any("not composable" in error for error in errors), errors)

    def test_profile_scope_is_enforced(self):
        config = toolkit_registry()
        config["toolkits"][0]["profile"] = "revenue"
        errors = self.mod.validate_toolkit_registry(config, provider_registry())
        self.assertTrue(any("profile revenue" in error for error in errors), errors)

    def test_unknown_capability_is_rejected(self):
        config = toolkit_registry()
        config["toolkits"][0]["selections"][0]["capability"] = "repository.delete"
        errors = self.mod.validate_toolkit_registry(config, provider_registry())
        self.assertTrue(any("does not advertise capability" in error for error in errors), errors)

    def test_effect_must_be_provider_supported_and_toolkit_allowed(self):
        config = toolkit_registry()
        config["toolkits"][0]["selections"][0]["effect"] = "delete"
        errors = self.mod.validate_toolkit_registry(config, provider_registry())
        self.assertTrue(any("does not advertise effect" in error for error in errors), errors)

        config = toolkit_registry()
        config["toolkits"][0]["allowed_effects"] = ["read"]
        errors = self.mod.validate_toolkit_registry(config, provider_registry())
        self.assertEqual(errors, [])
        config["toolkits"][0]["selections"][1]["effect"] = "external_write"
        errors = self.mod.validate_toolkit_registry(config, provider_registry())
        self.assertTrue(any("not allowed by toolkit" in error for error in errors), errors)

    def test_alias_collisions_are_rejected(self):
        config = toolkit_registry()
        config["toolkits"][0]["selections"][1]["alias"] = "repo_read"
        errors = self.mod.validate_toolkit_registry(config, provider_registry())
        self.assertTrue(any("duplicate alias" in error for error in errors), errors)

    def test_manifest_is_deterministic_and_records_source_provenance(self):
        config = toolkit_registry()
        first = self.mod.compose_toolkit(config, provider_registry(), "hermes_development")
        second = self.mod.compose_toolkit(config, provider_registry(), "hermes_development")
        self.assertEqual(first, second)
        self.assertRegex(first["manifest_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(first["tools"][0]["source"]["provider_id"], "alpha")
        self.assertEqual(first["tools"][0]["source"]["provenance"]["kind"], "official")
        self.assertEqual(first["tools"][0]["source"]["provenance"]["url"], "https://alpha.example/docs")

    def test_runtime_readiness_never_activates_disabled_source(self):
        manifest = self.mod.compose_toolkit(toolkit_registry(), provider_registry(), "hermes_development")
        self.assertTrue(manifest["runtime_enabled"])
        self.assertFalse(manifest["runtime_ready"])
        disabled = [tool for tool in manifest["tools"] if not tool["source"]["runtime_ready"]]
        self.assertEqual([tool["source"]["provider_id"] for tool in disabled], ["beta"])

    def test_mcp_market_backend_is_a_plan_not_an_undocumented_api_call(self):
        manifest = self.mod.compose_toolkit(toolkit_registry(), provider_registry(), "hermes_development")
        rendered = self.mod.render_backend(toolkit_registry(), manifest)
        self.assertEqual(rendered["schema_version"], "hermes-mcpmarket-toolkit-plan-v1")
        self.assertEqual(rendered["backend"], "mcp_market")
        self.assertEqual(rendered["mode"], "provisioning_plan")
        self.assertFalse(rendered["executes_remote_api"])
        self.assertEqual(rendered["manifest_digest"], manifest["manifest_digest"])
        self.assertEqual(rendered["tools"][0]["source_provider"], "alpha")
        serialized = json.dumps(rendered, sort_keys=True)
        self.assertNotIn("Authorization", serialized)
        self.assertNotIn("API_KEY", serialized)

    def test_default_toolkits_validate_against_canonical_provider_registry(self):
        data = self.mod.load_json(CONFIG)
        providers = self.mod.load_json(PROVIDERS)
        self.assertEqual(self.mod.validate_toolkit_registry(data, providers), [])
        ids = {row["id"] for row in data["toolkits"]}
        self.assertEqual(
            ids,
            {
                "hermes_development",
                "hermes_production_readonly",
                "hermes_security_lab",
                "hermes_revenue",
            },
        )
        production = next(row for row in data["toolkits"] if row["id"] == "hermes_production_readonly")
        self.assertEqual(production["allowed_effects"], ["read"])
        self.assertFalse(production["runtime_enabled"])
        security = next(row for row in data["toolkits"] if row["id"] == "hermes_security_lab")
        self.assertFalse(security["runtime_enabled"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
