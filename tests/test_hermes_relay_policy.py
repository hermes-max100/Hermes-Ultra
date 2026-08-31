from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/system/hermes_relay_policy.py"
POLICY = ROOT / "config/hermes-relay-policy.json"
EXPECTED_OPERATIONS = ['android_ping', 'android_read_screen', 'android_find_nodes', 'android_tap', 'android_tap_text', 'android_long_press', 'android_type', 'android_swipe', 'android_drag', 'android_open_app', 'android_press_key', 'android_screenshot', 'android_scroll', 'android_wait', 'android_get_apps', 'android_current_app', 'android_media', 'android_describe_node', 'android_setup', 'android_macro', 'android_clipboard_read', 'android_clipboard_write', 'android_screen_hash', 'android_diff_screen', 'android_send_intent', 'android_broadcast', 'android_events', 'android_event_stream', 'android_location', 'android_search_contacts', 'android_call', 'android_send_sms', 'android_return_to_hermes', 'android_share_media', 'android_send_mms', 'desktop_read_file', 'desktop_write_file', 'desktop_search_files', 'desktop_terminal', 'desktop_patch', 'desktop_powershell', 'desktop_spawn_detached', 'desktop_list_processes', 'desktop_kill_process', 'desktop_find_pid_by_port', 'desktop_job_start', 'desktop_job_status', 'desktop_job_logs', 'desktop_job_cancel', 'desktop_job_list', 'desktop_copy_directory', 'desktop_zip', 'desktop_unzip', 'desktop_checksum', 'desktop_health', 'desktop_computer_status', 'desktop_computer_screenshot', 'desktop_computer_action', 'desktop_computer_grant_request', 'desktop_computer_cancel']

def load_module():
    spec = importlib.util.spec_from_file_location("hermes_relay_policy_test", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module

class RelayPolicyTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.policy = self.mod.RelayPolicy.from_file(POLICY)

    def test_every_pinned_operation_is_explicitly_classified(self):
        config=json.loads(POLICY.read_text())
        configured={tool for value in config["classes"].values() for tool in value["operations"]}
        self.assertEqual(set(EXPECTED_OPERATIONS), configured)
        self.assertFalse(any("*" in tool for tool in configured))
        self.assertFalse(config["defaults"]["full_access_auto"])
        self.assertEqual(config["defaults"]["desktop_access"], "ask-every-time")
        self.assertEqual(config["defaults"]["unconfigured_access"], "restricted")

    def test_unknown_operation_fails_closed(self):
        with self.assertRaisesRegex(self.mod.RelayPolicyError, "unknown relay operation"):
            self.policy.classify("android_totally_new_power", target_device_id="phone-1")

    def test_missing_or_ambiguous_target_fails_closed(self):
        for target in ("", "*", "all", "phone-1,phone-2"):
            with self.subTest(target=target):
                with self.assertRaises(self.mod.RelayPolicyError):
                    self.policy.classify("android_ping", target_device_id=target)

    def test_read_only_operation_does_not_create_gate_request(self):
        decision=self.policy.classify("android_ping", target_device_id="phone-1")
        self.assertFalse(decision.consequential)
        with self.assertRaisesRegex(self.mod.RelayPolicyError, "non-consequential"):
            decision.to_gate_request(action_id="relay-read", principal="owner", actor="hermes", purpose="health check")

    def test_mutation_maps_to_existing_gate_schema(self):
        decision=self.policy.classify("android_tap", target_device_id="phone-1")
        request=decision.to_gate_request(action_id="relay-123", principal="owner", actor="hermes", purpose="approved device task")
        self.assertEqual(request["schema_version"], "hermes-consequential-action-v1")
        self.assertEqual(request["tool"], "android_tap")
        self.assertEqual(request["destination"], "device:phone-1")
        self.assertEqual(request["counterparty"], "device:phone-1")
        self.assertEqual(request["amount"], 0.0)

    def test_process_and_external_communications_are_high_risk(self):
        for tool in ("desktop_terminal", "desktop_powershell", "android_send_sms", "android_call"):
            with self.subTest(tool=tool):
                decision=self.policy.classify(tool, target_device_id="device-1")
                self.assertTrue(decision.consequential)
                self.assertEqual(decision.risk_class, "high")

    def test_policy_decisions_never_capture_raw_credentials(self):
        decision=self.policy.classify("android_tap", target_device_id="phone-1")
        dumped=json.dumps(decision.__dict__, sort_keys=True).lower()
        for forbidden in ("bearer", "session_token", "api_key", "authorization"):
            self.assertNotIn(forbidden, dumped)

if __name__ == "__main__":
    unittest.main(verbosity=2)
