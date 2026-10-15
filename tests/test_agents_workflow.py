import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from agents import (
    build_supply_chain_graph,
    create_initial_state,
    evaluate_supplier_risk,
)
from calculations import calculate_inventory_metrics
from main import run_scenario
from supply_data import (
    CRITICAL_SHORTAGE,
    NORMAL_SUPPLY,
    SUPPLIER_DELAY,
    get_scenario_part,
)


EXPECTED_NODE_ORDER = [
    "Inventory Monitor",
    "Supplier Risk",
    "Replenishment Decision",
    "Management Report",
]


class AutoSupplyWorkflowTests(unittest.TestCase):
    def _run_part(self, part, scenario="Custom", use_llm_report=False):
        state = create_initial_state(scenario, part, use_llm_report)
        return build_supply_chain_graph().invoke(state)

    def test_four_nodes_execute_in_fixed_order(self):
        result = run_scenario(NORMAL_SUPPLY)

        self.assertEqual(
            [entry["node_name"] for entry in result["execution_trace"]],
            EXPECTED_NODE_ORDER,
        )
        self.assertEqual(
            [entry["execution_status"] for entry in result["execution_trace"]],
            ["SUCCESS", "SUCCESS", "SUCCESS", "SUCCESS"],
        )

    def test_shared_state_carries_inputs_metrics_risk_decision_and_report(self):
        result = run_scenario(SUPPLIER_DELAY)

        self.assertEqual(result["selected_part"]["part_code"], "SEN-001")
        self.assertEqual(result["input_params"]["lead_time_days"], 14)
        self.assertEqual(result["inventory_metrics"]["stockout_gap"], 4.0)
        self.assertEqual(result["supplier_risk"]["risk_level"], "HIGH")
        self.assertEqual(
            result["replenishment_decision"]["recommended_order_qty"],
            result["inventory_metrics"]["recommended_order_qty"],
        )
        self.assertTrue(result["management_report"])

    def test_three_scenarios_produce_distinct_business_decisions(self):
        normal = run_scenario(NORMAL_SUPPLY)
        delayed = run_scenario(SUPPLIER_DELAY)
        critical = run_scenario(CRITICAL_SHORTAGE)

        self.assertEqual(
            (
                normal["supplier_risk"]["risk_level"],
                normal["replenishment_decision"]["recommended_action"],
                normal["replenishment_decision"]["recommended_order_qty"],
            ),
            ("LOW", "No Action", 0),
        )
        self.assertEqual(
            (
                delayed["supplier_risk"]["risk_level"],
                delayed["replenishment_decision"]["recommended_action"],
                delayed["replenishment_decision"]["recommended_order_qty"],
            ),
            ("HIGH", "Emergency Reorder", 560),
        )
        self.assertEqual(
            (
                critical["supplier_risk"]["risk_level"],
                critical["replenishment_decision"]["recommended_action"],
                critical["replenishment_decision"]["recommended_order_qty"],
            ),
            ("HIGH", "Emergency Reorder", 220),
        )
        self.assertIn(
            "Expedite Delivery",
            delayed["replenishment_decision"]["supporting_actions"],
        )
        self.assertIn(
            "Evaluate Backup Supplier",
            critical["replenishment_decision"]["supporting_actions"],
        )
        self.assertNotIn(
            "Activate Backup Supplier",
            critical["replenishment_decision"]["supporting_actions"],
        )

    def test_medium_risk_when_below_reorder_point_without_gap(self):
        part = deepcopy(get_scenario_part(NORMAL_SUPPLY))
        part["current_stock"] = 750
        metrics = calculate_inventory_metrics(
            part["current_stock"],
            part["daily_usage"],
            part["lead_time_days"],
            part["safety_days"],
        )

        risk = evaluate_supplier_risk(part, metrics)

        self.assertEqual(metrics["stockout_gap"], 0.0)
        self.assertLess(part["current_stock"], metrics["reorder_point"])
        self.assertEqual(risk["risk_level"], "MEDIUM")

    def test_high_criticality_can_raise_delayed_supplier_risk(self):
        part = deepcopy(get_scenario_part(NORMAL_SUPPLY, "CTL-003"))
        part["supplier_status"] = "DELAYED"
        metrics = calculate_inventory_metrics(
            part["current_stock"],
            part["daily_usage"],
            part["lead_time_days"],
            part["safety_days"],
        )

        risk = evaluate_supplier_risk(part, metrics)

        self.assertEqual(metrics["stockout_gap"], 0.0)
        self.assertEqual(risk["risk_level"], "HIGH")

    def test_inventory_or_lead_time_changes_workflow_result(self):
        baseline_part = get_scenario_part(NORMAL_SUPPLY)
        changed_part = deepcopy(baseline_part)
        changed_part["lead_time_days"] = 12

        baseline = self._run_part(baseline_part)
        changed = self._run_part(changed_part)

        self.assertEqual(baseline["supplier_risk"]["risk_level"], "LOW")
        self.assertEqual(changed["supplier_risk"]["risk_level"], "HIGH")
        self.assertEqual(changed["inventory_metrics"]["stockout_gap"], 2.0)
        self.assertEqual(
            changed["replenishment_decision"]["recommended_order_qty"], 400
        )

    def test_template_report_is_default_and_contains_required_facts(self):
        result = run_scenario(CRITICAL_SHORTAGE)
        report = result["management_report"]

        self.assertEqual(result["report_source"], "template")
        self.assertIn("库存 40 件", report)
        self.assertIn("供应商交期 10 天", report)
        self.assertIn("潜在库存覆盖缺口为 8 天", report)
        self.assertIn("高风险（HIGH）", report)
        self.assertIn("建议订货量为 220 件", report)
        self.assertIn("业务假设", report)
        self.assertIn("不等同于已经发生的停产天数", report)

    def test_llm_failure_falls_back_to_template_report(self):
        part = get_scenario_part(NORMAL_SUPPLY)
        with patch(
            "agents._generate_llm_report",
            side_effect=ConnectionError("simulated Ollama outage"),
        ):
            result = self._run_part(part, use_llm_report=True)

        self.assertEqual(result["report_source"], "template_fallback")
        self.assertIn("simulated Ollama outage", result["llm_error"])
        self.assertIn("管理层分析报告", result["management_report"])
        self.assertEqual(
            result["execution_trace"][-1]["execution_status"], "SUCCESS"
        )

    def test_valid_llm_commentary_is_appended_after_verified_template(self):
        class FakeLlm:
            def invoke(self, _prompt):
                return (
                    "当前为低风险（LOW），建议执行无需行动（No Action），"
                    "同时保持常规供应商监测。"
                )

        part = get_scenario_part(NORMAL_SUPPLY)
        with patch("agents._create_ollama_llm", return_value=FakeLlm()):
            result = self._run_part(part, use_llm_report=True)

        self.assertEqual(result["report_source"], "llm")
        self.assertIn("潜在库存覆盖缺口为 0 天", result["management_report"])
        self.assertIn("LLM 管理层补充", result["management_report"])
        self.assertEqual(result["llm_error"], "")

    def test_llm_prompt_requests_chinese_and_rejects_metric_restatement(self):
        captured_prompt = ""

        class MetricRestatingLlm:
            def invoke(self, prompt):
                nonlocal captured_prompt
                captured_prompt = prompt
                return "低风险（LOW），无需行动（No Action），库存表现稳定。"

        part = get_scenario_part(NORMAL_SUPPLY)
        with patch("agents._create_ollama_llm", return_value=MetricRestatingLlm()):
            result = self._run_part(part, use_llm_report=True)

        self.assertIn("用简体中文", captured_prompt)
        self.assertEqual(result["report_source"], "template_fallback")
        self.assertIn("verified metric", result["llm_error"])

    def test_failed_node_trace_is_based_on_actual_execution(self):
        part = deepcopy(get_scenario_part(NORMAL_SUPPLY))
        part["current_stock"] = -1

        result = self._run_part(part)

        self.assertEqual(
            [entry["execution_status"] for entry in result["execution_trace"]],
            ["FAILED", "SKIPPED", "SKIPPED", "SKIPPED"],
        )
        self.assertIn("non-negative", result["workflow_error"])


if __name__ == "__main__":
    unittest.main()
