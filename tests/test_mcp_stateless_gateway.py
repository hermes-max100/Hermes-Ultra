#!/usr/bin/env python3
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/system/mcp-stateless-gateway.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_mcp_stateless", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class MCPStatelessGatewayTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.headers = {"MCP-Protocol-Version":"2026-07-28","Mcp-Method":"tools/call","Mcp-Name":"memory.search"}
        self.body = {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"memory.search","arguments":{"query":"prior fact"},"_meta":{"io.modelcontextprotocol/clientInfo":{"name":"hermes-web","version":"1.0"},"io.modelcontextprotocol/clientCapabilities":{"sampling":False}}}}

    def test_valid_2026_request_is_self_describing_and_routable(self):
        result=self.mod.validate_request(self.headers,self.body)
        self.assertTrue(result["valid"]); self.assertEqual(result["protocol_version"],"2026-07-28"); self.assertEqual(result["method"],"tools/call"); self.assertEqual(result["name"],"memory.search"); self.assertEqual(result["client"]["name"],"hermes-web")

    def test_session_id_and_initialize_are_rejected(self):
        headers=dict(self.headers); headers["Mcp-Session-Id"]="old-session"
        with self.assertRaises(ValueError): self.mod.validate_request(headers,self.body)
        body=json.loads(json.dumps(self.body)); body["method"]="initialize"; headers=dict(self.headers); headers["Mcp-Method"]="initialize"; headers["Mcp-Name"]="initialize"
        with self.assertRaises(ValueError): self.mod.validate_request(headers,body)

    def test_header_method_and_name_must_match_json_body(self):
        headers=dict(self.headers); headers["Mcp-Method"]="tools/list"
        with self.assertRaises(ValueError): self.mod.validate_request(headers,self.body)
        headers=dict(self.headers); headers["Mcp-Name"]="other.tool"
        with self.assertRaises(ValueError): self.mod.validate_request(headers,self.body)

    def test_client_identity_meta_is_required(self):
        body=json.loads(json.dumps(self.body)); body["params"].pop("_meta")
        with self.assertRaises(ValueError): self.mod.validate_request(self.headers,body)

    def test_containment_scope_is_derived_from_routing_headers_not_arguments(self):
        validated=self.mod.validate_request(self.headers,self.body)
        scope=self.mod.build_containment_scope(validated,destination="https://jarvis.example.com",data_class="INTERNAL")
        self.assertEqual(scope["principal"],"mcp:hermes-web"); self.assertEqual(scope["tool"],"mcp:memory.search"); self.assertEqual(scope["resource"],"mcp:tools/call:memory.search"); self.assertEqual(scope["destination"],"https://jarvis.example.com"); self.assertNotIn("prior fact",json.dumps(scope))

    def test_issuer_must_match_expected_authorization_server_exactly(self):
        self.assertTrue(self.mod.validate_issuer("https://auth.example.com","https://auth.example.com"))
        with self.assertRaises(ValueError): self.mod.validate_issuer("https://evil.example.com","https://auth.example.com")
        with self.assertRaises(ValueError): self.mod.validate_issuer("https://auth.example.com/","https://auth.example.com")

    def test_cache_hints_are_bounded_and_list_order_is_deterministic(self):
        result={"tools":[{"name":"zeta","description":"z"},{"name":"alpha","description":"a"}],"ttlMs":60000,"cacheScope":"private"}
        normalized=self.mod.normalize_cacheable_result("tools/list",result,max_ttl_ms=120000)
        self.assertEqual([row["name"] for row in normalized["tools"]],["alpha","zeta"]); self.assertEqual(normalized["ttlMs"],60000)
        with self.assertRaises(ValueError): self.mod.normalize_cacheable_result("tools/list",{**result,"ttlMs":999999},max_ttl_ms=120000)

    def test_mrtr_input_required_maps_to_approval_request_without_session_state(self):
        value={"resultType":"input_required","requests":[{"type":"elicitation","message":"Approve this action?"}]}
        mapped=self.mod.map_input_required(value,request_id="req-123")
        self.assertEqual(mapped["state"],"input_required"); self.assertEqual(mapped["request_id"],"req-123"); self.assertEqual(mapped["approval_boundary"],"hermes-approvals"); self.assertNotIn("session",json.dumps(mapped).lower())

    def test_legacy_protocol_is_feature_flagged_not_silently_accepted(self):
        headers=dict(self.headers); headers["MCP-Protocol-Version"]="2025-11-25"
        with self.assertRaises(ValueError): self.mod.validate_request(headers,self.body)
        result=self.mod.validate_request(headers,self.body,allow_legacy=True)
        self.assertFalse(result["stateless"]); self.assertEqual(result["migration_action"],"legacy_adapter_required")


if __name__ == "__main__": unittest.main(verbosity=2)
