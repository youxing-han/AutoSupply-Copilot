import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
from agents import build_supply_chain_graph, create_initial_state
from assistant import build_assistant_context, answer_supply_chain_question, AssistantUnavailableError
from inventory_planning import simulate_inventory
from mitigation import compare_mitigations, money_cents, build_mitigation_demo
from planning_data import analyze_planning_bundle, build_planning_demo
from report_pdf import build_pdf_report


def fixture():
    result = analyze_planning_bundle(build_planning_demo(horizon_days=5, scenario="无采购订单"))["details"]["SEN-001"]
    p, plan = copy.deepcopy(result["selected_part"]), copy.deepcopy(result["planning_input"])
    p["current_stock"] = 0
    for row in plan["demands"]:
        row["quantity"] = 20
    return p, plan


def candidate(cid="A", qty=100, available="2026-10-12", unit=5, fee=0, kind="BACKUP", **overrides):
    return {"candidate_id": cid, "part_code": "SEN-001", "kind": kind, "source": "Fictional Supply",
            "quantity": qty, "earliest_available_date": available, "unit_cost": unit, "extra_cost": fee,
            "qualified": True, "business_allowed": True, "minimum_quantity": 1, "pack_multiple": 1,
            "capacity": 1000, "source_pool": "", "pool_capacity": 0, "linked_po_id": "", **overrides}


class MitigationTests(unittest.TestCase):
    def compare(self, candidates):
        return compare_mitigations(*fixture(), candidates)

    def test_scenario1_cheapest_late_does_not_solve_gap(self):
        r = self.compare([candidate("LATE", available="2026-10-14", unit=0.1), candidate("EARLY", unit=5)])
        late = next(s for s in r["scenarios"] if s["scenario_id"] == "LATE")
        self.assertEqual((late["incremental_cost"], late["residual_unmet"], late["residual_shortage_dates"]), (10, 40, ["2026-10-12", "2026-10-13"]))
        self.assertFalse(late["fully_feasible"])
        self.assertFalse(late["arrives_by_first_shortage"])
        self.assertEqual(r["recommended"]["scenario_id"], "EARLY")

    def test_scenario2_expensive_expedite_changes_po_date_without_duplicate(self):
        p, plan = fixture()
        plan["orders"] = [{"po_id": "SIM-COMMITTED", "part_code": p["part_code"], "supplier": p["supplier"],
                           "open_quantity": 100, "arrival_date": "2026-10-16", "status": "CONFIRMED"}]
        expedite = candidate("EXP", kind="EXPEDITE", unit=0, fee=600,
                             source=p["supplier"], linked_po_id="SIM-COMMITTED")
        r = compare_mitigations(p, plan, [expedite])
        best = r["recommended"]
        self.assertEqual((best["residual_unmet"], best["incremental_cost"]), (0, 600))
        self.assertEqual(sum(d["confirmed_receipts"] for d in best["projection"]["daily"]), 100)
        self.assertEqual(best["projection"]["final_available"], 0)
        self.assertEqual(plan["orders"][0]["arrival_date"], "2026-10-16")

    def test_scenario3_two_insufficient_lots_combine(self):
        r = self.compare([candidate("BACKUP", qty=50, unit=4, fee=20),
                          candidate("TRANSFER", qty=50, unit=1, fee=10, kind="TRANSFER")])
        self.assertEqual(r["recommended"]["candidate_ids"], ["BACKUP", "TRANSFER"])
        self.assertEqual(r["recommended"]["residual_unmet"], 0)
        self.assertEqual(r["recommended"]["incremental_cost"], 280)
        singles = [s for s in r["scenarios"] if len(s["candidate_ids"]) == 1]
        self.assertTrue(all(s["residual_unmet"] == 50 for s in singles))

    def test_scenario4_unqualified_supplier_is_never_recommended(self):
        r = self.compare([candidate("BAD", unit=0, qualified=False), candidate("GOOD", unit=5)])
        bad = next(s for s in r["scenarios"] if s["scenario_id"] == "BAD")
        self.assertFalse(bad["constraints_satisfied"])
        self.assertEqual(bad["reduction_unmet"], 0)
        self.assertEqual(r["recommended"]["scenario_id"], "GOOD")
        self.assertTrue(all("BAD" not in s["candidate_ids"] for s in r["scenarios"] if s["constraints_satisfied"]))

    def test_scenario5_no_fully_feasible_plan_reports_residual(self):
        r = self.compare([candidate("LATE", available="2026-10-14", unit=0.1), candidate("PARTIAL", qty=10, unit=1)])
        self.assertFalse(r["has_fully_feasible"])
        self.assertEqual(r["recommended"]["residual_unmet"], 30)
        self.assertEqual(r["recommended"]["first_residual_shortage"], "2026-10-12")
        self.assertIn("无完全可行方案", r["recommendation_reason"])
        self.assertIn("人工", r["recommendation_reason"])

    def test_scenario6_hand_cost_and_independent_inventory_check(self):
        p, plan = fixture()
        rows = [candidate("BUY", qty=60, unit=2.5, fee=15), candidate("MOVE", qty=40, unit=0.5, fee=10, kind="TRANSFER")]
        result = compare_mitigations(p, plan, rows)
        # Hand cost: 60*2.50+15 + 40*0.50+10 = 195 yuan.
        self.assertEqual(result["recommended"]["incremental_cost_cents"], 19500)
        orders = [{"po_id": "INDEPENDENT", "part_code": p["part_code"], "supplier": "Fictional Supply",
                   "open_quantity": 100, "arrival_date": "2026-10-12", "status": "CONFIRMED"}]
        independent = simulate_inventory(p,plan["demands"],orders,plan["start_date"],5)
        self.assertEqual(result["recommended"]["projection"]["final_available"], independent["final_available"])
        self.assertEqual(result["recommended"]["residual_unmet"], independent["total_unmet_demand"])

    def test_constraints_moq_pack_capacity_and_business(self):
        for overrides in [{"minimum_quantity": 101}, {"pack_multiple": 30}, {"capacity": 99}, {"business_allowed": False}]:
            with self.subTest(overrides=overrides):
                r = self.compare([candidate(**overrides)])
                self.assertFalse(r["has_fully_feasible"])
                self.assertFalse(r["scenarios"][1]["constraints_satisfied"])
                self.assertEqual(r["recommended"]["scenario_id"], "BASELINE")

    def test_shared_stock_pool_prevents_double_use(self):
        r = self.compare([candidate("T1", qty=50, unit=1, kind="TRANSFER", source_pool="POOL", pool_capacity=60),
                          candidate("T2", qty=50, unit=1, kind="TRANSFER", source_pool="POOL", pool_capacity=60)])
        combo = next(s for s in r["scenarios"] if len(s["candidate_ids"]) == 2)
        self.assertFalse(combo["constraints_satisfied"])
        self.assertEqual(r["recommended"]["residual_unmet"], 50)
        self.assertFalse(r["has_fully_feasible"])

    def test_duplicate_expedite_same_po_combination_rejected(self):
        p, plan = fixture()
        plan["orders"] = [{"po_id": "PO", "part_code": p["part_code"], "supplier": p["supplier"], "open_quantity": 100,
                           "arrival_date": "2026-10-16", "status": "CONFIRMED"}]
        rows = [candidate("E1", kind="EXPEDITE", source=p["supplier"], linked_po_id="PO", unit=0, fee=60),
                candidate("E2", kind="EXPEDITE", source=p["supplier"], linked_po_id="PO", unit=0, fee=90)]
        r = compare_mitigations(p, plan, rows)
        self.assertFalse(next(s for s in r["scenarios"] if len(s["candidate_ids"]) == 2)["constraints_satisfied"])
        self.assertEqual(r["recommended"]["scenario_id"], "E1")

    def test_expedite_missing_po_or_wrong_quantity_is_ineligible(self):
        r = self.compare([candidate("E", kind="EXPEDITE", unit=0, linked_po_id="MISSING")])
        self.assertFalse(r["scenarios"][1]["constraints_satisfied"])

    def test_candidate_after_horizon_does_not_reduce_gap(self):
        r = self.compare([candidate(available="2026-10-30", unit=0)])
        self.assertEqual(r["scenarios"][1]["residual_unmet"], 100)
        self.assertEqual(r["recommended"]["scenario_id"], "BASELINE")

    def test_no_candidates_or_no_shortage_selects_baseline(self):
        r = self.compare([])
        self.assertFalse(r["has_fully_feasible"])
        self.assertEqual(r["recommended"]["scenario_id"], "BASELINE")
        p, plan = fixture()
        p["current_stock"] = 1000
        r = compare_mitigations(p, plan, [candidate(unit=0)])
        self.assertEqual(r["recommended"]["scenario_id"], "BASELINE")
        self.assertTrue(r["has_fully_feasible"])

    def test_money_decimal_is_exact_and_invalid_values_rejected(self):
        self.assertEqual(money_cents(0.1), 10)
        self.assertEqual(money_cents("123.45"), 12345)
        for value in [-1, True, 0.001, float("inf"), "not-a-number"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                money_cents(value)

    def test_bad_candidates_and_bounds_rejected(self):
        for overrides in [{"part_code": "BAD"}, {"quantity": -1}, {"earliest_available_date": "bad"},
                          {"earliest_available_date": "2026-10-11"}, {"qualified": "true"}, {"unit_cost": -1},
                          {"pack_multiple": 0}, {"kind": "BAD"}, {"kind": "TRANSFER", "linked_po_id": "PO"}]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.compare([candidate(**overrides)])
        with self.assertRaises(ValueError):
            self.compare([candidate(), candidate()])
        with self.assertRaises(ValueError):
            self.compare([candidate(str(i)) for i in range(9)])

    def test_all_fixed_lot_subsets_are_evaluated(self):
        r = self.compare([candidate(str(i), qty=25, unit=i+1) for i in range(4)])
        self.assertEqual(len(r["scenarios"]), 16)
        self.assertEqual(r["recommended"]["residual_unmet"], 0)
        self.assertEqual(r["recommended"]["incremental_cost"], 250)


class MitigationIntegrationTests(unittest.TestCase):
    def test_dynamic_llm_cannot_invent_scenario_conclusions(self):
        r = analyze_planning_bundle(build_planning_demo())["details"]["SEN-001"]
        context = build_assistant_context("single", single_result=r)
        for raw in ['SIM-EXPEDITE + SIM-BACKUP 没有解决缺料问题。',
                    '{"explanation_keys":["unverified"]}', '{"explanation_keys":["timing"],"quantity":100}',
                    '{"explanation_keys":[]}', '{"explanation_keys":["cost","cost"]}',
                    '{"explanation_keys":[{}]}']:
            with self.subTest(raw=raw), patch("assistant._create_ollama_llm") as llm:
                llm.return_value.invoke.return_value = raw
                with self.assertRaises(AssistantUnavailableError):
                    answer_supply_chain_question("为什么？", context)
        with patch("assistant._create_ollama_llm") as llm:
            llm.return_value.invoke.return_value = '{"explanation_keys":["timing","cost"]}'
            answer = answer_supply_chain_question("比较方案", context)
        self.assertIn("AI 选择的核验说明", answer)
        self.assertIn("晚于缺料日", answer)
        self.assertIn(context["facts_text"], answer)
    def test_editor_qualification_change_removes_executable_advice(self):
        import hashlib
        import json
        app = AppTest.from_file(ROOT / "app.py", default_timeout=30).run()
        app.get_by_key("analysis_mode").set_value("动态物料计划").run()
        app.get_by_key("planning_data_pack").select("公式核验 · 5种物料").run()
        app.get_by_key("planning_horizon").set_value(14).run()
        app.get_by_key("planning_scenario").select("供应商交付延迟").run()
        app.get_by_key("load_planning_demo").click().run()
        app.get_by_key("run_planning_analysis").click().run()
        app.get_by_key("planning_show_mitigation").check().run()
        r = app.session_state["planning_selected_result"]
        identity = hashlib.sha256(json.dumps({"part": r["selected_part"], "plan": r["planning_input"]},
                                            sort_keys=True, default=str).encode()).hexdigest()[:12]
        app.session_state[f"mitigation_editor_{identity}"] = {
            "edited_rows": {i: {"qualified": False} for i in range(4)}, "added_rows": [], "deleted_rows": []}
        app.run()
        self.assertEqual([e.value for e in app.exception], [])
        self.assertFalse(app.session_state["mitigation_comparison"]["has_fully_feasible"])
        self.assertEqual(app.session_state["mitigation_comparison"]["recommended"]["scenario_id"], "BASELINE")
        self.assertTrue(any("无完全可行方案" in w.value for w in app.warning))

    def test_four_node_report_pdf_and_safe_context_use_comparison(self):
        result = analyze_planning_bundle(build_planning_demo())["details"]["SEN-001"]
        state = create_initial_state("Dynamic Planning", result["selected_part"])
        state["planning_input"] = result["planning_input"]
        state["mitigation_candidates"] = build_mitigation_demo(result)
        r = build_supply_chain_graph().invoke(state)
        self.assertFalse(r["workflow_error"])
        self.assertTrue(r["mitigation_comparison"]["has_fully_feasible"])
        self.assertEqual(r["mitigation_comparison"]["recommended"]["incremental_cost"], 2980)
        self.assertEqual([t["execution_status"] for t in r["execution_trace"]], ["SUCCESS"]*4)
        self.assertIn("mitigation=", r["execution_trace"][2]["output_summary"])
        self.assertIn("供应缓解方案比较", r["management_report"])
        self.assertTrue(build_pdf_report(r).startswith(b"%PDF"))
        context = build_assistant_context("single", single_result=r)
        self.assertEqual(context["payload"]["mitigation"]["scenarios"][0]["residual_unmet"], 80)
        self.assertIn("2980", context["facts_text"])
        self.assertLess(len(context["facts_text"]), 1200)
        self.assertNotIn("SIM-EXPEDITE + SIM-BACKUP + SIM-TRANSFER + SIM-LATE", context["facts_text"])
        self.assertNotIn("projection", context["payload"]["mitigation"]["scenarios"][0])

    def test_invalid_candidate_fails_replenishment_and_skips_report(self):
        result = analyze_planning_bundle(build_planning_demo())["details"]["SEN-001"]
        state = create_initial_state("Dynamic Planning", result["selected_part"])
        state["planning_input"] = result["planning_input"]
        state["mitigation_candidates"] = [candidate(unit=-1)]
        r = build_supply_chain_graph().invoke(state)
        self.assertEqual([t["execution_status"] for t in r["execution_trace"]], ["SUCCESS", "SUCCESS", "FAILED", "SKIPPED"])

    def test_page_scenario_switch_and_comparison_selection(self):
        app = AppTest.from_file(ROOT / "app.py", default_timeout=30).run()
        app.get_by_key("analysis_mode").set_value("动态物料计划").run()
        app.get_by_key("planning_data_pack").select("公式核验 · 5种物料").run()
        app.get_by_key("planning_horizon").set_value(14).run()
        app.get_by_key("planning_scenario").select("供应商交付延迟").run()
        app.get_by_key("load_planning_demo").click().run()
        app.get_by_key("run_planning_analysis").click().run()
        app.get_by_key("planning_show_mitigation").check().run()
        self.assertEqual([e.value for e in app.exception], [])
        comparison = app.session_state["mitigation_comparison"]
        self.assertEqual(comparison["recommended"]["residual_unmet"], 0)
        selection = next(s for s in app.selectbox if s.label == "查看方案库存结果")
        selection.select("SIM-LATE").run()
        context = build_assistant_context("single", single_result=app.session_state["planning_selected_result"])
        self.assertEqual(context["payload"]["selected_mitigation_scenario"]["scenario_id"], "SIM-LATE")
        self.assertIn("当前查看方案 SIM-LATE", context["facts_text"])
        self.assertTrue(any("80" in c.value and "残余缺料日期" in c.value for c in app.caption))
        app.get_by_key("planning_scenario").select("采购订单待确认").run()
        app.get_by_key("load_planning_demo").click().run()
        app.get_by_key("run_planning_analysis").click().run()
        app.get_by_key("planning_show_mitigation").check().run()
        self.assertEqual([e.value for e in app.exception], [])
        self.assertIn("SIM-EXPEDITE", [s["scenario_id"] for s in app.session_state["mitigation_comparison"]["scenarios"]])
        app.get_by_key("planning_scenario").select("正常到货").run()
        app.get_by_key("load_planning_demo").click().run()
        app.get_by_key("run_planning_analysis").click().run()
        app.get_by_key("planning_show_mitigation").check().run()
        app.get_by_key("planning_sku").select("SEN-001").run()
        self.assertEqual(app.session_state["mitigation_comparison"]["recommended"]["scenario_id"], "BASELINE")
        self.assertEqual([e.value for e in app.exception], [])


if __name__ == "__main__":
    unittest.main()
