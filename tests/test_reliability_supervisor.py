from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/system/reliability-supervisor.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_reliability_supervisor", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ReliabilitySupervisorTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = self.mod.ReliabilitySupervisor(self.root)
        self.t0 = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stalled_run_is_detected_and_rearmed_without_losing_memory(self):
        self.store.register_job(
            "daily-revenue",
            schedule="0 8 * * *",
            max_runtime_seconds=900,
            heartbeat_timeout_seconds=120,
            max_recoveries=2,
            memory_refs=["mem:campaign-1"],
            now=self.t0,
        )
        self.store.start_run("daily-revenue", "run-1", now=self.t0)
        self.store.heartbeat("daily-revenue", "run-1", memory_refs=["mem:lead-42"], now=self.t0 + timedelta(seconds=30))

        stalled = self.store.assess("daily-revenue", now=self.t0 + timedelta(seconds=200))
        self.assertEqual("stalled", stalled["status"])
        self.assertEqual("heartbeat_timeout", stalled["stall_reason"])

        rearmed = self.store.rearm("daily-revenue", now=self.t0 + timedelta(seconds=201))
        self.assertEqual("idle", rearmed["status"])
        self.assertEqual(1, rearmed["recovery_count"])
        self.assertEqual(["mem:campaign-1", "mem:lead-42"], rearmed["memory_refs"])

        reopened = self.mod.ReliabilitySupervisor(self.root).load_job("daily-revenue")
        self.assertEqual(1, reopened["recovery_count"])
        self.assertEqual(["mem:campaign-1", "mem:lead-42"], reopened["memory_refs"])

    def test_recovery_budget_fails_closed(self):
        self.store.register_job(
            "job-1", schedule="1h", max_runtime_seconds=60,
            heartbeat_timeout_seconds=10, max_recoveries=1, now=self.t0,
        )
        self.store.start_run("job-1", "run-1", now=self.t0)
        self.store.assess("job-1", now=self.t0 + timedelta(seconds=11))
        self.store.rearm("job-1", now=self.t0 + timedelta(seconds=12))
        self.store.start_run("job-1", "run-2", now=self.t0 + timedelta(seconds=13))
        self.store.assess("job-1", now=self.t0 + timedelta(seconds=30))
        with self.assertRaises(self.mod.ReliabilityError):
            self.store.rearm("job-1", now=self.t0 + timedelta(seconds=31))

    def test_success_completion_requires_verified_evidence_and_emits_immutable_receipt(self):
        self.store.register_job("job-1", schedule="1h", now=self.t0)
        self.store.start_run("job-1", "run-1", now=self.t0)
        with self.assertRaises(self.mod.ReliabilityError):
            self.store.complete_run(
                "job-1", "run-1", status="success",
                result_hash="sha256:" + "a" * 64, evidence=[], now=self.t0 + timedelta(seconds=5),
            )

        result = self.store.complete_run(
            "job-1", "run-1", status="success",
            result_hash="sha256:" + "a" * 64,
            evidence=["sha256:" + "b" * 64], now=self.t0 + timedelta(seconds=5),
        )
        receipt_path = Path(result["receipt_path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual("success", receipt["status"])
        self.assertTrue(receipt["content_hash"].startswith("sha256:"))
        with self.assertRaises(FileExistsError):
            self.store.complete_run(
                "job-1", "run-1", status="success",
                result_hash="sha256:" + "a" * 64,
                evidence=["sha256:" + "b" * 64], now=self.t0 + timedelta(seconds=6),
            )

    def test_update_receipt_is_content_bound_and_tamper_detected(self):
        path = self.store.record_update_receipt(
            update_id="upd-1",
            component="hermes-runtime",
            before_ref="sha256:" + "1" * 64,
            after_ref="sha256:" + "2" * 64,
            status="verified",
            evidence=["sha256:" + "3" * 64],
            tests={"passed": 37, "failed": 0},
            now=self.t0,
        )
        verified = self.store.verify_receipt(path)
        self.assertEqual("verified", verified["status"])
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["status"] = "failed"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(self.mod.ReliabilityError):
            self.store.verify_receipt(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
