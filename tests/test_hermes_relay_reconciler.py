from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "system"))

from background_task_reconciler import BackgroundTaskReconciler, BackgroundTaskStore, ProviderInspection
from hermes_relay_adapter import RelayCompletionReceipt


class RelayReconcilerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import hermes_relay_reconciler as mod
        self.mod = mod
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.receipts = mod.RelayReceiptStore(self.root / "receipts")
        self.provider = BackgroundTaskStore(self.root / "provider")

    def tearDown(self):
        self.tmp.cleanup()

    def expectation(self, handle="req-1", **overrides):
        value = dict(task_id="task-1", target_device_id="phone-1", operation="android_tap", request_id="req-1", authorization_id="auth-1")
        value.update(overrides)
        self.receipts.register(handle, **value)
        return value

    def receipt(self, **overrides):
        value = dict(
            schema_version="hermes-relay-completion-receipt-v1",
            task_id="task-1",
            target_device_id="phone-1",
            channel="bridge",
            operation="android_tap",
            request_id="req-1",
            authorization_id="auth-1",
            terminal_status="success",
            result_digest="sha256:" + "a" * 64,
            verification_source="relay_response",
        )
        value.update(overrides)
        return RelayCompletionReceipt(**value)

    def make_reconciler(self, inspector):
        return BackgroundTaskReconciler(
            self.provider,
            inspectors={"relay": inspector.inspect},
            evidence_verifier=self.mod.relay_evidence_verifier(self.receipts),
            stale_after_seconds=1,
        )

    async def test_matching_receipt_reconciles_success_idempotently(self):
        self.expectation()
        self.receipts.record_completion("req-1", self.receipt())
        self.provider.register("bg-1", provider="relay", provider_task_id="req-1")
        reconciler = self.make_reconciler(self.mod.RelayTaskInspector(self.receipts))
        first = await reconciler.reconcile("bg-1")
        second = await reconciler.reconcile("bg-1")
        self.assertEqual(first["status"], "success")
        self.assertEqual(second["status"], "success")
        self.assertEqual(first["evidence"], ["relay-receipt:req-1"])

    async def test_mismatched_device_or_request_never_verifies(self):
        self.expectation()
        self.receipts.record_completion("req-1", self.receipt(target_device_id="phone-2", request_id="req-x"))
        self.provider.register("bg-2", provider="relay", provider_task_id="req-1")
        row = await self.make_reconciler(self.mod.RelayTaskInspector(self.receipts)).reconcile("bg-2")
        self.assertEqual(row["status"], "verificationPending")

    async def test_notification_only_cannot_be_success_and_is_redacted(self):
        self.expectation()
        self.provider.register("bg-3", provider="relay", provider_task_id="req-1")
        reconciler = self.make_reconciler(self.mod.RelayTaskInspector(self.receipts))
        self.mod.observe_relay_notification(reconciler, "bg-3", "bridge.response", {"session_token": "secret-token", "authorization": "Bearer secret", "status": 200})
        row = self.provider.load("bg-3")
        self.assertEqual(row["status"], "running")
        raw = (self.root / "provider" / "bg-3.json").read_text().lower()
        self.assertNotIn("secret-token", raw)
        self.assertNotIn("bearer secret", raw)

    async def test_revoked_session_is_provider_failure(self):
        self.expectation()
        self.provider.register("bg-4", provider="relay", provider_task_id="req-1")
        inspector = self.mod.RelayTaskInspector(self.receipts, session_validator=lambda _: False)
        row = await self.make_reconciler(inspector).reconcile("bg-4")
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["provider_status"], "failed")
        self.assertEqual(row["result"]["reason"], "relay_session_revoked")

    async def test_stale_unfinished_work_becomes_stalled(self):
        self.expectation("req-stale", request_id="req-stale")
        self.provider.register("bg-5", provider="relay", provider_task_id="req-stale")
        self.provider.update("bg-5", progress_fingerprint="relay-awaiting:req-stale", last_progress_at="2026-01-01T00:00:00Z")
        row = await self.make_reconciler(self.mod.RelayTaskInspector(self.receipts)).reconcile("bg-5")
        self.assertEqual(row["status"], "stalled")

    async def test_output_hash_or_durable_receipt_tamper_fails_closed(self):
        self.expectation()
        self.receipts.record_completion("req-1", self.receipt())
        inspector = self.mod.RelayTaskInspector(self.receipts)
        inspection = await inspector.inspect("req-1")
        bad = ProviderInspection(status=inspection.status, result=inspection.result, evidence=inspection.evidence, output_hash="sha256:" + "b" * 64, metadata=inspection.metadata)
        self.assertFalse(await self.mod.relay_evidence_verifier(self.receipts)("relay", "req-1", bad))
        path = self.receipts.path_for("req-1")
        raw = json.loads(path.read_text())
        raw["receipt"]["target_device_id"] = "attacker"
        path.write_text(json.dumps(raw))
        with self.assertRaises(self.mod.RelayReceiptError):
            await inspector.inspect("req-1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
