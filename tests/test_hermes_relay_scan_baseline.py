import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-hermes-relay-scan-baseline.py"


def fingerprint(findings):
    ordered = sorted(findings, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    payload = json.dumps(ordered, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


class RelayScanBaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.manifest = self.root / "SOURCE_MANIFEST.sha256"
        self.manifest.write_text("abc  source/plugin/plugin.yaml\n")
        self.commit = "08545ed32db07609c14730a7fc02cdd758f12434"
        self.findings = [{
            "severity": "critical", "pattern_id": "hermes_config_mod",
            "category": "persistence", "file": "relay/config.py", "line": 43,
            "match": "~/.hermes/config.yaml", "description": "fixture",
        }]
        self.scan = self.root / "scan.json"
        self.baseline = self.root / "baseline.json"
        self._write_scan(self.findings)
        self._write_baseline(self.findings)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_scan(self, findings, scanner="plugin-guard-v1", verdict="dangerous"):
        self.scan.write_text(json.dumps({"scanner_version": scanner, "verdict": verdict, "findings": findings}))

    def _write_baseline(self, findings):
        self.baseline.write_text(json.dumps({
            "schema_version": 1,
            "source": "Codename-11/hermes-relay",
            "tag": "server-v1.10.0",
            "source_commit": self.commit,
            "source_manifest_sha256": hashlib.sha256(self.manifest.read_bytes()).hexdigest(),
            "scanner_version": "plugin-guard-v1",
            "raw_verdict": "dangerous",
            "finding_count": len(findings),
            "finding_fingerprint_sha256": fingerprint(findings),
            "finding_severity_counts": {"critical": 1},
            "finding_pattern_counts": {"hermes_config_mod": 1},
            "decision": "allow_exact_reviewed_snapshot",
        }))

    def run_verify(self, commit=None):
        return subprocess.run([
            "python3", str(SCRIPT), "--scan-result", str(self.scan),
            "--baseline", str(self.baseline), "--source-commit", commit or self.commit,
            "--source-manifest", str(self.manifest), "--source", "Codename-11/hermes-relay",
            "--tag", "server-v1.10.0",
        ], text=True, capture_output=True)

    def test_exact_reviewed_baseline_is_accepted(self):
        result = self.run_verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RELAY_SCAN_BASELINE=PASS", result.stdout)

    def test_changed_finding_is_rejected(self):
        changed = [dict(self.findings[0], pattern_id="reverse_shell")]
        self._write_scan(changed)
        self.assertNotEqual(self.run_verify().returncode, 0)

    def test_changed_source_commit_is_rejected(self):
        self.assertNotEqual(self.run_verify("f" * 40).returncode, 0)

    def test_changed_source_manifest_is_rejected(self):
        self.manifest.write_text("changed\n")
        self.assertNotEqual(self.run_verify().returncode, 0)

    def test_scanner_version_change_is_rejected(self):
        self._write_scan(self.findings, scanner="plugin-guard-v2")
        self.assertNotEqual(self.run_verify().returncode, 0)


if __name__ == "__main__":
    unittest.main()
