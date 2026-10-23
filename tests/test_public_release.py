import io
import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

import agents
import assistant
from batch_analysis import build_batch_template, read_batch_file
from planning_data import build_interview_demo, planning_xlsx_bytes, read_planning_xlsx, validate_planning_bundle
from report_pdf import build_pdf_report
from runtime_mode import is_public_demo
from supply_data import get_scenario_part
from upload_safety import validate_upload


class PublicCapabilityTests(unittest.TestCase):
    def test_attribution_files_preserved_outside_readme(self):
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("Cindy Aprilia", license_text)
        self.assertIn("Permission is hereby granted", license_text)
        self.assertIn("https://github.com/cinapr/SupplyChainAgenticAI", notices)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("## 开源来源与许可", readme)

    def test_published_links_and_screenshots_are_complete(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("https://autosupply-copilot.streamlit.app/", readme)
        self.assertIn("https://github.com/youxing-han/AutoSupply-Copilot", readme)
        for mode in ("single", "batch", "planning", "mitigation"):
            path = ROOT / "docs/screenshots" / f"online-{mode}.jpg"
            self.assertGreater(path.stat().st_size, 10_000)
            self.assertEqual(path.read_bytes()[:3], b"\xff\xd8\xff")

    @patch.dict(os.environ, {"AUTOSUPPLY_MODE": "public"})
    def test_no_model_constructor_even_for_explicit_report_request(self):
        with patch.object(agents, "OllamaLLM", side_effect=AssertionError("model accessed")):
            with self.assertRaises(RuntimeError):
                agents._create_ollama_llm()
            state = agents.create_initial_state("Normal Supply", get_scenario_part("Normal Supply", "SEN-001"), use_llm_report=True)
            result = agents.build_supply_chain_graph().invoke(state)
        self.assertEqual(result["report_source"], "template_fallback")
        self.assertFalse(result.get("workflow_error"))
        self.assertEqual(len(result["execution_trace"]), 4)
        self.assertTrue(build_pdf_report(result).startswith(b"%PDF"))

    @patch.dict(os.environ, {"AUTOSUPPLY_MODE": "public"})
    def test_assistant_blocked_before_any_model_or_context_access(self):
        with patch.object(assistant, "_create_ollama_llm", side_effect=AssertionError("model accessed")):
            with self.assertRaisesRegex(assistant.AssistantUnavailableError, "在线演示"):
                assistant.answer_supply_chain_question("why", {})

    @patch.dict(os.environ, {"AUTOSUPPLY_MODE": "local"})
    def test_local_model_client_preserved(self):
        with patch.object(agents, "OllamaLLM") as factory:
            agents._create_ollama_llm()
        self.assertEqual(factory.call_args.kwargs["base_url"], "http://127.0.0.1:11434")

    @patch.dict(os.environ, {"AUTOSUPPLY_MODE": "typo"})
    def test_invalid_mode_fails_closed(self):
        with self.assertRaises(ValueError):
            is_public_demo()


class UploadSafetyTests(unittest.TestCase):
    def test_csv_duplicate_or_excess_headers_rejected_before_dataframe_parse(self):
        for payload in (b"part_code,part_code\na,b", (",".join(f"x{i}" for i in range(41)) + "\n").encode()):
            with patch("batch_analysis.pd.read_csv", side_effect=AssertionError("parsed before header check")):
                with self.assertRaises(ValueError):
                    read_batch_file("unsafe.csv", payload)

    def test_release_allowlist_excludes_private_and_irrelevant_files(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("release_builder", ROOT / "scripts/build_public_release.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        for path in (".env", ".streamlit/secrets.toml", ".venv/a.py", ".runtime/result.pdf", "docs/development_progress.md", "Documentation/movie.mp4", "docs/design.docx", "simulation/results/data.csv"):
            self.assertFalse(builder.allowed(path), path)
        for path in ("LICENSE", "public_app.py", "agent/agents.py", "templates/autosupply_dynamic_demo.xlsx"):
            self.assertTrue(builder.allowed(path), path)

    def test_batch_csv_and_excel_roundtrip(self):
        frame = build_batch_template()
        csv = read_batch_file("demo.csv", frame.to_csv(index=False).encode("utf-8-sig"))
        output = io.BytesIO()
        frame.to_excel(output, index=False)
        excel = read_batch_file("demo.xlsx", output.getvalue())
        self.assertEqual(list(csv.part_code), list(excel.part_code))

    def test_excess_rows_and_long_cells_rejected(self):
        import pandas as pd
        frame = pd.concat([build_batch_template()] * 11, ignore_index=True)
        with self.assertRaises(ValueError):
            read_batch_file("too_many.csv", frame.to_csv(index=False).encode())
        frame = build_batch_template()
        frame.loc[0, "part_name"] = "x" * 501
        with self.assertRaises(ValueError):
            read_batch_file("long.csv", frame.to_csv(index=False).encode())

    def test_invalid_formats_and_oversize_rejected(self):
        for name, payload in [("test.py", b"print(1)"), ("test.csv", b"a\x00b"), ("test.xlsx", b"broken"), ("test.csv", b"a" * 5_000_001)]:
            with self.subTest(name=name, size=len(payload)), self.assertRaises(ValueError):
                read_batch_file(name, payload)

    def test_zip_bomb_macro_and_external_link_rejected(self):
        for name, content in [("xl/worksheets/sheet1.xml", b"a" * 25_000_001), ("xl/vbaProject.bin", b"macro"), ("xl/externalLinks/externalLink1.xml", b"link")]:
            output = io.BytesIO()
            with ZipFile(output, "w", ZIP_DEFLATED) as archive:
                archive.writestr("[Content_Types].xml", "")
                archive.writestr("xl/workbook.xml", "")
                archive.writestr(name, content)
            with self.assertRaises(ValueError):
                validate_upload(output.getvalue(), xlsx=True)

    def test_planning_roundtrip_and_bounded_orders(self):
        bundle = build_interview_demo(horizon_days=14)
        parsed = read_planning_xlsx(planning_xlsx_bytes(bundle))
        self.assertEqual(len(parsed["demands"]), 70)
        too_many = deepcopy(bundle)
        too_many["orders"] = too_many["orders"] * 101
        with self.assertRaisesRegex(ValueError, "500"):
            validate_planning_bundle(too_many)


class PublicSessionTests(unittest.TestCase):
    @patch.dict(os.environ, {"AUTOSUPPLY_MODE": "public"})
    def test_two_sessions_are_independent_and_have_no_llm_controls(self):
        from streamlit.testing.v1 import AppTest
        a = AppTest.from_file(str(ROOT / "public_app.py"), default_timeout=30).run()
        b = AppTest.from_file(str(ROOT / "public_app.py"), default_timeout=30).run()
        self.assertEqual(list(a.exception), [])
        self.assertEqual(list(b.exception), [])
        a.session_state["chat_messages"] = [{"role": "user", "content": "SESSION_A_ONLY"}]
        self.assertEqual(b.session_state["chat_messages"], [])
        a.get_by_key("current_inventory").set_value(321).run()
        self.assertNotEqual(a.session_state["current_inventory"], b.session_state["current_inventory"])
        self.assertNotIn("检查本地模型连接", [button.label for button in a.button])
        self.assertTrue(a.get_by_key("generate_llm_report").disabled)


if __name__ == "__main__":
    unittest.main()
