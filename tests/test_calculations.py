import math
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from calculations import (
    calculate_days_of_stock,
    calculate_inventory_metrics,
    calculate_recommended_order_quantity,
    calculate_reorder_point,
    calculate_safety_stock,
    calculate_stockout_gap,
)


class InventoryCalculationTests(unittest.TestCase):
    def test_individual_formulas_match_expected_values(self):
        days_of_stock = calculate_days_of_stock(350, 50)

        self.assertEqual(days_of_stock, 7.0)
        self.assertEqual(calculate_stockout_gap(days_of_stock, 10), 3.0)
        self.assertEqual(calculate_safety_stock(50, 3), 150.0)
        self.assertEqual(calculate_reorder_point(50, 10, 3), 650.0)
        self.assertEqual(calculate_recommended_order_quantity(350, 50, 13), 300)

    def test_order_quantity_rounds_up_to_whole_units(self):
        self.assertEqual(calculate_recommended_order_quantity(40.2, 10, 7), 30)

    def test_zero_daily_usage_is_handled_without_division_error(self):
        metrics = calculate_inventory_metrics(
            current_stock=100,
            daily_usage=0,
            lead_time_days=14,
            safety_days=3,
        )

        self.assertTrue(math.isinf(metrics["days_of_stock"]))
        self.assertEqual(metrics["stockout_gap"], 0.0)
        self.assertEqual(metrics["safety_stock"], 0.0)
        self.assertEqual(metrics["reorder_point"], 0.0)
        self.assertEqual(metrics["target_stock"], 0.0)
        self.assertEqual(metrics["recommended_order_qty"], 0)

    def test_zero_stock_with_usage_creates_full_lead_time_gap(self):
        metrics = calculate_inventory_metrics(
            current_stock=0,
            daily_usage=25,
            lead_time_days=7,
            safety_days=2,
        )

        self.assertEqual(metrics["days_of_stock"], 0.0)
        self.assertEqual(metrics["stockout_gap"], 7.0)
        self.assertEqual(metrics["recommended_order_qty"], 225)

    def test_custom_target_coverage_controls_order_quantity(self):
        metrics = calculate_inventory_metrics(
            current_stock=100,
            daily_usage=20,
            lead_time_days=5,
            safety_days=2,
            target_coverage_days=12,
        )

        self.assertEqual(metrics["target_stock"], 240.0)
        self.assertEqual(metrics["recommended_order_qty"], 140)

    def test_negative_inputs_are_rejected(self):
        invalid_calls = [
            lambda: calculate_days_of_stock(-1, 10),
            lambda: calculate_days_of_stock(10, -1),
            lambda: calculate_stockout_gap(2, -1),
            lambda: calculate_safety_stock(10, -1),
            lambda: calculate_reorder_point(10, -1, 2),
            lambda: calculate_recommended_order_quantity(-1, 10, 5),
        ]

        for invalid_call in invalid_calls:
            with self.subTest(call=invalid_call):
                with self.assertRaises(ValueError):
                    invalid_call()

    def test_non_numeric_and_non_finite_inputs_are_rejected(self):
        with self.assertRaises(TypeError):
            calculate_days_of_stock("100", 10)
        with self.assertRaises(TypeError):
            calculate_days_of_stock(True, 10)
        with self.assertRaises(ValueError):
            calculate_days_of_stock(math.nan, 10)
        with self.assertRaises(ValueError):
            calculate_days_of_stock(math.inf, 10)


if __name__ == "__main__":
    unittest.main()
