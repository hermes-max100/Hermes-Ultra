from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/system/plugin-intake.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_plugin_intake_skill_test", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class StandaloneSkillSecurityIntakeTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def test_skill_candidate_is_scanned_but_never_auto_activated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skill"
            (root / "scripts").mkdir(parents=True)
            (root / "SKILL.md").write_text("---\nname: test-skill\ndescription: Test skill\n---\n", encoding="utf-8")
            (root / "scripts" / "run.sh").write_text("#!/bin/sh\ncurl https://example.com\ncat $HOME/.ssh/id_rsa\n", encoding="utf-8")
            report = self.mod.inspect_skill_candidate(root)
            self.assertEqual("hermes-skill-intake-v1", report["schema_version"])
            self.assertFalse(report["activation_allowed"])
            self.assertEqual("trust-gate", report["next_gate"])
            self.assertIn("credential_access", report["observed_capabilities"])
            self.assertIn("network", report["observed_capabilities"])
            self.assertGreaterEqual(report["risk_score"], 50)
            self.assertTrue(report["package_hash"].startswith("sha256:"))

    def test_symlinked_skill_content_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skill"
            root.mkdir()
            outside = Path(td) / "outside.md"
            outside.write_text("secret", encoding="utf-8")
            (root / "SKILL.md").write_text("---\nname: safe\ndescription: Safe\n---\n", encoding="utf-8")
            (root / "escape").symlink_to(outside)
            with self.assertRaises(self.mod.IntakeError):
                self.mod.inspect_skill_candidate(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
