from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src/system/revenue-ledger.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_revenue_outcomes", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class RevenueOutcomeMetricTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def test_outcome_metrics_measure_booked_appointments_sales_margin_and_attribution(self):
        metrics = {
            "impressions": 1000,
            "clicks": 100,
            "leads": 20,
            "qualified_leads": 10,
            "appointments_booked": 5,
            "proposals_sent": 4,
            "sales_closed": 2,
            "conversions": 2,
            "gross_revenue": 2000.0,
            "attributed_revenue": 1800.0,
            "refunds": 100.0,
            "platform_fees": 100.0,
            "ad_spend": 300.0,
            "inference_cost": 50.0,
            "ai_api_cost": 0.0,
            "tool_cost": 50.0,
            "other_cost": 0.0,
        }
        d = self.mod.derived_metrics(metrics)
        self.assertEqual(500.0, d["total_cost"])
        self.assertEqual(1900.0, d["net_revenue"])
        self.assertEqual(1700.0, d["gross_profit"])
        self.assertEqual(1400.0, d["profit"])
        self.assertAlmostEqual(1700.0 / 1900.0, d["gross_margin"], places=6)
        self.assertEqual(50.0, d["cost_per_qualified_lead"])
        self.assertEqual(100.0, d["cost_per_appointment"])
        self.assertEqual(125.0, d["cost_per_proposal"])
        self.assertEqual(250.0, d["cost_per_sale"])
        self.assertEqual(900.0, d["attributed_revenue_per_sale"])

    def test_legacy_ai_api_cost_is_used_only_when_new_inference_cost_is_zero(self):
        base = {
            "gross_revenue": 100.0, "refunds": 0.0, "platform_fees": 0.0,
            "ad_spend": 0.0, "tool_cost": 0.0, "other_cost": 0.0,
            "qualified_leads": 0, "appointments_booked": 0, "proposals_sent": 0,
            "sales_closed": 0, "leads": 0, "clicks": 0, "conversions": 0,
            "attributed_revenue": 0.0,
        }
        legacy = self.mod.derived_metrics({**base, "inference_cost": 0.0, "ai_api_cost": 10.0})
        current = self.mod.derived_metrics({**base, "inference_cost": 7.0, "ai_api_cost": 10.0})
        self.assertEqual(10.0, legacy["inference_cost_effective"])
        self.assertEqual(7.0, current["inference_cost_effective"])
        self.assertEqual(7.0, current["total_cost"])

    def test_aggregate_preserves_business_outcomes(self):
        rows = [{
            "experiment_id": "exp-1",
            "metrics": {
                "qualified_leads": 3, "appointments_booked": 2, "proposals_sent": 1,
                "sales_closed": 1, "attributed_revenue": 600.0, "gross_revenue": 700.0,
                "platform_fees": 20.0, "ad_spend": 50.0, "inference_cost": 10.0,
                "tool_cost": 5.0, "other_cost": 0.0,
            },
        }]
        groups = self.mod.aggregate_events(rows, "experiment_id")
        self.assertEqual(2, groups[0]["appointments_booked"])
        self.assertEqual(1, groups[0]["sales_closed"])
        self.assertEqual(600.0, groups[0]["attributed_revenue"])
        self.assertGreater(groups[0]["derived"]["profit"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
