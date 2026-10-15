"""Business verification for the isolated UI proposal (no production changes)."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "docs/prototypes/build_planning_preview.py"
spec = importlib.util.spec_from_file_location("planning_preview", SCRIPT)
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class PlanningPreviewTests(unittest.TestCase):
    def test_anchor_preserves_14_and_30_day_business_cases(self):
        expected = {("平稳排产", 14): (0, 180, None),
                    ("供应商延期", 14): (80, 260, "2026-10-24"),
                    ("排产高峰", 14): (140, 0, "2026-10-26"),
                    ("订单待确认", 14): (320, 0, "2026-10-24"),
                    ("平稳排产", 30): (1100, 0, "2026-10-30"),
                    ("供应商延期", 30): (1100, 0, "2026-10-24")}
        for (scene, horizon), values in expected.items():
            with self.subTest(scene=scene, horizon=horizon):
                p = preview.build_source(scene, anchor=True)["products"][0]
                result = preview.project(p, horizon)
                self.assertEqual((result["total_unmet_demand"], result["final_available"],
                                  result["first_shortage_date"]), values)

    def test_all_scenarios_use_same_initial_stock_and_demand_except_demand_variants(self):
        base = preview.build_source("平稳排产")["products"]
        for scene in preview.SCENARIOS:
            rows = preview.build_source(scene)["products"]
            self.assertEqual(len(rows), 12)
            for initial, changed in zip(base, rows):
                self.assertEqual(initial["stock"], changed["stock"])
                self.assertEqual([o["qty"] for o in initial["orders"]], [o["qty"] for o in changed["orders"]])
                if scene not in ("排产高峰", "周末检修"):
                    self.assertEqual(initial["demand"], changed["demand"])

    def test_each_daily_projection_conserves_stock_and_demand(self):
        for scene in preview.SCENARIOS:
            for product in preview.build_source(scene)["products"]:
                result = preview.project(product)
                for day in result["daily"]:
                    self.assertEqual(day["opening_available"] + day["confirmed_receipts"],
                                     day["satisfied_demand"] + day["closing_available"])
                    self.assertEqual(day["planned_demand"], day["satisfied_demand"] + day["unmet_demand"])
                    self.assertGreaterEqual(day["closing_available"], 0)

    def test_variation_is_explained_by_demands_and_receipts(self):
        for product in preview.build_source("平稳排产")["products"]:
            daily = preview.project(product)["daily"]
            self.assertGreater(len(set(product["demand"])), 5)
            self.assertTrue(any(d["confirmed_receipts"] for d in daily))
            self.assertTrue(any(b["closing_available"] > a["closing_available"] for a, b in zip(daily, daily[1:])))
            self.assertTrue(any(b["closing_available"] < a["closing_available"] for a, b in zip(daily, daily[1:])))

    def test_order_date_changes_real_result_and_pending_is_excluded(self):
        product = preview.build_source("供应商延期", anchor=True)["products"][0]
        original = preview.project(product, 14)
        product["orders"][0]["day"] = 8
        changed = preview.project(product, 14)
        self.assertEqual(original["total_unmet_demand"], 80)
        self.assertEqual(changed["total_unmet_demand"], 0)
        product["orders"][0]["status"] = "待确认"
        pending = preview.project(product, 14)
        self.assertEqual(pending["total_unmet_demand"], 320)
        self.assertFalse(pending["confirmed_orders"])

    def test_counterfactual_preserves_input_and_restores_original_arrival(self):
        product = preview.build_source("供应商延期", anchor=True)["products"][0]
        normal = preview.project(product, 14, normal=True)
        self.assertEqual(normal["total_unmet_demand"], 0)
        self.assertEqual(product["orders"][0]["day"], 12)

    def test_catalog_is_reproducible_and_contains_only_computed_curves(self):
        a, b = preview.build_catalog(), preview.build_catalog()
        self.assertEqual(a, b)
        for pack in a["packs"].values():
            for source in pack.values():
                for p in source["products"]:
                    expected = [[d["closing_available"], d["unmet_demand"]] for d in preview.project(p)["daily"]]
                    self.assertEqual(expected, p["verified"])


if __name__ == "__main__":
    unittest.main()
