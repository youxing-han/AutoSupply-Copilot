import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

import assistant
from agents import build_supply_chain_graph, create_initial_state
from batch_analysis import analyze_batch, build_batch_template
from supply_data import get_scenario_part


def scenario_result(scenario: str = "Supplier Delay"):
    part_code = "SEN-001" if scenario != "Critical Shortage" else "BRK-004"
    state = create_initial_state(
        scenario, get_scenario_part(scenario, part_code), use_llm_report=False
    )
    return build_supply_chain_graph().invoke(state)


class AssistantTests(unittest.TestCase):
    def test_single_context_uses_verified_workflow_facts(self):
        context = assistant.build_assistant_context(
            "single", single_result=scenario_result()
        )

        self.assertIsNotNone(context)
        self.assertIn("SEN-001", context["facts_text"])
        self.assertIn("潜在覆盖缺口 4 天", context["facts_text"])
        self.assertIn("建议订货量 560 件", context["facts_text"])
        self.assertEqual(context["payload"]["risk_level"], "HIGH")

    def test_context_id_changes_when_analysis_facts_change(self):
        delayed = assistant.build_assistant_context(
            "single", single_result=scenario_result("Supplier Delay")
        )
        normal = assistant.build_assistant_context(
            "single", single_result=scenario_result("Normal Supply")
        )
        self.assertNotEqual(delayed["context_id"], normal["context_id"])

        changed_stock_result = deepcopy(scenario_result("Normal Supply"))
        changed_stock_result["selected_part"]["current_stock"] = 799.0
        changed_stock = assistant.build_assistant_context(
            "single", single_result=changed_stock_result
        )
        self.assertNotEqual(normal["context_id"], changed_stock["context_id"])

    def test_batch_context_uses_sorted_priority_results(self):
        batch = analyze_batch(build_batch_template())
        context = assistant.build_assistant_context("batch", batch_result=batch)

        self.assertEqual(context["payload"]["total_count"], 5)
        self.assertEqual(
            context["payload"]["priorities"][0]["part_code"],
            batch["summary"].iloc[0]["part_code"],
        )
        self.assertIn("本批次共 5 个 SKU", context["facts_text"])

    def test_batch_context_tracks_the_current_selected_sku(self):
        batch = analyze_batch(build_batch_template())
        codes = list(batch["details"])

        first = assistant.build_assistant_context(
            "batch", batch_result=batch, selected_part_code=codes[0]
        )
        second = assistant.build_assistant_context(
            "batch", batch_result=batch, selected_part_code=codes[1]
        )

        self.assertNotEqual(first["context_id"], second["context_id"])
        self.assertEqual(
            first["payload"]["selected_priority"]["part_code"], codes[0]
        )
        self.assertIn(f"当前查看：{codes[0]}", first["facts_text"])

    def test_answer_combines_python_facts_with_qualitative_llm_text(self):
        class FakeLlm:
            def invoke(self, prompt):
                self.prompt = prompt
                return "该风险来自库存覆盖与供应交付节奏不匹配，应优先核验交付缓解措施。"

        context = assistant.build_assistant_context(
            "single", single_result=scenario_result()
        )
        with patch.object(assistant, "_create_ollama_llm", return_value=FakeLlm()):
            answer = assistant.answer_supply_chain_question(
                "为什么是高风险？", context, history=[]
            )

        self.assertIn("系统核验事实", answer)
        self.assertIn("建议订货量 560 件", answer)
        self.assertIn("AI 定性解释", answer)

    def test_numeric_or_executed_action_claim_is_rejected(self):
        context = assistant.build_assistant_context(
            "single", single_result=scenario_result()
        )

        class NumericLlm:
            def invoke(self, _prompt):
                return "建议采购五百六十件，数值为 560。"

        with patch.object(assistant, "_create_ollama_llm", return_value=NumericLlm()):
            with self.assertRaisesRegex(
                assistant.AssistantUnavailableError, "新增数值"
            ):
                assistant.answer_supply_chain_question("如何处理？", context)

        class ActionLlm:
            def invoke(self, _prompt):
                return "系统已经下单，后续等待交付即可。"

        with patch.object(assistant, "_create_ollama_llm", return_value=ActionLlm()):
            with self.assertRaisesRegex(
                assistant.AssistantUnavailableError, "未经执行"
            ):
                assistant.answer_supply_chain_question("进展如何？", context)

    def test_ollama_failure_returns_friendly_domain_error(self):
        context = assistant.build_assistant_context(
            "single", single_result=scenario_result()
        )
        with patch.object(
            assistant,
            "_create_ollama_llm",
            side_effect=ConnectionError("simulated outage"),
        ):
            with self.assertRaisesRegex(
                assistant.AssistantUnavailableError, "本地 Ollama 暂时不可用"
            ):
                assistant.answer_supply_chain_question("解释风险", context)


if __name__ == "__main__":
    unittest.main()
