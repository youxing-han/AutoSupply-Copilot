"""Three-mode website proposal, isolated from the running application."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_planning_preview import SPECS, build_catalog  # noqa: E402
from calculations import calculate_inventory_metrics  # noqa: E402
from agents import evaluate_supplier_risk  # noqa: E402

STATIC_SCENARIOS = ("常规供给", "交付延迟", "需求增长", "集中缺料")


def static_result(row: dict) -> dict:
    metrics = calculate_inventory_metrics(row["stock"], row["usage"], row["lead"], row["safety"])
    risk = evaluate_supplier_risk({"current_stock": row["stock"],
                                   "criticality": row["critical"],
                                   "supplier_status": row["supplierStatus"]}, metrics)
    return {"coverage": metrics["days_of_stock"], "gap": metrics["stockout_gap"],
            "quantity": metrics["recommended_order_qty"], "reorder": metrics["reorder_point"],
            "risk": risk["risk_level"]}


def build_static_catalog() -> dict:
    sources = {}
    leads = (7, 5, 10, 8, 9, 6, 8, 7, 9, 5, 6, 10)
    for scene in STATIC_SCENARIOS:
        rows = []
        for index, (code, name, supplier, rate, stock, safety) in enumerate(SPECS):
            row = {"code": code, "name": name, "supplier": supplier,
                   "stock": 800 if index == 0 else stock,
                   "usage": rate, "lead": leads[index], "safety": safety,
                   "critical": "HIGH" if index in (2, 3, 4, 8, 11) else "MEDIUM",
                   "supplierStatus": "NORMAL"}
            if scene == "交付延迟" and index in (0, 2, 5):
                row["lead"] = 14 if index == 0 else row["lead"] + 4
                row["supplierStatus"] = "DELAYED"
            if scene == "需求增长" and index in (0, 2, 5, 9):
                row["usage"] = round(rate * 1.5)
            if scene == "集中缺料" and index in (3, 8, 11):
                row["stock"] = round(rate * 1.5)
            row["verified"] = static_result(row)
            rows.append(row)
        sources[scene] = rows
    return sources


def render(output: Path) -> None:
    dynamic = (HERE / "planning-redesign.template.html").read_text(encoding="utf-8")
    dynamic = dynamic.replace("__PREVIEW_DATA__", json.dumps(build_catalog(), ensure_ascii=False, separators=(",", ":")))
    site = (HERE / "copilot-website.template.html").read_text(encoding="utf-8")
    assert site.count("__DYNAMIC_PREVIEW__") == 1 and site.count("__SITE_DATA__") == 1
    result = site.replace("__DYNAMIC_PREVIEW__", dynamic).replace(
        "__SITE_DATA__", json.dumps(build_static_catalog(), ensure_ascii=False, separators=(",", ":")))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    render(parser.parse_args().output)
