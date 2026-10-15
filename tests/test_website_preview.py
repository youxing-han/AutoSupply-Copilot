"""Validate three-mode proposal against existing static business calculations."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "docs/prototypes/build_website_preview.py"
spec = importlib.util.spec_from_file_location("website_preview", SCRIPT)
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class WebsitePreviewTests(unittest.TestCase):
    def test_single_reference_matches_existing_coverage_formula(self):
        p = preview.build_static_catalog()["交付延迟"][0]
        self.assertEqual(p["verified"], {"coverage": 10, "gap": 4, "quantity": 560,
                                         "reorder": 1360, "risk": "HIGH"})

    def test_batch_contains_twelve_parts_and_four_controlled_scenarios(self):
        catalog = preview.build_static_catalog()
        self.assertEqual(set(catalog), set(preview.STATIC_SCENARIOS))
        for rows in catalog.values():
            self.assertEqual(len(rows), 12)
            self.assertEqual(len({p["code"] for p in rows}), 12)
            for p in rows:
                self.assertEqual(p["verified"], preview.static_result(p))

    def test_delay_changes_lead_not_initial_stock_or_daily_usage(self):
        catalog = preview.build_static_catalog()
        for a, b in zip(catalog["常规供给"], catalog["交付延迟"]):
            self.assertEqual(a["stock"], b["stock"])
            self.assertEqual(a["usage"], b["usage"])
            self.assertGreaterEqual(b["lead"], a["lead"])

    def test_renderer_contains_all_three_modes_and_embeds_dynamic_model(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "website.html"
            preview.render(output)
            html = output.read_text(encoding="utf-8")
        for key in ("single", "batch", "dynamic"):
            self.assertIn(f'data-site-mode="{key}"', html)
        self.assertIn('id="material-plan-preview"', html)
        self.assertNotIn("__DYNAMIC_PREVIEW__", html)
        self.assertNotIn("__SITE_DATA__", html)
        self.assertNotIn("__PREVIEW_DATA__", html)
        self.assertLess(len(html.encode("utf-8")), 1_000_000)


if __name__ == "__main__":
    unittest.main()
