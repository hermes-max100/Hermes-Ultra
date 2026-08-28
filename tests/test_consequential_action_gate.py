from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/system/consequential-action-gate.py"
APPROVAL = ROOT / "src/system/approval-security.py"
SECRET = "consequential-action-test-secret-longer-than-thirty-two-bytes"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ConsequentialActionGateTests(unittest.TestCase):
    def setUp(self):
        self.mod = load(MODULE, "hermes_consequential_action_gate_test")
        self.security = load(APPROVAL, "hermes_approval_security_gate_test")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.t0 = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def grant(self, **overrides):
        value = {
            "schema_version": "hermes-authority-grant-v1",
            "grant_id": "grant-1",
            "principal": "owner",
            "actor": "revenue-os",
            "allowed_actions": ["payment", "external_message"],
            "allowed_tools": ["paypal", "smtp"],
            "allowed_destinations": ["vendor:approved", "recipient:lead@example.com"],
            "allowed_counterparties": ["vendor-1", "lead@example.com"],
            "max_single_amount": 100.0,
            "cumulative_budget": 150.0,
            "approval_required_actions": ["payment", "external_message"],
            "identity_ttl_seconds": 900,
            "required_evidence_types": ["purpose"],
            "expires_at": (self.t0 + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        }
        value.update(overrides)
        return value

    def request(self, action_id="act-1", amount=40.0, **overrides):
        value = {
            "schema_version": "hermes-consequential-action-v1",
            "action_id": action_id,
            "principal": "owner",
            "actor": "revenue-os",
            "action_type": "payment",
            "purpose": "Pay approved vendor invoice",
            "tool": "paypal",
            "destination": "vendor:approved",
            "counterparty": "vendor-1",
            "amount": amount,
            "risk_class": "FINANCIAL",
            "evidence_refs": [{"type": "purpose", "ref": "invoice:123"}],
        }
        value.update(overrides)
        return value

    def identity_event(self, when=None):
        when = when or self.t0
        return {
            "event_type": "identity_verified",
            "principal": "owner",
            "actor": "revenue-os",
            "verified_at": when.isoformat().replace("+00:00", "Z"),
            "evidence_id": "idv-1",
        }

    def approval(self, request):
        raw = {
            "schema_version": "consequential-action-approval-v1",
            "approval_id": "approve-1",
            "action_id": request["action_id"],
            "action": request["action_type"],
            "principal": request["principal"],
            "actor": request["actor"],
            "counterparty": request["counterparty"],
            "destination": request["destination"],
            "amount": request["amount"],
            "scope": "exact-action",
            "approved_at": self.t0.isoformat().replace("+00:00", "Z"),
            "expires_at": (self.t0 + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
            "approver": "owner",
            "policy_hash": "sha256:" + "a" * 64,
            "source": "trusted-governance",
        }
        return self.security.sign_receipt(raw, SECRET)

    def test_recent_identity_bound_approval_and_budget_allow_then_consume_once(self):
        req = self.request()
        gate = self.mod.ConsequentialActionGate(self.root)
        with patch.dict(os.environ, {"HERMES_APPROVAL_HMAC_SECRET": SECRET}, clear=False):
            receipt = gate.authorize(req, self.grant(), [self.identity_event()], self.approval(req), now=self.t0)
        self.assertEqual("ALLOW", receipt["decision"])
        self.assertEqual(110.0, receipt["remaining_budget_after"])
        self.assertEqual("idv-1", receipt["identity_evidence_id"])
        with patch.dict(os.environ, {"HERMES_APPROVAL_HMAC_SECRET": SECRET}, clear=False):
            with self.assertRaises(self.mod.GateError):
                gate.authorize(req, self.grant(), [self.identity_event()], self.approval(req), now=self.t0)

    def test_stale_identity_fails_closed(self):
        req = self.request()
        stale = self.identity_event(self.t0 - timedelta(hours=1))
        with patch.dict(os.environ, {"HERMES_APPROVAL_HMAC_SECRET": SECRET}, clear=False):
            with self.assertRaisesRegex(self.mod.GateError, "identity"):
                self.mod.ConsequentialActionGate(self.root).authorize(req, self.grant(), [stale], self.approval(req), now=self.t0)

    def test_cumulative_budget_is_persistent_across_gate_instances(self):
        req1 = self.request("act-1", 90.0)
        req2 = self.request("act-2", 70.0)
        with patch.dict(os.environ, {"HERMES_APPROVAL_HMAC_SECRET": SECRET}, clear=False):
            self.mod.ConsequentialActionGate(self.root).authorize(req1, self.grant(), [self.identity_event()], self.approval(req1), now=self.t0)
            with self.assertRaisesRegex(self.mod.GateError, "budget"):
                self.mod.ConsequentialActionGate(self.root).authorize(req2, self.grant(), [self.identity_event()], self.approval(req2), now=self.t0)

    def test_hmac_valid_but_wrong_counterparty_approval_is_denied(self):
        req = self.request()
        approval = self.approval(req)
        approval_body = {k: v for k, v in approval.items() if k not in {"approval_auth", "approval_receipt_hash"}}
        approval_body["counterparty"] = "attacker-vendor"
        wrong = self.security.sign_receipt(approval_body, SECRET)
        with patch.dict(os.environ, {"HERMES_APPROVAL_HMAC_SECRET": SECRET}, clear=False):
            with self.assertRaisesRegex(self.mod.GateError, "approval_binding"):
                self.mod.ConsequentialActionGate(self.root).authorize(req, self.grant(), [self.identity_event()], wrong, now=self.t0)

    def test_tool_destination_and_single_action_limit_are_enforced(self):
        gate = self.mod.ConsequentialActionGate(self.root)
        for req in (
            self.request(tool="unknown-tool"),
            self.request(destination="vendor:unapproved"),
            self.request(amount=101.0),
        ):
            with patch.dict(os.environ, {"HERMES_APPROVAL_HMAC_SECRET": SECRET}, clear=False):
                with self.assertRaises(self.mod.GateError):
                    gate.authorize(req, self.grant(), [self.identity_event()], self.approval(req), now=self.t0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
