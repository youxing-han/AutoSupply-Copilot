"""Time-phased v2 model, integer pieces, receipts before same-day demand.

Unfulfilled production is recorded but NOT carried as a backorder. All results
are deterministic conditional forecasts, not real stock or production events.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from numbers import Real


def day(value, field="date") -> date:
    if isinstance(value, datetime):
        if value.time() != datetime.min.time() or value.tzinfo is not None:
            raise ValueError(f"{field}: use a date without time/timezone")
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() == value:
                return parsed
        except ValueError:
            pass
    raise ValueError(f"{field}: expected YYYY-MM-DD date")


def quantity(value, field="quantity") -> int:
    if (isinstance(value, bool) or not isinstance(value, Real)
            or not math.isfinite(float(value)) or value < 0 or int(value) != value):
        raise ValueError(f"{field}: expected a finite non-negative integer")
    return int(value)


def simulate_inventory(part: dict, demands: list[dict], orders: list[dict],
                       start_date, horizon_days=30) -> dict:
    start = day(start_date, "start_date")
    horizon = quantity(horizon_days, "horizon_days")
    if not 1 <= horizon <= 90:
        raise ValueError("horizon_days must be between 1 and 90")
    sku = part["part_code"]
    initial = quantity(part["current_stock"], "current_stock")
    safety = float(part.get("safety_stock", 0))
    if not math.isfinite(safety) or safety < 0:
        raise ValueError("safety_stock must be finite and non-negative")
    dates = [start + timedelta(days=i) for i in range(horizon)]
    demand_map = {}
    for row in demands:
        if row["part_code"] != sku:
            raise ValueError("demand references wrong SKU")
        d = day(row["date"])
        if d not in dates or d in demand_map:
            raise ValueError("demand date is duplicate or outside horizon")
        demand_map[d] = quantity(row["quantity"], "demand quantity")
    if set(demand_map) != set(dates):
        raise ValueError("provide exactly one demand row per SKU per day, including zero days")
    receipts = {d: [] for d in dates}
    po_ids, excluded, included = set(), [], []
    for row in orders:
        po = row["po_id"]
        if not isinstance(po, str) or not po.strip() or po != po.strip() or po in po_ids:
            raise ValueError("PO identifier is empty or duplicate")
        po_ids.add(po)
        if row["part_code"] != sku:
            raise ValueError("PO references wrong SKU")
        if not isinstance(row["supplier"], str) or not row["supplier"].strip():
            raise ValueError("PO supplier is required")
        q = quantity(row["open_quantity"], "PO open_quantity")
        d = day(row["arrival_date"], "arrival_date")
        status = row["status"]
        if status not in {"CONFIRMED", "PENDING", "CANCELLED"}:
            raise ValueError("PO status must be CONFIRMED/PENDING/CANCELLED")
        if status == "CONFIRMED" and d < start:
            raise ValueError("overdue confirmed PO must have its arrival date reconfirmed")
        normalized = {**row, "arrival_date": d.isoformat(), "open_quantity": q}
        if status == "CONFIRMED" and d in receipts:
            receipts[d].append(normalized)
            included.append(normalized)
        else:
            excluded.append(normalized)

    def run(with_orders):
        available, daily = initial, []
        for d in dates:
            opening = available
            received = sum(p["open_quantity"] for p in receipts[d]) if with_orders else 0
            demand = demand_map[d]
            satisfied = min(demand, opening + received)
            unmet = demand - satisfied
            balance = opening + received - demand
            available = max(0, balance)
            daily.append({"date": d.isoformat(), "opening_available": opening,
                          "confirmed_receipts": received, "planned_demand": demand,
                          "satisfied_demand": satisfied, "unmet_demand": unmet,
                          "projected_balance": balance, "closing_available": available,
                          "below_safety_stock": available < safety,
                          "po_ids": [p["po_id"] for p in receipts[d]] if with_orders else []})
        return daily

    daily = run(True)
    missing = [r for r in daily if r["unmet_demand"] > 0]
    windows = []
    for row in missing:
        if windows and day(row["date"]) == day(windows[-1]["end"]) + timedelta(days=1):
            windows[-1]["end"] = row["date"]
            windows[-1]["days"] += 1
            windows[-1]["quantity"] += row["unmet_demand"]
        else:
            windows.append({"start": row["date"], "end": row["date"],
                            "days": 1, "quantity": row["unmet_demand"]})
    baseline_missing = [r for r in run(False) if r["unmet_demand"] > 0]
    unmet = sum(r["unmet_demand"] for r in missing)
    baseline_unmet = sum(r["unmet_demand"] for r in baseline_missing)
    return {"model_version": "time-phased-v2", "part_code": sku,
            "start_date": start.isoformat(), "horizon_days": horizon,
            "initial_available": initial, "daily": daily,
            "first_shortage_date": missing[0]["date"] if missing else None,
            "first_shortage_quantity": missing[0]["unmet_demand"] if missing else 0,
            "total_unmet_demand": unmet, "shortage_days": len(missing),
            "risk_windows": windows, "final_available": daily[-1]["closing_available"],
            "safety_warning_dates": [r["date"] for r in daily if r["below_safety_stock"]],
            "confirmed_orders": included, "excluded_orders": excluded,
            "without_orders_unmet": baseline_unmet,
            "without_orders_first_shortage": baseline_missing[0]["date"] if baseline_missing else None,
            "unmet_avoided_by_confirmed_orders": baseline_unmet - unmet,
            "backorder_policy": "unmet demand is not carried; reschedule manually"}


def evaluate_dynamic_risk(part: dict, projection: dict) -> dict:
    shortage = projection["total_unmet_demand"] > 0
    safety = bool(projection["safety_warning_dates"])
    warning = part["supplier_status"] != "NORMAL"
    critical = part["criticality"] == "HIGH"
    level = "HIGH" if shortage and (critical or warning) else "MEDIUM" if shortage or safety or warning else "LOW"
    reasons = []
    if shortage:
        reasons.append(f"预计 {projection['first_shortage_date']} 首次缺料 {projection['first_shortage_quantity']} 件，累计未满足需求 {projection['total_unmet_demand']} 件，涉及 {projection['shortage_days']} 个生产日。")
    else:
        reasons.append("预测期内未出现数量短缺。")
    if safety:
        reasons.append(f"有 {len(projection['safety_warning_dates'])} 天期末库存低于安全库存阈值，属于缓冲预警。")
    if warning:
        reasons.append(f"供应商状态 {part['supplier_status']}，已确认订单按提供的到货日期进行条件预测，仍需跟踪履约。")
    reasons.append("预测数量短缺不等同于实际生产停线；未满足生产需求需人工重排。")
    return {"risk_level": level, "reasons": reasons, "mitigating_factors": [
        f"确认在途订单相对无订单场景减少未满足需求 {projection['unmet_avoided_by_confirmed_orders']} 件。"],
        "quantity_shortage": shortage, "safety_stock_warning": safety,
        "supplier_warning": warning, "rule_version": "time-phased-v2"}


def dynamic_decision(part: dict, projection: dict) -> dict:
    shortage = projection["total_unmet_demand"]
    safety = float(part.get("safety_stock", 0))
    q = math.ceil(shortage + max(0, safety - projection["final_available"]))
    return {"recommended_action": "Emergency Reorder" if shortage else "Normal Reorder" if q else "No Action",
            "recommended_order_qty": q,
            "supporting_actions": ["Expedite Delivery", "Evaluate Backup Supplier"] if shortage else [],
            "decision_reasons": [f"计划保障参考量为未满足需求 {shortage} 件，加期末安全库存差额 {max(0, safety - projection['final_available']):g} 件，向上取整为 {q} 件。",
                                 "参考量不能证明到货前缺口已解决，必须以候选到货日期和数量重新模拟。"],
            "caveats": ["未满足需求不结转；参考量供人工重排和应急供给讨论，不是自动采购指令。"]}


def dynamic_report(state: dict) -> str:
    p, r = state["inventory_projection"], state["supplier_risk"]
    decision = state["replenishment_decision"]
    orders = "；".join(f"{o['po_id']}：{o['arrival_date']} 到货 {o['open_quantity']} 件" for o in p["confirmed_orders"]) or "无"
    return (f"动态物料计划报告｜{p['part_code']}｜{p['start_date']} 起 {p['horizon_days']} 天\n"
            f"期初实际可用 {p['initial_available']} 件；期末预计可用 {p['final_available']} 件。\n"
            f"首次预计缺料：{p['first_shortage_date'] or '预测期内无缺料'}；首次缺料 {p['first_shortage_quantity']} 件；累计未满足 {p['total_unmet_demand']} 件；缺料日数 {p['shortage_days']} 天。\n"
            f"风险等级 {r['risk_level']}：{' '.join(r['reasons'])}\n"
            f"确认在途：{orders}；无订单累计缺料 {p['without_orders_unmet']} 件；确认订单减少缺料 {p['unmet_avoided_by_confirmed_orders']} 件。\n"
            f"建议：{' '.join(decision['decision_reasons'])}\n"
            "业务假设：当日先收货后生产；库存最低为零；未满足需求不自动结转；待确认订单不计入；所有输入完全虚构。\n"
            "静态 v1 指标仅供历史对照，不作为本报告的缺料结论。")
