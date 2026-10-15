import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from calculations import calculate_inventory_metrics
from supply_data import (
    CRITICAL_SHORTAGE,
    NORMAL_SUPPLY,
    SCENARIO_NAMES,
    SUPPLIER_DELAY,
    generate_automotive_supply_data,
    generate_supply_chain_data,
    get_chain_summary,
    get_scenario_part,
)


class AutomotiveScenarioTests(unittest.TestCase):
    def _part(self, scenario: str, part_code: str):
        data = generate_automotive_supply_data(scenario)
        return data.loc[data["part_code"] == part_code].iloc[0]

    def _metrics(self, part):
        return calculate_inventory_metrics(
            current_stock=part["current_stock"],
            daily_usage=part["daily_usage"],
            lead_time_days=part["lead_time_days"],
            safety_days=part["safety_days"],
        )

    def test_all_scenarios_contain_required_automotive_fields(self):
        required_fields = {
            "part_code",
            "part_name",
            "supplier",
            "current_stock",
            "daily_usage",
            "lead_time_days",
            "supplier_status",
            "criticality",
            "backup_supplier",
            "destination_line",
            "unit_cost",
        }

        for scenario in SCENARIO_NAMES:
            with self.subTest(scenario=scenario):
                data = generate_automotive_supply_data(scenario)
                self.assertTrue(required_fields.issubset(data.columns))
                self.assertEqual(len(data), 5)
                self.assertEqual(
                    set(data["part_name"]),
                    {
                        "Sensor",
                        "Bearing",
                        "Controller",
                        "Brake Module",
                        "Battery Component",
                    },
                )

    def test_normal_supply_sensor_has_no_coverage_gap(self):
        sensor = self._part(NORMAL_SUPPLY, "SEN-001")
        metrics = self._metrics(sensor)

        self.assertEqual(sensor["supplier_status"], "NORMAL")
        self.assertEqual(metrics["days_of_stock"], 10.0)
        self.assertEqual(metrics["stockout_gap"], 0.0)
        self.assertEqual(metrics["safety_stock"], 240.0)
        self.assertEqual(metrics["reorder_point"], 800.0)
        self.assertEqual(metrics["recommended_order_qty"], 0)

    def test_supplier_delay_changes_lead_time_and_creates_gap(self):
        normal_sensor = self._part(NORMAL_SUPPLY, "SEN-001")
        delayed_sensor = self._part(SUPPLIER_DELAY, "SEN-001")
        metrics = self._metrics(delayed_sensor)

        self.assertEqual(normal_sensor["lead_time_days"], 7)
        self.assertEqual(delayed_sensor["lead_time_days"], 14)
        self.assertEqual(delayed_sensor["supplier_status"], "DELAYED")
        self.assertEqual(metrics["days_of_stock"], 10.0)
        self.assertEqual(metrics["stockout_gap"], 4.0)
        self.assertEqual(metrics["reorder_point"], 1360.0)
        self.assertEqual(metrics["recommended_order_qty"], 560)

    def test_critical_shortage_changes_operational_inputs(self):
        normal_brake = self._part(NORMAL_SUPPLY, "BRK-004")
        shortage_brake = self._part(CRITICAL_SHORTAGE, "BRK-004")
        metrics = self._metrics(shortage_brake)

        self.assertEqual(normal_brake["current_stock"], 400)
        self.assertEqual(shortage_brake["current_stock"], 40)
        self.assertEqual(shortage_brake["supplier_status"], "DISRUPTED")
        self.assertEqual(shortage_brake["backup_supplier"], "SafeBrake Components")
        self.assertTrue(shortage_brake["backup_supplier_available"])
        self.assertEqual(metrics["days_of_stock"], 2.0)
        self.assertEqual(metrics["stockout_gap"], 8.0)
        self.assertEqual(metrics["safety_stock"], 60.0)
        self.assertEqual(metrics["reorder_point"], 260.0)
        self.assertEqual(metrics["recommended_order_qty"], 220)

    def test_unknown_scenario_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_automotive_supply_data("Invented Scenario")

    def test_default_scenario_part_is_ready_for_workflow_state(self):
        normal = get_scenario_part(NORMAL_SUPPLY)
        critical = get_scenario_part(CRITICAL_SHORTAGE)

        self.assertEqual(normal["part_code"], "SEN-001")
        self.assertIsNone(normal["backup_supplier"])
        self.assertEqual(critical["part_code"], "BRK-004")
        self.assertIsInstance(critical["backup_supplier_available"], bool)

    def test_unknown_part_code_is_rejected(self):
        with self.assertRaises(ValueError):
            get_scenario_part(NORMAL_SUPPLY, "UNKNOWN")

    def test_original_food_supply_interface_remains_compatible(self):
        original_data = generate_supply_chain_data(disruption=True)
        summary = get_chain_summary(original_data)

        self.assertEqual(original_data.loc[0, "node"], "Farm_A")
        self.assertEqual(original_data.loc[0, "status"], "DISRUPTED")
        self.assertIn("Farm_A", summary)
        self.assertIn("status=DISRUPTED", summary)


if __name__ == "__main__":
    unittest.main()
