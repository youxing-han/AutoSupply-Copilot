import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "agent"))

from agents import build_supply_chain_graph, create_initial_state
from report_pdf import build_pdf_report
from supply_data import get_scenario_part


class PdfReportTests(unittest.TestCase):
    def test_pdf_uses_verified_workflow_result(self):
        state = create_initial_state(
            "Supplier Delay",
            get_scenario_part("Supplier Delay", "SEN-001"),
            use_llm_report=False,
        )
        result = build_supply_chain_graph().invoke(state)

        pdf = build_pdf_report(result)

        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 2_000)
        self.assertIn(b"AutoSupply Copilot", pdf)


if __name__ == "__main__":
    unittest.main()
