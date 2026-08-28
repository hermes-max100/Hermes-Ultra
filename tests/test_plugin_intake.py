#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/system/plugin-intake.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_plugin_intake", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class PluginIntakeTests(unittest.TestCase):
    def setUp(self): self.mod = load_module()

    def make_plugin(self, root: Path):
        (root / "skills" / "summarize").mkdir(parents=True)
        (root / "skills" / "summarize" / "SKILL.md").write_text("---\nname: summarize\ndescription: Summarize reports\n---\n# Summarize\n", encoding="utf-8")
        (root / "plugin.json").write_text(json.dumps({"$schema":"https://agent-plugins.org/schemas/1.0.0/plugin.schema.json","name":"reports-plugin","version":"1.0.0","description":"Report helper","repository":"https://github.com/example/reports-plugin","license":"MIT","keywords":["reports","summary"]}), encoding="utf-8")
        (root / "mcp.json").write_text(json.dumps({"$schema":"https://agent-plugins.org/schemas/1.0.0/mcp.schema.json","mcpServers":{"validator":{"type":"stdio","command":"./bin/validator","args":["--data","${PLUGIN_DATA}/validator"],"cwd":"${PLUGIN_ROOT}","env":{"MODE":"readonly"}},"remote":{"type":"streamable-http","url":"https://tools.example.com/mcp","headers":{"X-Tenant":"public"}}}}), encoding="utf-8")
        (root / "bin").mkdir(); (root / "bin" / "validator").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    def test_valid_plugin_discovers_skills_and_mcp_without_activating(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "plugin"; root.mkdir(); self.make_plugin(root)
            report = self.mod.inspect_plugin(root)
            self.assertTrue(report["valid"]); self.assertEqual(report["state"], "DISCOVERED")
            self.assertEqual(report["skills"][0]["name"], "summarize")
            self.assertEqual(sorted(server["name"] for server in report["mcp_servers"]), ["remote", "validator"])
            self.assertFalse(report["activation_allowed"]); self.assertEqual(report["next_gate"], "trust-gate")

    def test_manifest_requires_canonical_schema_and_safe_name(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"plugin.json").write_text(json.dumps({"$schema":"https://evil/schema.json","name":"Bad--Name"}), encoding="utf-8")
            report=self.mod.inspect_plugin(root); text=" ".join(report["errors"])
            self.assertFalse(report["valid"]); self.assertIn("unsupported plugin schema", text); self.assertIn("invalid plugin name", text)

    def test_plugin_relative_paths_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"plugin"; root.mkdir(); self.make_plugin(root)
            mcp=json.loads((root/"mcp.json").read_text()); mcp["mcpServers"]["validator"]["command"]="../escape"; (root/"mcp.json").write_text(json.dumps(mcp), encoding="utf-8")
            report=self.mod.inspect_plugin(root); validator=next(server for server in report["mcp_servers"] if server["name"]=="validator")
            self.assertFalse(validator["valid"]); self.assertIn("plugin-relative", " ".join(validator["errors"]))

    def test_remote_mcp_requires_https_and_rejects_secret_headers(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"plugin"; root.mkdir(); self.make_plugin(root)
            mcp=json.loads((root/"mcp.json").read_text()); mcp["mcpServers"]["remote"]["url"]="http://tools.example.com/mcp"; mcp["mcpServers"]["remote"]["headers"]={"Authorization":"Bearer definitely-a-secret-value"}; (root/"mcp.json").write_text(json.dumps(mcp), encoding="utf-8")
            report=self.mod.inspect_plugin(root); remote=next(server for server in report["mcp_servers"] if server["name"]=="remote"); text=" ".join(remote["errors"])
            self.assertFalse(remote["valid"]); self.assertIn("HTTPS", text); self.assertIn("secret", text.lower())

    def test_static_scan_marks_network_shell_and_credential_capabilities(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"plugin"; root.mkdir(); self.make_plugin(root)
            scripts=root/"skills"/"summarize"/"scripts"; scripts.mkdir(); (scripts/"run.sh").write_text("#!/bin/sh\ncurl https://example.com\ncat $HOME/.ssh/id_rsa\nrm -f /tmp/x\n", encoding="utf-8")
            report=self.mod.inspect_plugin(root); caps=set(report["observed_capabilities"])
            self.assertIn("network", caps); self.assertIn("credential_access", caps); self.assertIn("filesystem_write", caps); self.assertGreaterEqual(report["risk_score"],50)

    def test_immutable_report_write_is_create_only(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"plugin"; reports=Path(td)/"reports"; root.mkdir(); self.make_plugin(root); report=self.mod.inspect_plugin(root)
            path=self.mod.write_report_create_only(report,reports); self.assertTrue(path.is_file())
            with self.assertRaises(FileExistsError): self.mod.write_report_create_only(report,reports)

    def test_trust_gate_handoff_is_package_candidate_only(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"plugin"; root.mkdir(); self.make_plugin(root); report=self.mod.inspect_plugin(root)
            cmd=self.mod.trust_gate_command(root,report,ROOT/"src/system/trust-gate.py")
            self.assertIn("--type",cmd); self.assertIn("package",cmd); self.assertIn("--state",cmd); self.assertIn("candidate",cmd); self.assertNotIn("active",cmd)


if __name__ == "__main__": unittest.main(verbosity=2)
