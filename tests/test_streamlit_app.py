import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

import agents
import app as dashboard


EXPECTED_NODE_ORDER = [
    "Inventory Monitor",
    "Supplier Risk",
    "Replenishment Decision",
    "Management Report",
]


class StreamlitDashboardTests(unittest.TestCase):
    def _app(self):
        app = AppTest.from_file(PROJECT_ROOT / "app.py", default_timeout=20)
        return app.run()

    def _assert_no_page_exception(self, app):
        self.assertEqual([item.value for item in app.exception], [])

    def test_initial_page_automatically_runs_normal_template_in_chinese(self):
        app = self._app()

        result = app.session_state["last_result"]
        self.assertEqual(app.get_by_key("scenario_preset").value, "Normal Supply")
        self.assertEqual(app.get_by_key("part_sku").value, "SEN-001")
        self.assertEqual(result["supplier_risk"]["risk_level"], "LOW")
        self.assertEqual(result["report_source"], "template")
        self.assertIn("管理层分析报告", result["management_report"])
        self.assertIn("正常供应（Normal Supply）", result["management_report"])
        self.assertEqual(len(app.metric), 3)
        visible_text = " ".join(item.value for item in app.markdown)
        self.assertEqual(app.metric[0].value,"10 天")
        self.assertIn('risk-low',visible_text)
        self.assertIn("未来库存消耗趋势", visible_text)
        self.assertIsNotNone(app.get_by_key("download_single_pdf"))
        self.assertEqual(len(app.sidebar.selectbox), 0)
        self._assert_no_page_exception(app)

    def test_all_scenario_presets_auto_load_and_auto_analyze(self):
        app = self._app()

        app.get_by_key("scenario_preset").select("Supplier Delay").run()
        app.get_by_key("run_single_analysis").click().run()
        delayed = app.session_state["last_result"]
        self.assertEqual(app.get_by_key("part_sku").value, "SEN-001")
        self.assertEqual(app.get_by_key("lead_time_days").value, 14.0)
        self.assertEqual(delayed["inventory_metrics"]["stockout_gap"], 4.0)
        self.assertEqual(delayed["supplier_risk"]["risk_level"], "HIGH")
        self.assertEqual(
            delayed["replenishment_decision"]["recommended_order_qty"], 560
        )

        app.get_by_key("scenario_preset").select("Critical Shortage").run()
        app.get_by_key("run_single_analysis").click().run()
        critical = app.session_state["last_result"]
        self.assertEqual(app.get_by_key("part_sku").value, "BRK-004")
        self.assertEqual(app.get_by_key("current_inventory").value, 40.0)
        self.assertEqual(critical["inventory_metrics"]["stockout_gap"], 8.0)
        self.assertEqual(critical["supplier_risk"]["risk_level"], "HIGH")
        self.assertEqual(
            critical["replenishment_decision"]["recommended_order_qty"], 220
        )
        self.assertTrue(app.get_by_key("backup_supplier_available").value)
        self._assert_no_page_exception(app)

    def test_part_selection_loads_defaults_and_analyzes_selected_sku(self):
        app = self._app()

        app.get_by_key("part_sku").select("BRG-002").run()
        app.get_by_key("run_single_analysis").click().run()
        result = app.session_state["last_result"]
        self.assertEqual(app.get_by_key("current_inventory").value, 1500.0)
        self.assertEqual(app.get_by_key("daily_usage").value, 100.0)
        self.assertEqual(
            app.get_by_key("supplier").value, "Precision Bearing Works"
        )
        self.assertEqual(result["selected_part"]["part_code"], "BRG-002")
        self.assertEqual(result["supplier_risk"]["risk_level"], "LOW")
        self._assert_no_page_exception(app)

    def test_manual_lead_time_change_automatically_refreshes_one_graph_result(self):
        app = self._app()
        self.assertEqual(
            app.session_state["last_result"]["supplier_risk"]["risk_level"],
            "LOW",
        )

        app.get_by_key("lead_time_days").set_value(12.0).run()
        app.get_by_key("run_single_analysis").click().run()
        changed = app.session_state["last_result"]
        self.assertEqual(changed["selected_part"]["lead_time_days"], 12.0)
        self.assertEqual(changed["inventory_metrics"]["stockout_gap"], 2.0)
        self.assertEqual(changed["supplier_risk"]["risk_level"], "HIGH")
        self.assertEqual(
            changed["replenishment_decision"]["recommended_order_qty"], 400
        )
        self.assertEqual(changed["report_source"], "template")
        self.assertIn("潜在库存覆盖缺口为 2 天", changed["management_report"])
        self._assert_no_page_exception(app)

    def test_inventory_change_automatically_changes_metrics_and_decision(self):
        app = self._app()

        app.get_by_key("current_inventory").set_value(400.0).run()
        app.get_by_key("run_single_analysis").click().run()
        result = app.session_state["last_result"]
        self.assertEqual(result["inventory_metrics"]["days_of_stock"], 5.0)
        self.assertEqual(result["inventory_metrics"]["stockout_gap"], 2.0)
        self.assertEqual(result["supplier_risk"]["risk_level"], "HIGH")
        self.assertEqual(
            result["replenishment_decision"]["recommended_order_qty"], 400
        )
        self._assert_no_page_exception(app)

    def test_kpis_decision_trace_and_report_share_the_same_auto_result(self):
        app = self._app()
        app.get_by_key("scenario_preset").select("Supplier Delay").run()
        app.get_by_key("run_single_analysis").click().run()

        result = app.session_state["last_result"]
        self.assertEqual(
            [entry["node_name"] for entry in result["execution_trace"]],
            EXPECTED_NODE_ORDER,
        )
        self.assertEqual(
            [entry["execution_status"] for entry in result["execution_trace"]],
            ["SUCCESS"] * 4,
        )
        visible_text = " ".join(item.value for item in app.markdown)
        self.assertEqual(app.metric[0].value,"10 天")
        self.assertIn('risk-high',visible_text)
        self.assertIn('4 天潜在供应缺口',visible_text)
        self.assertEqual(app.metric[1].value, "4 天")
        self.assertEqual(
            result["replenishment_decision"]["recommended_order_qty"], 560
        )
        self.assertTrue(any("560 件" in item.value for item in app.markdown))
        self.assertIn("库存监控", visible_text)
        self.assertIn("管理报告", visible_text)
        self._assert_no_page_exception(app)

    def test_zero_daily_usage_has_explainable_display_without_infinity(self):
        app = self._app()
        app.get_by_key("daily_usage").set_value(0.0).run()
        app.get_by_key("run_single_analysis").click().run()

        result = app.session_state["last_result"]
        self.assertTrue(math.isinf(result["inventory_metrics"]["days_of_stock"]))
        self.assertIn("日均需求为零", result["management_report"])
        visible_text = " ".join(
            str(item.value) for item in [*app.markdown, *app.caption, *app.info]
        )
        self.assertIn("无消耗", visible_text)
        self.assertNotIn("Infinity", visible_text)
        self._assert_no_page_exception(app)

    def test_empty_supplier_shows_chinese_error_without_running_workflow(self):
        app = self._app()
        app.get_by_key("supplier").set_value(" ").run()
        app.get_by_key("run_single_analysis").click().run()

        self.assertIsNotNone(app.session_state["last_result"])  # invalid draft keeps the successful snapshot
        self.assertTrue(
            any("供应商名称不能为空" in item.value for item in app.error)
        )
        self._assert_no_page_exception(app)

    def test_batch_mode_provides_visible_reference_data_and_explicit_run(self):
        app = self._app()

        app.get_by_key("analysis_mode").set_value(
            "Excel / CSV 批量风险分析"
        ).run()

        self.assertEqual(
            app.get_by_key("analysis_mode").value,
            "Excel / CSV 批量风险分析",
        )
        self.assertFalse(app.get_by_key("start_batch_analysis").disabled)
        self.assertEqual(len(app.session_state['batch_draft_rows']),12)
        self.assertTrue(any('batch_input_preview' in item.value for item in app.markdown))
        self.assertTrue(
            any("等待输入并运行分析" in item.value and "运行批量分析" in item.value for item in app.info)
        )
        with self.assertRaises(KeyError):
            app.get_by_key("open_ai_assistant")
        self._assert_no_page_exception(app)

    def test_mode_switch_round_trip_persists_and_never_calls_ollama(self):
        with patch.object(
            agents,
            "_create_ollama_llm",
            side_effect=AssertionError("mode switching must not call Ollama"),
        ):
            app = self._app()
            toolbar_css = " ".join(
                item.value for item in app.markdown if "stToolbar" in item.value
            )
            self.assertIn("pointer-events:none;", toolbar_css)
            self.assertIn(
                '[data-testid="stToolbar"] {pointer-events:none;}',
                toolbar_css,
            )
            self.assertIn(
                '[data-testid="stHeader"] button {pointer-events:auto;}',
                toolbar_css,
            )

            for _ in range(2):
                app.get_by_key("analysis_mode").set_value(
                    dashboard.BATCH_ANALYSIS_MODE
                ).run()
                self.assertEqual(
                    app.session_state["analysis_mode"],
                    dashboard.BATCH_ANALYSIS_MODE,
                )
                self.assertIsNotNone(app.get_by_key("batch_source"))
                with self.assertRaises(KeyError):
                    app.get_by_key("scenario_preset")

                # A normal rerun (the closest AppTest analogue to refresh)
                # must preserve the current mode.
                app.run()
                self.assertEqual(
                    app.get_by_key("analysis_mode").value,
                    dashboard.BATCH_ANALYSIS_MODE,
                )

                app.get_by_key("analysis_mode").set_value(
                    dashboard.SINGLE_ANALYSIS_MODE
                ).run()
                self.assertEqual(
                    app.session_state["analysis_mode"],
                    dashboard.SINGLE_ANALYSIS_MODE,
                )
                self.assertIsNotNone(app.get_by_key("scenario_preset"))
                self.assertEqual(
                    app.session_state["last_result"]["report_source"],
                    "template",
                )

        self._assert_no_page_exception(app)

    def test_batch_demo_runs_real_workflow_and_renders_priority_chart(self):
        app = self._app()
        app.get_by_key("analysis_mode").set_value(
            "Excel / CSV 批量风险分析"
        ).run()

        app.get_by_key("load_batch_demo").click().run()
        self.assertFalse(app.get_by_key("start_batch_analysis").disabled)
        app.get_by_key("start_batch_analysis").click().run()

        batch_result = app.session_state["batch_result"]
        self.assertEqual(batch_result["total_count"], 12)
        self.assertEqual(batch_result["success_count"], 12)
        self.assertEqual(batch_result["failure_count"], 0)
        self.assertGreaterEqual(
            int((batch_result["summary"]["risk_level"] == "HIGH").sum()), 2
        )
        self.assertIsNotNone(app.get_by_key("batch_priority_chart"))
        self.assertIsNotNone(app.get_by_key('batch_open_SEN-001'))
        app.get_by_key('batch_overview_view').select('表格').run()
        self.assertTrue(any('data-table="batch_risk_table"' in item.value for item in app.markdown))
        self.assertIsNotNone(app.get_by_key("batch_ai_input"))
        self.assertIsNotNone(app.get_by_key("download_batch_pdf"))
        self._assert_no_page_exception(app)

    def test_batch_table_is_compact_and_formats_business_values(self):
        app = self._app()
        app.get_by_key("analysis_mode").set_value(
            dashboard.BATCH_ANALYSIS_MODE
        ).run()
        app.get_by_key("load_batch_demo").click().run()
        app.get_by_key("start_batch_analysis").click().run()

        summary = app.session_state["batch_result"]["summary"]
        display = dashboard._prepare_batch_display_frame(summary)

        self.assertEqual(
            list(display.columns),
            ["SKU", "零部件", "库存覆盖", "潜在缺口", "风险等级", "建议订货量"],
        )
        self.assertEqual(len(display), 12)
        self.assertTrue(all(str(value).endswith("天") for value in display["库存覆盖"]))
        self.assertFalse(any(".000000" in str(value) for value in display.to_numpy().flat))
        self.assertEqual(dashboard._batch_table_height(5), 243)
        self.assertEqual(dashboard._batch_table_height(50), 348)
        self._assert_no_page_exception(app)

    def test_batch_selected_sku_change_resets_assistant_context(self):
        with patch.object(
            dashboard,
            "answer_supply_chain_question",
            side_effect=AssertionError("selection must not call Ollama"),
        ):
            app = self._app()
            app.get_by_key("analysis_mode").set_value(
                dashboard.BATCH_ANALYSIS_MODE
            ).run()
            app.get_by_key("load_batch_demo").click().run()
            app.get_by_key("start_batch_analysis").click().run()

            initial_context_id = app.session_state["chat_context_id"]
            initial_code = app.get_by_key("batch_selected_sku").value
            alternatives = [
                code
                for code in app.session_state["batch_result"]["details"]
                if code != initial_code
            ]
            app.session_state["chat_messages"] = [
                {"role": "user", "content": "旧 SKU 上下文"}
            ]
            app.get_by_key("batch_selected_sku").select(alternatives[0]).run()

        self.assertNotEqual(app.session_state["chat_context_id"], initial_context_id)
        self.assertEqual(app.session_state["chat_messages"], [])
        self._assert_no_page_exception(app)

    def test_enterprise_palette_maps_all_risk_levels(self):
        self.assertEqual(dashboard._risk_color("LOW"), "#23836B")
        self.assertEqual(dashboard._risk_color("MEDIUM"), "#C88B35")
        self.assertEqual(dashboard._risk_color("HIGH"), "#C94A4A")
        self.assertEqual(dashboard._risk_color("UNKNOWN"), "#788482")

    def test_visual_conclusion_and_trend_use_the_workflow_result(self):
        app = self._app()
        app.get_by_key("scenario_preset").select("Supplier Delay").run()
        app.get_by_key("run_single_analysis").click().run()
        result = app.session_state["last_result"]

        headline, detail = dashboard._risk_conclusion(result)
        trend = dashboard._stock_trend_figure(result)

        self.assertEqual(headline, "库存只能支撑 10 天，交付却需要 14 天。")
        self.assertIn("4 天潜在供应缺口", detail)
        self.assertEqual(len(trend.data), 3)
        self.assertEqual(trend.data[0].name, "预计库存")
        self.assertEqual(len(trend.layout.shapes), 2)
        self.assertTrue(any("潜在覆盖缺口" in item.text for item in trend.layout.annotations))

    def test_critical_shortage_conclusion_is_specific_and_dynamic(self):
        app = self._app()
        app.get_by_key("scenario_preset").select("Critical Shortage").run()
        app.get_by_key("run_single_analysis").click().run()
        result = app.session_state["last_result"]

        headline, detail = dashboard._risk_conclusion(result)

        self.assertEqual(headline, "关键零部件存在 8 天潜在供应覆盖缺口。")
        self.assertIn("库存覆盖 2 天", detail)
        self.assertIn("供应商交期为 10 天", detail)

    def test_ai_assistant_is_on_demand_and_context_change_clears_history(self):
        with patch.object(
            dashboard,
            "answer_supply_chain_question",
            side_effect=AssertionError("assistant must not run on page refresh"),
        ):
            app = self._app()

        self.assertFalse(app.get_by_key("quick_single_0").disabled)
        initial_context_id = app.session_state["chat_context_id"]
        self.assertTrue(initial_context_id)
        app.session_state["chat_messages"] = [
            {"role": "user", "content": "旧上下文问题"}
        ]

        app.get_by_key("lead_time_days").set_value(12.0).run()
        app.get_by_key("run_single_analysis").click().run()

        self.assertNotEqual(app.session_state["chat_context_id"], initial_context_id)
        self.assertEqual(app.session_state["chat_messages"], [])
        self._assert_no_page_exception(app)

    def test_llm_failure_is_visible_and_template_fallback_remains_usable(self):
        app = self._app()
        with patch.object(
            agents,
            "_generate_llm_report",
            side_effect=ConnectionError("simulated dashboard outage"),
        ):
            app.get_by_key("generate_llm_report").click().run()

        result = app.session_state["last_result"]
        self.assertEqual(result["report_source"], "template_fallback")
        self.assertIn("simulated dashboard outage", result["llm_error"])
        self.assertTrue(result["management_report"].startswith("管理层分析报告"))
        self.assertTrue(
            any("已自动展示可靠的中文模板报告" in item.value for item in app.warning)
        )

        # A passive rerun with unchanged inputs must not replace the explicit result.
        app.run()
        self.assertEqual(
            app.session_state["last_result"]["report_source"],
            "template_fallback",
        )
        self._assert_no_page_exception(app)

    def test_input_change_after_llm_request_returns_to_template_mode(self):
        class FakeLlm:
            def invoke(self, _prompt):
                return (
                    "当前为低风险（LOW），建议执行无需行动（No Action），"
                    "并维持常规供应商监测。"
                )

        app = self._app()
        with patch.object(agents, "_create_ollama_llm", return_value=FakeLlm()):
            app.get_by_key("generate_llm_report").click().run()
        self.assertEqual(app.session_state["last_result"]["report_source"], "llm")

        app.get_by_key("lead_time_days").set_value(12.0).run()
        app.get_by_key("run_single_analysis").click().run()
        refreshed = app.session_state["last_result"]
        self.assertEqual(refreshed["report_source"], "template")
        self.assertEqual(refreshed["inventory_metrics"]["stockout_gap"], 2.0)
        self._assert_no_page_exception(app)


if __name__ == "__main__":
    unittest.main()
