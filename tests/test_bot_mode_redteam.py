#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/system/bot-mode-governance.py"
POLICY_PATH = ROOT / "config/bot-mode-policy.json"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_bot_mode_governance_redteam", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Bot Mode governance module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BotModeRedTeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_module()
        cls.policy = cls.mod.load_policy(POLICY_PATH)

    def test_each_bot_has_explicit_data_class_intake_policy(self) -> None:
        bots = {bot["id"]: bot for bot in self.policy["bots"]}
        self.assertEqual(bots["research"]["allowed_data_classes"], ["PUBLIC", "INTERNAL"])
        self.assertEqual(bots["legal"]["allowed_data_classes"], ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "LEGAL_PRIVILEGED"])
        self.assertEqual(bots["revenue"]["allowed_data_classes"], ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "FINANCIAL"])
        for bot in bots.values():
            self.assertNotIn("CREDENTIAL", bot["allowed_data_classes"])

    def test_sensitive_cross_bot_flow_is_denied(self) -> None:
        cases = (
            ("legal", "research", "LEGAL_PRIVILEGED"),
            ("revenue", "research", "FINANCIAL"),
            ("coding", "creator", "SECURITY_SENSITIVE"),
        )
        for sender, recipient, classification in cases:
            with self.subTest(sender=sender, recipient=recipient, classification=classification):
                with self.assertRaises(self.mod.GovernanceError):
                    self.mod.create_message(
                        self.policy,
                        sender=sender,
                        recipient=recipient,
                        classification=classification,
                        purpose="handoff",
                        body="sensitive payload",
                        evidence_parent="ev_sensitive",
                    )

    def test_sender_must_be_allowed_to_handle_declared_classification(self) -> None:
        with self.assertRaises(self.mod.GovernanceError):
            self.mod.create_message(
                self.policy,
                sender="creator",
                recipient="coding",
                classification="SECURITY_SENSITIVE",
                purpose="handoff",
                body="payload",
                evidence_parent="ev_sender_flow",
            )

    def test_council_intake_is_intersection_safe(self) -> None:
        council = next(item for item in self.policy["councils"] if item["id"] == "hermes-council")
        self.assertEqual(council["allowed_data_classes"], ["PUBLIC", "INTERNAL"])
        with self.assertRaises(self.mod.GovernanceError):
            self.mod.create_message(
                self.policy,
                sender="legal",
                recipient="hermes-council",
                classification="LEGAL_PRIVILEGED",
                purpose="council_request",
                body="privileged",
                evidence_parent="ev_privileged",
            )

    def test_policy_validation_requires_profile_manifest_membership(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "profiles/fake").mkdir(parents=True)
            (root / "profiles/fake/SOUL.md").write_text("# fake\n", encoding="utf-8")
            (root / "profiles").mkdir(exist_ok=True)
            manifest = json.loads((ROOT / "profiles/profile_manifest.json").read_text(encoding="utf-8"))
            shutil.copytree(ROOT / "profiles/legal", root / "profiles/legal")
            shutil.copytree(ROOT / "profiles/coding", root / "profiles/coding")
            shutil.copytree(ROOT / "profiles/revenue", root / "profiles/revenue")
            shutil.copytree(ROOT / "profiles/creator", root / "profiles/creator")
            (root / "profiles/profile_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            mutated = copy.deepcopy(self.policy)
            research = next(bot for bot in mutated["bots"] if bot["id"] == "research")
            research["profile"] = "fake"
            with self.assertRaises(self.mod.GovernanceError):
                self.mod.validate_policy(mutated, root=root)

    def test_runtime_cli_does_not_accept_caller_policy_override(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(MODULE_PATH), "validate-policy", "--help"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("--policy", proc.stdout)

    def test_classification_is_canonical_not_rank_coerced(self) -> None:
        with self.assertRaises(self.mod.GovernanceError):
            self.mod.create_message(
                self.policy,
                sender="research",
                recipient="legal",
                classification="public",
                purpose="handoff",
                body="payload",
                evidence_parent="ev_case",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
