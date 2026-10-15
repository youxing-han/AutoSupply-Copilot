import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from batch_analysis import (
    MAX_BATCH_SKUS,
    analyze_batch,
    batch_results_csv_bytes,
    build_batch_template,
    read_batch_file,
    template_csv_bytes,
    template_xlsx_bytes,
    validate_batch_dataframe,
)


class BatchAnalysisTests(unittest.TestCase):
    def test_csv_and_xlsx_templates_round_trip(self):
        csv_frame = read_batch_file("template.csv", template_csv_bytes())
        xlsx_frame = read_batch_file("template.xlsx", template_xlsx_bytes())

        self.assertEqual(len(csv_frame), 5)
        self.assertEqual(list(csv_frame.columns), list(xlsx_frame.columns))
        self.assertEqual(csv_frame.iloc[0]["part_code"], "SEN-001")

    def test_rejects_missing_columns_invalid_values_and_duplicate_skus(self):
        missing = pd.DataFrame({"part_code": ["A"]})
        normalized, errors = validate_batch_dataframe(missing)
        self.assertIsNone(normalized)
        self.assertTrue(any("缺少必要字段" in error for error in errors))

        invalid = build_batch_template().iloc[:2].copy()
        invalid.loc[1, "part_code"] = invalid.loc[0, "part_code"].lower()
        invalid.loc[0, "current_stock"] = -1
        invalid.loc[1, "supplier_status"] = "BROKEN"
        invalid.loc[0, "criticality"] = "URGENT"
        invalid["backup_supplier_available"] = invalid[
            "backup_supplier_available"
        ].astype(object)
        invalid.loc[1, "backup_supplier_available"] = "maybe"
        normalized, errors = validate_batch_dataframe(invalid)

        self.assertIsNone(normalized)
        joined = "\n".join(errors)
        self.assertIn("SKU 编码重复", joined)
        self.assertIn("current_stock", joined)
        self.assertIn("supplier_status", joined)
        self.assertIn("criticality", joined)
        self.assertIn("backup_supplier_available", joined)

    def test_rejects_more_than_fifty_skus(self):
        row = build_batch_template().iloc[[0]]
        frame = pd.concat([row] * (MAX_BATCH_SKUS + 1), ignore_index=True)
        frame["part_code"] = [f"SKU-{index:03d}" for index in range(len(frame))]

        normalized, errors = validate_batch_dataframe(frame)

        self.assertIsNone(normalized)
        self.assertTrue(any("最多分析 50 个 SKU" in error for error in errors))

    def test_batch_runs_existing_graph_and_sorts_high_risk_first(self):
        frame = build_batch_template().iloc[:3].copy()
        frame.loc[0, ["current_stock", "lead_time_days", "supplier_status"]] = [
            800,
            7,
            "NORMAL",
        ]
        frame.loc[1, ["current_stock", "lead_time_days", "supplier_status"]] = [
            100,
            12,
            "DELAYED",
        ]
        frame.loc[2, ["current_stock", "lead_time_days", "supplier_status"]] = [
            300,
            10,
            "NORMAL",
        ]
        progress: list[tuple[int, int]] = []

        result = analyze_batch(frame, lambda current, total: progress.append((current, total)))

        self.assertEqual(result["success_count"], 3)
        self.assertEqual(result["failure_count"], 0)
        self.assertEqual(result["summary"].iloc[0]["risk_level"], "HIGH")
        self.assertEqual(progress[-1], (3, 3))
        for detail in result["details"].values():
            self.assertEqual(
                [item["node_name"] for item in detail["execution_trace"]],
                [
                    "Inventory Monitor",
                    "Supplier Risk",
                    "Replenishment Decision",
                    "Management Report",
                ],
            )
            self.assertEqual(detail["report_source"], "template")

    def test_one_row_failure_does_not_abort_remaining_rows(self):
        frame = build_batch_template().iloc[:3].copy()

        class IsolatedFailureGraph:
            def __init__(self, real_graph):
                self.real_graph = real_graph

            def invoke(self, state):
                if state["selected_part"]["part_code"] == "BRG-002":
                    raise RuntimeError("simulated row failure")
                return self.real_graph.invoke(state)

        from batch_analysis import build_supply_chain_graph

        wrapped = IsolatedFailureGraph(build_supply_chain_graph())
        with patch("batch_analysis.build_supply_chain_graph", return_value=wrapped):
            result = analyze_batch(frame)

        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["failure_count"], 1)
        self.assertEqual(result["failures"][0]["part_code"], "BRG-002")
        self.assertIn("simulated row failure", result["failures"][0]["error"])

    def test_export_contains_sorted_summary(self):
        result = analyze_batch(build_batch_template().iloc[:2].copy())
        exported = pd.read_csv(io.BytesIO(batch_results_csv_bytes(result)))

        self.assertEqual(len(exported), 2)
        self.assertIn("risk_level", exported.columns)
        self.assertIn("recommended_order_qty", exported.columns)

    def test_unsupported_file_extension_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "仅支持"):
            read_batch_file("parts.txt", b"part_code")


if __name__ == "__main__":
    unittest.main()
