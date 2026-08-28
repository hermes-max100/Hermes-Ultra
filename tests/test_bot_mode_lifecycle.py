#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/system/bot-mode-governance.py"
POLICY_PATH = ROOT / "config/bot-mode-policy.json"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_bot_mode_lifecycle", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Bot Mode governance module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BotModeLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_module()
        cls.policy = cls.mod.load_policy(POLICY_PATH)

    def test_inactive_bot_cannot_send_or_receive(self) -> None:
        mutated = copy.deepcopy(self.policy)
        creator = next(bot for bot in mutated["bots"] if bot["id"] == "creator")
        creator["active"] = False
        self.mod.validate_policy(mutated, root=ROOT)

        with self.assertRaises(self.mod.GovernanceError):
            self.mod.create_message(
                mutated,
                sender="creator",
                recipient="coding",
                classification="INTERNAL",
                purpose="handoff",
                body="x",
                evidence_parent="ev_inactive_send",
            )
        with self.assertRaises(self.mod.GovernanceError):
            self.mod.create_message(
                mutated,
                sender="coding",
                recipient="creator",
                classification="INTERNAL",
                purpose="handoff",
                body="x",
                evidence_parent="ev_inactive_receive",
            )

    def test_inactive_bot_cannot_remain_on_council(self) -> None:
        mutated = copy.deepcopy(self.policy)
        research = next(bot for bot in mutated["bots"] if bot["id"] == "research")
        research["active"] = False
        with self.assertRaises(self.mod.GovernanceError):
            self.mod.validate_policy(mutated, root=ROOT)

    def test_council_proposal_is_explicitly_classified(self) -> None:
        proposal = self.mod.create_council_proposal(
            self.policy,
            council_id="hermes-council",
            rounds=1,
            message_count=4,
            classification="INTERNAL",
            proposal="proposal",
            evidence_parents=["ev_classified"],
        )
        self.assertEqual(proposal["classification"], "INTERNAL")
        self.mod.verify_council_proposal(self.policy, proposal)

    def test_council_proposal_cannot_exceed_council_data_class(self) -> None:
        with self.assertRaises(self.mod.GovernanceError):
            self.mod.create_council_proposal(
                self.policy,
                council_id="hermes-council",
                rounds=1,
                message_count=4,
                classification="LEGAL_PRIVILEGED",
                proposal="privileged proposal",
                evidence_parents=["ev_privileged_proposal"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
