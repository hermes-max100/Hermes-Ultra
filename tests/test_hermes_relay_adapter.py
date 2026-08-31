from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/system/hermes_relay_adapter.py"


def load_module():
    name = "hermes_relay_adapter_test"
    spec = importlib.util.spec_from_file_location(name, MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class RelayAdapterTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def auth_ok(self, *, version="1.10.0", expires_at=None, grants=None):
        return {
            "type": "auth.ok",
            "payload": {
                "session_token": "relay-secret-token",
                "server_version": version,
                "expires_at": expires_at,
                "grants": grants or {"bridge": None},
                "client_surface": "android",
                "device_form_factor": "phone",
            },
        }

    def test_auth_ok_is_version_pinned_and_does_not_store_raw_token(self):
        state = self.mod.RelaySessionState.from_auth_ok(self.auth_ok())
        self.assertEqual(state.server_version, "1.10.0")
        self.assertTrue(state.token_sha256.startswith("sha256:"))
        self.assertNotIn("relay-secret-token", repr(state))
        with self.assertRaisesRegex(self.mod.RelayProtocolError, "server version"):
            self.mod.RelaySessionState.from_auth_ok(self.auth_ok(version="1.11.0"))

    def test_grant_expiry_and_null_never_expire(self):
        state = self.mod.RelaySessionState.from_auth_ok(
            self.auth_ok(expires_at=2000.0, grants={"bridge": None, "desktop": 1500.0})
        )
        self.assertTrue(state.session_active(1000.0))
        self.assertTrue(state.grant_active("bridge", 999999.0))
        self.assertTrue(state.grant_active("desktop", 1499.0))
        self.assertFalse(state.grant_active("desktop", 1500.0))
        self.assertFalse(state.session_active(2000.0))

    def test_bridge_capability_schema_one_only(self):
        caps = self.mod.RelayBridgeCapabilities.from_status_payload({
            "capabilities": {
                "schema_version": 1,
                "permanent": ["screen_read"],
                "timed": {"device_control": 5000},
                "unlimited": ["notifications"],
            }
        })
        self.assertEqual(caps.schema_version, 1)
        self.assertIn("screen_read", caps.permanent)
        with self.assertRaisesRegex(self.mod.RelayProtocolError, "capability schema"):
            self.mod.RelayBridgeCapabilities.from_status_payload({"capabilities": {"schema_version": 2}})

    def test_bridge_response_requires_target_and_request_correlation(self):
        envelope = {"type": "bridge.response", "payload": {"request_id": "req-1", "status": 200, "result": {"ok": True}}}
        receipt = self.mod.RelayCompletionReceipt.from_bridge_response(
            envelope,
            task_id="task-1",
            target_device_id="phone-1",
            actual_device_id="phone-1",
            operation="android_tap",
            expected_request_id="req-1",
            authorization_id="auth-1",
        )
        self.assertEqual(receipt.terminal_status, "success")
        with self.assertRaisesRegex(self.mod.RelayProtocolError, "device"):
            self.mod.RelayCompletionReceipt.from_bridge_response(envelope, task_id="task-1", target_device_id="phone-1", actual_device_id="phone-2", operation="android_tap", expected_request_id="req-1", authorization_id="auth-1")
        with self.assertRaisesRegex(self.mod.RelayProtocolError, "request"):
            self.mod.RelayCompletionReceipt.from_bridge_response(envelope, task_id="task-1", target_device_id="phone-1", actual_device_id="phone-1", operation="android_tap", expected_request_id="req-2", authorization_id="auth-1")

    def test_completion_receipt_contains_digest_not_sensitive_result_bodies(self):
        envelope = {"type": "bridge.response", "payload": {"request_id": "req-1", "status": 200, "result": {"clipboard": "secret clip", "screen": "secret screen", "notification_body": "secret note", "authorization": "Bearer secret", "api_key": "sk-secret"}}}
        receipt = self.mod.RelayCompletionReceipt.from_bridge_response(envelope, task_id="task-1", target_device_id="phone-1", actual_device_id="phone-1", operation="android_tap", expected_request_id="req-1", authorization_id="auth-1")
        raw = json.dumps(receipt.to_dict(), sort_keys=True).lower()
        self.assertTrue(receipt.result_digest.startswith("sha256:"))
        for secret in ("secret clip", "secret screen", "secret note", "bearer secret", "sk-secret"):
            self.assertNotIn(secret, raw)

    def test_typed_stream_event_schema_and_dedupe_are_bounded(self):
        d = self.mod.RelayEventDeduper(max_entries=3)
        def event(seq, name="assistant.delta"):
            return {"type": "stream.event", "schema_version": 1, "session_id": "s1", "run_id": "r1", "seq": seq, "event": name, "ts": "2026-08-28T00:00:00Z", "payload": {}}
        first = d.observe(event(1))
        dup = d.observe(event(1, "run.completed"))
        newer = d.observe(event(3, "run.completed"))
        older = d.observe(event(2, "run.completed"))
        self.assertTrue(first.accepted)
        self.assertFalse(dup.accepted)
        self.assertFalse(dup.terminal_success)
        self.assertTrue(newer.terminal_success)
        self.assertFalse(older.accepted)
        self.assertFalse(older.terminal_success)
        d.observe({**event(4), "session_id": "s2"})
        d.observe({**event(5), "session_id": "s3"})
        self.assertLessEqual(d.size, 3)
        with self.assertRaisesRegex(self.mod.RelayProtocolError, "stream event schema"):
            d.observe({**event(6), "schema_version": 2})


if __name__ == "__main__":
    unittest.main(verbosity=2)
