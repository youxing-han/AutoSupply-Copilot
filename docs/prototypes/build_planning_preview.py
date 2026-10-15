"""Build an isolated discussion mockup; never imported by the Streamlit app.

All records are fictional. Curves are computed with the existing Python model.
Weekday production, scheduled peaks and split receipts create the variation.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent"))
from inventory_planning import simulate_inventory  # noqa: E402

START = date(2026, 10, 14)
SCENARIOS = ("平稳排产", "供应商延期", "排产高峰", "订单待确认", "周末检修", "集中到货")
SPECS = (
    ("SEN-001", "前向感知传感器", "星澜传感科技", 80, 640, 3),
    ("BRG-002", "轮毂轴承", "精衡轴承制造", 100, 1080, 2),
    ("CTL-003", "车身控制器", "启程汽车电子", 30, 240, 4),
    ("BRK-004", "制动控制模块", "安驰制动系统", 20, 180, 3),
    ("BAT-005", "电池连接组件", "澄能动力部件", 50, 420, 3),
    ("HRN-006", "低压线束", "联序线束制造", 180, 1500, 2),
    ("PUM-007", "冷却水泵", "清源热管理", 48, 390, 3),
    ("VLV-008", "电磁控制阀", "锐控精密部件", 65, 610, 2),
    ("RAD-009", "散热器总成", "清源热管理", 36, 320, 3),
    ("CON-010", "高压连接器", "联序线束制造", 210, 1780, 2),
    ("SEA-011", "动力系统密封圈", "恒密高分子", 320, 2800, 2),
    ("CAM-012", "环视摄像头", "星澜传感科技", 96, 720, 3),
)


def build_source(scenario: str, anchor: bool = False) -> dict:
    if scenario not in SCENARIOS:
        raise ValueError("unknown preview scenario")
    products = []
    for index, (code, name, supplier, rate, stock, safety) in enumerate(SPECS[:1] if anchor else SPECS):
        stock = 800 if anchor else stock
        demand = []
        for offset in range(60):
            weekday = (START + timedelta(days=offset)).weekday()
            factor = (1.05, 1.0, 1.1, 0.95, 1.15, 0.45, 0)[weekday]
            week = (1, 1.15, 0.92, 1.08, 1.02, 1.1, 0.96, 1.04, 1)[offset // 7]
            q = rate if anchor else round(rate * factor * week)
            if scenario == "排产高峰" and 6 <= offset <= 9:
                q = q * 2 if anchor else round(q * 1.75)
            if scenario == "周末检修" and weekday >= 5 and not anchor:
                q = 0
            demand.append(q)
        orders = []
        schedule = [(8, 500)] if anchor else [(7 + index % 3 + 8 * k, round(rate * (7.6 if k % 2 == 0 else 7.1))) for k in range(7)]
        for number, (arrival, qty) in enumerate(schedule):
            status, actual = "已确认", arrival
            affected = anchor or index in (0, 2, 5)
            if scenario == "供应商延期" and number == 0 and affected:
                actual += 4
            if scenario == "订单待确认" and number == 0 and affected:
                status = "待确认"
            if scenario == "集中到货" and not anchor:
                actual = ((arrival - 1) // 7 + 1) * 7
            orders.append({"id": f"MN-{code}-{number + 1:02d}", "day": actual,
                           "original": arrival, "qty": qty, "status": status})
        if not anchor and index in (1, 4, 9):
            orders.append({"id": f"MN-{code}-补充", "day": 25, "original": 25,
                           "qty": rate * 2, "status": "待确认"})
        products.append({"code": code, "name": name, "supplier": supplier,
                         "stock": stock, "rate": rate, "safetyDays": safety,
                         "demand": demand, "orders": orders})
    return {"scenario": scenario, "products": products}


def project(product: dict, horizon: int = 60, normal: bool = False) -> dict:
    demands = [{"part_code": product["code"], "date": (START + timedelta(days=i)).isoformat(),
                "quantity": q} for i, q in enumerate(product["demand"][:horizon])]
    orders = []
    for order in product["orders"]:
        arrival = order["original"] if normal else order["day"]
        status = "已确认" if normal and order["status"] != "已取消" else order["status"]
        orders.append({"po_id": order["id"], "part_code": product["code"],
                       "supplier": product["supplier"], "open_quantity": order["qty"],
                       "arrival_date": (START + timedelta(days=arrival - 1)).isoformat(),
                       "status": {"已确认": "CONFIRMED", "待确认": "PENDING", "已取消": "CANCELLED"}[status]})
    return simulate_inventory({"part_code": product["code"], "current_stock": product["stock"]},
                              demands, orders, START, horizon)


def build_catalog() -> dict:
    packs = {}
    for key, anchor in (("assembly", False), ("anchor", True)):
        packs[key] = {}
        for scenario in SCENARIOS:
            source = build_source(scenario, anchor)
            for p in source["products"]:
                p["verified"] = [[r["closing_available"], r["unmet_demand"]] for r in project(p)["daily"]]
            packs[key][scenario] = source
    return {"start": START.isoformat(), "scenarios": list(SCENARIOS), "packs": packs}


def render(output: Path) -> None:
    template = Path(__file__).with_name("planning-redesign.template.html").read_text(encoding="utf-8")
    payload = json.dumps(build_catalog(), ensure_ascii=False, separators=(",", ":"))
    assert template.count("__PREVIEW_DATA__") == 1
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace("__PREVIEW_DATA__", payload), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    render(parser.parse_args().output)
