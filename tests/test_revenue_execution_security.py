#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "src/system"
APPROVAL_SECRET = "approval-test-secret-that-is-longer-than-thirty-two-bytes"
CONTAINMENT_SECRET = "containment-test-secret-that-is-longer-than-thirty-two-bytes"


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def subparser(parser: argparse.ArgumentParser, name: str) -> argparse.ArgumentParser:
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return action.choices[name]


def options(parser: argparse.ArgumentParser) -> set[str]:
    return {opt for action in parser._actions for opt in action.option_strings}


def option_action(parser: argparse.ArgumentParser, option: str):
    for action in parser._actions:
        if option in action.option_strings:
            return action
    return None


class RevenueExecutionSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.outbound = load("hermes_outbound_security_test", "outbound-executor.py")
        cls.contact = load("hermes_contact_security_test", "contact-form-executor.py")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def unsigned_approval(self) -> dict:
        return {
            "schema_version": "revenue-approval-receipt-v1",
            "approval_id": "approve_forged",
            "experiment_id": "exp_redteam",
            "action": "send",
            "scope": "campaign",
            "approved_at": "2026-08-19T10:00:00Z",
            "expires_at": "2026-08-20T10:00:00Z",
            "approver": "forged-human",
            "policy_hash": "deadbeef",
            "source": "attacker",
            "notes": "machine forged",
        }

    def write_forged_sha_only_approval(self) -> None:
        receipt = self.unsigned_approval()
        receipt["approval_receipt_hash"] = hashlib.sha256(
            json.dumps(receipt, sort_keys=True).encode()
        ).hexdigest()
        path = self.root / "approval-receipts" / "approve_forged.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(receipt), encoding="utf-8")

    def test_sha_only_approval_is_not_authentic_authorization(self):
        self.write_forged_sha_only_approval()
        with patch.dict(os.environ, {"HERMES_APPROVAL_HMAC_SECRET": APPROVAL_SECRET}, clear=False):
            with self.assertRaises(SystemExit):
                self.outbound.load_approval(self.root, "approve_forged")

    def test_missing_approval_authenticator_fails_closed(self):
        self.write_forged_sha_only_approval()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                self.outbound.load_approval(self.root, "approve_forged")

    def test_authenticated_approval_round_trip_and_tamper_denial(self):
        security = self.outbound.approval_security
        signed = security.sign_receipt(self.unsigned_approval(), APPROVAL_SECRET)
        security.verify_receipt(signed, APPROVAL_SECRET)
        tampered = dict(signed)
        tampered["approver"] = "attacker"
        tampered["approval_receipt_hash"] = security.legacy_hash(
            {k: v for k, v in tampered.items() if k != "approval_receipt_hash"}
        )
        with self.assertRaises(security.ApprovalSecurityError):
            security.verify_receipt(tampered, APPROVAL_SECRET)

    def test_outbound_has_no_duplicate_or_sendmail_policy_off_switch(self):
        parser = self.outbound.build_parser()
        validate = subparser(parser, "validate-handoff")
        send = subparser(parser, "send")
        self.assertNotIn("--allow-duplicate", options(validate))
        self.assertNotIn("--allow-duplicate", options(send))
        transport = option_action(send, "--transport")
        self.assertIsNotNone(transport)
        self.assertEqual({"smtp"}, set(transport.choices or []))

    def test_outbound_send_requires_containment_token_from_stdin(self):
        send = subparser(self.outbound.build_parser(), "send")
        action = option_action(send, "--containment-token-stdin")
        self.assertIsNotNone(action)
        self.assertTrue(action.required)
        self.assertNotIn("--containment-token", options(send))

    def test_outbound_containment_is_bound_to_recipient_and_approval(self):
        destination = "tcp://smtp.example.com:587"
        scope = self.outbound.containment.RequestScope.make(
            "revenue-os:outbound-executor",
            "outbound:smtp",
            destination,
            "recipient:owner@example.com",
            "INTERNAL",
        )
        token = self.outbound.containment.issue_capability(
            secret=CONTAINMENT_SECRET,
            scope=scope,
            purpose="outbound-send",
            evidence_id="approve_123",
            ttl_seconds=60,
        )
        args = argparse.Namespace(approval_id="approve_123", containment_token_stdin=True)
        validation = {"contact_ref": "owner@example.com"}
        env = {
            "HERMES_CONTAINMENT_SECRET": CONTAINMENT_SECRET,
            "HERMES_CONTAINMENT_STATE_DIR": str(self.root / "containment"),
            "HERMES_SMTP_HOST": "smtp.example.com",
            "HERMES_SMTP_PORT": "587",
        }
        public_dns = [(2, 1, 6, "", ("93.184.216.34", 587))]
        with patch.dict(os.environ, env, clear=False), \
             patch.object(self.outbound.socket, "getaddrinfo", return_value=public_dns), \
             patch.object(self.outbound.containment, "load_json_stdin", return_value=token):
            receipt = self.outbound.verify_send_capability(validation, args)
        self.assertEqual("ALLOW", receipt["decision"])

        wrong_scope_token = self.outbound.containment.issue_capability(
            secret=CONTAINMENT_SECRET,
            scope=scope,
            purpose="outbound-send",
            evidence_id="approve_123",
            ttl_seconds=60,
        )
        wrong_validation = {"contact_ref": "other@example.com"}
        with patch.dict(os.environ, env, clear=False), \
             patch.object(self.outbound.socket, "getaddrinfo", return_value=public_dns), \
             patch.object(self.outbound.containment, "load_json_stdin", return_value=wrong_scope_token):
            with self.assertRaises(SystemExit):
                self.outbound.verify_send_capability(wrong_validation, args)

    def test_atomic_externalization_claim_blocks_duplicate_workers(self):
        env = {"HERMES_EXTERNALIZATION_STATE_DIR": str(self.root / "externalization")}
        with patch.dict(os.environ, env, clear=False):
            first = self.outbound.externalization.acquire("smtp", "camp_1", "pros_1")
            with self.assertRaises(self.outbound.externalization.ExternalizationClaimError):
                self.outbound.externalization.acquire("smtp", "camp_1", "pros_1")
            completed = self.outbound.externalization.complete(first, "receipt.json", "abc123")
        self.assertEqual("completed", completed["status"])
        self.assertTrue((self.root / "externalization" / "completed" / f"{first['claim_id']}.json").is_file())

    def test_full_outbound_send_uses_one_snapshot_and_records_security_receipts(self):
        validation = {
            "valid": True,
            "errors": [],
            "campaign_id": "camp_1",
            "experiment_id": "exp_1",
            "prospect_id": "pros_1",
            "business_name": "Example Co",
            "contact_ref": "owner@example.com",
            "message_hash": "message_hash",
            "message_subject": "Subject",
            "policy": {"campaign_policy_hash": "policy_hash"},
            "message": {"subject": "Subject", "body": "Body"},
        }
        scope = self.outbound.containment.RequestScope.make(
            "revenue-os:outbound-executor",
            "outbound:smtp",
            "tcp://smtp.example.com:587",
            "recipient:owner@example.com",
            "INTERNAL",
        )
        token = self.outbound.containment.issue_capability(
            secret=CONTAINMENT_SECRET,
            scope=scope,
            purpose="outbound-send",
            evidence_id="approve_1",
            ttl_seconds=60,
        )
        args = argparse.Namespace(
            transport="smtp", root=str(self.root), repo_root=str(ROOT),
            approval_id="approve_1", containment_token_stdin=True,
        )
        env = {
            "HERMES_CONTAINMENT_SECRET": CONTAINMENT_SECRET,
            "HERMES_CONTAINMENT_STATE_DIR": str(self.root / "containment"),
            "HERMES_EXTERNALIZATION_STATE_DIR": str(self.root / "externalization"),
            "HERMES_SMTP_HOST": "smtp.example.com",
            "HERMES_SMTP_PORT": "587",
        }
        public_dns = [(2, 1, 6, "", ("93.184.216.34", 587))]
        with patch.dict(os.environ, env, clear=False), \
             patch.object(self.outbound.core, "validate_send", return_value=validation) as validate_send, \
             patch.object(self.outbound.socket, "getaddrinfo", return_value=public_dns), \
             patch.object(self.outbound.containment, "load_json_stdin", return_value=token), \
             patch.object(self.outbound.core, "send_smtp", return_value={"transport": "smtp", "recipient": "owner@example.com", "sender": "sender@example.com"}), \
             patch.object(self.outbound.core, "record_sent_stage", return_value=None):
            rc = self.outbound.hardened_cmd_send(args)
        self.assertEqual(0, rc)
        self.assertEqual(1, validate_send.call_count)
        receipts = list((self.root / "outbound" / "send-receipts").glob("*.json"))
        self.assertEqual(1, len(receipts))
        receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertEqual("smtp", receipt["transport"])
        self.assertTrue(receipt["containment_grant_id"].startswith("cap_"))
        self.assertTrue(receipt["externalization_claim_id"].startswith("ext_"))

    def test_contact_form_has_no_private_network_or_duplicate_bypass(self):
        parser = self.contact.build_parser()
        for command in ("validate-handoff", "submit"):
            child = subparser(parser, command)
            self.assertNotIn("--allow-private-network-for-test", options(child))
            self.assertNotIn("--allow-duplicate", options(child))

    def test_contact_submit_requires_containment_token_from_stdin(self):
        submit = subparser(self.contact.build_parser(), "submit")
        action = option_action(submit, "--containment-token-stdin")
        self.assertIsNotNone(action)
        self.assertTrue(action.required)

    def test_contact_browser_guard_blocks_private_and_cross_site_requests(self):
        self.assertFalse(
            self.contact.request_is_authorized("http://127.0.0.1/admin", "http://127.0.0.1/form")
        )
        self.assertFalse(
            self.contact.request_is_authorized("https://attacker.invalid/pixel", "https://example.com/form")
        )
        self.assertTrue(self.contact.request_is_authorized("data:text/plain,ok", "https://example.com/form"))

    def test_contact_submit_uses_one_validation_snapshot(self):
        validation = {
            "valid": True,
            "errors": [],
            "campaign_id": "camp_1",
            "experiment_id": "exp_1",
            "prospect_id": "pros_1",
            "business_name": "Example Co",
            "policy": {"campaign_policy_hash": "policy_hash"},
            "official_domain": "example.com",
            "form_url": "https://example.com/contact",
            "message_hash": "message_hash",
            "message_subject": "Subject",
        }
        args = argparse.Namespace(
            root=str(self.root), repo_root=str(ROOT), approval_id="approve_1",
            operator_name="Operator", operator_email="operator@example.com",
            containment_token_stdin=True,
        )

        async def fake_browser(snapshot, _args):
            self.assertIs(snapshot, validation)
            return {
                "browser_run_id": "browser_test",
                "form_url": snapshot["form_url"],
                "confirmation_url": snapshot["form_url"] + "?submitted=1",
                "confirmation_text_hash": "confirm_hash",
                "confirmation_text_excerpt": "thank you",
                "submitted_fields": [],
                "pre_submit_screenshot": str(self.root / "pre.png"),
                "pre_submit_screenshot_hash": "pre_hash",
                "submission_screenshot": str(self.root / "post.png"),
                "submission_screenshot_hash": "post_hash",
                "network_policy": "same-site-public-http-only",
            }

        with patch.object(self.contact.core, "load_validation", return_value=validation) as load_validation, \
             patch.object(self.contact, "verify_submit_capability", return_value={"grant_id": "cap_1", "token_sha256": "token_hash"}), \
             patch.object(self.contact, "acquire_claim", return_value={"claim_id": "ext_test"}), \
             patch.object(self.contact.core, "submit_with_playwright", side_effect=fake_browser), \
             patch.object(self.contact.core, "record_sent_stage", return_value=None), \
             patch.object(self.contact.externalization, "complete", return_value={"status": "completed"}):
            rc = self.contact.hardened_cmd_submit(args)
        self.assertEqual(0, rc)
        self.assertEqual(1, load_validation.call_count)


if __name__ == "__main__":
    unittest.main(verbosity=2)
