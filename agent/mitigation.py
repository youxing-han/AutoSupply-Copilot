"""Deterministic fixed-lot scenario enumeration, bounded to eight candidates.

Objective: zero unmet demand over the horizon, then minimum modeled incremental
cost. If no zero-shortage combination exists, minimize residual unmet units,
then cost. Results are optimal ONLY within supplied fixed lots, not an ERP-wide
or continuous-quantity optimization. Committed baseline PO costs are common and
excluded. Expediting a linked PO changes its date; it never duplicates its stock.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from itertools import combinations

from inventory_planning import day, quantity, simulate_inventory

MAX_CANDIDATES = 8
KINDS = {"EXPEDITE", "BACKUP", "TRANSFER"}


def money_cents(value, field="cost") -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field}: expected non-negative money with at most two decimals")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount * 100 != (amount * 100).to_integral_value():
            raise ValueError()
        return int(amount * 100)
    except (ValueError, InvalidOperation):
        raise ValueError(f"{field}: expected non-negative money with at most two decimals") from None


def validate_candidates(part: dict, plan: dict, candidates: list[dict]) -> list[dict]:
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError(f"at most {MAX_CANDIDATES} fixed-lot candidates")
    po_map = {p["po_id"]: p for p in plan["orders"]}
    normalized, ids, pools = [], set(), {}
    start = day(plan["start_date"])
    for row in candidates:
        r = deepcopy(row)
        cid = r["candidate_id"]
        if not isinstance(cid, str) or not cid.strip() or cid != cid.strip() or cid in ids:
            raise ValueError("empty or duplicate candidate_id")
        ids.add(cid)
        if r["part_code"] != part["part_code"] or r["kind"] not in KINDS:
            raise ValueError("candidate has wrong SKU or invalid kind")
        if not isinstance(r["source"], str) or not r["source"].strip():
            raise ValueError("candidate source is required")
        for name in ["quantity", "minimum_quantity", "pack_multiple", "capacity", "pool_capacity"]:
            r[name] = quantity(r.get(name, 1 if name == "pack_multiple" else 0), name)
        if r["quantity"] == 0 or r["pack_multiple"] == 0:
            raise ValueError("quantity and pack_multiple must be positive")
        for name in ["qualified", "business_allowed"]:
            if not isinstance(r[name], bool):
                raise ValueError(f"{name} must be a boolean")
        d = day(r["earliest_available_date"], "earliest_available_date")
        if d < start:
            raise ValueError("candidate available date cannot precede planning start")
        r["earliest_available_date"] = d.isoformat()
        r["unit_cost_cents"] = money_cents(r["unit_cost"], "unit_cost")
        r["extra_cost_cents"] = money_cents(r["extra_cost"], "extra_cost")
        # Stable string IDs are separate from PO IDs; synthetic PO collisions rejected.
        if "MIT-" + cid in po_map:
            raise ValueError("candidate synthetic PO id collides with existing PO")
        pool = r.get("source_pool", "")
        if not isinstance(pool, str):
            raise ValueError("source_pool must be a string")
        if pool:
            if pool in pools and pools[pool] != r["pool_capacity"]:
                raise ValueError("shared source pool must have one consistent capacity")
            pools[pool] = r["pool_capacity"]
        reasons = []
        if not r["qualified"]:
            reasons.append("来源未通过资格核验")
        if not r["business_allowed"]:
            reasons.append("不满足业务限制")
        if r["quantity"] < r["minimum_quantity"]:
            reasons.append("低于最小批量")
        if r["quantity"] % r["pack_multiple"]:
            reasons.append("不满足包装倍数")
        if r["quantity"] > r["capacity"]:
            reasons.append("超过来源可供数量/产能")
        if pool and r["quantity"] > r["pool_capacity"]:
            reasons.append("超过共享库存池可用量")
        linked = r.get("linked_po_id", "")
        if r["kind"] == "EXPEDITE":
            po = po_map.get(linked)
            if (po is None or po["status"] != "CONFIRMED" or po["supplier"] != r["source"]
                    or po["part_code"] != r["part_code"] or po["open_quantity"] != r["quantity"]):
                reasons.append("加急必须关联同来源的确认 PO 全部未交量")
            elif d >= day(po["arrival_date"]):
                reasons.append("加急日期没有早于原到货日期")
            if r["unit_cost_cents"] != 0:
                raise ValueError("linked PO expedite unit_cost must be zero; committed purchase cost is excluded")
        elif linked:
            raise ValueError("only EXPEDITE may link an existing PO")
        r["eligible"] = not reasons
        r["constraint_reasons"] = reasons
        r["incremental_cost_cents"] = r["quantity"] * r["unit_cost_cents"] + r["extra_cost_cents"]
        normalized.append(r)
    return normalized


def _scenario(part: dict, plan: dict, baseline: dict, selected: list[dict]) -> dict:
    ids = [r["candidate_id"] for r in selected]
    reasons = [f"{r['candidate_id']}：{reason}" for r in selected for reason in r["constraint_reasons"]]
    linked = [r.get("linked_po_id") for r in selected if r["kind"] == "EXPEDITE"]
    if len(linked) != len(set(linked)):
        reasons.append("不能同时选择同一 PO 的多种加急措施")
    pools = {}
    for r in selected:
        pool = r.get("source_pool")
        if pool:
            pools[pool] = pools.get(pool, 0) + r["quantity"]
            if pools[pool] > r["pool_capacity"]:
                reasons.append(f"共享库存池 {pool} 的组合数量超限")
    cost = sum(r["incremental_cost_cents"] for r in selected)
    projection = baseline
    eligible = not reasons
    if eligible:
        orders = deepcopy(plan["orders"])
        for r in selected:
            if r["kind"] == "EXPEDITE":
                for po in orders:
                    if po["po_id"] == r["linked_po_id"]:
                        po["arrival_date"] = r["earliest_available_date"]
            else:
                orders.append({"po_id": "MIT-" + r["candidate_id"], "part_code": part["part_code"],
                               "supplier": r["source"], "open_quantity": r["quantity"],
                               "arrival_date": r["earliest_available_date"], "status": "CONFIRMED"})
        projection = simulate_inventory(part, plan["demands"], orders, plan["start_date"], plan["horizon_days"])
    first = baseline["first_shortage_date"]
    return {"scenario_id": " + ".join(ids) or "BASELINE", "candidate_ids": ids,
            "constraints_satisfied": eligible, "constraint_reasons": reasons,
            "fully_feasible": eligible and projection["total_unmet_demand"] == 0,
            "arrives_by_first_shortage": eligible and (not first or all(day(r["earliest_available_date"]) <= day(first) for r in selected)),
            "residual_unmet": projection["total_unmet_demand"],
            "reduction_unmet": baseline["total_unmet_demand"] - projection["total_unmet_demand"],
            "first_residual_shortage": projection["first_shortage_date"],
            "residual_shortage_dates": [d["date"] for d in projection["daily"] if d["unmet_demand"]],
            "incremental_cost_cents": cost, "incremental_cost": cost / 100,
            "projection": projection}


def compare_mitigations(part: dict, plan: dict, candidates: list[dict]) -> dict:
    baseline = simulate_inventory(part, plan["demands"], plan["orders"], plan["start_date"], plan["horizon_days"])
    validated = validate_candidates(part, plan, candidates)
    scenarios = [_scenario(part, plan, baseline, [])]
    # Invalid singles remain visible, but never become executable suggestions.
    scenarios.extend(_scenario(part, plan, baseline, [r]) for r in validated)
    eligible = [r for r in validated if r["eligible"]]
    for size in range(2, len(eligible) + 1):
        scenarios.extend(_scenario(part, plan, baseline, list(subset)) for subset in combinations(eligible, size))
    executable = [s for s in scenarios if s["constraints_satisfied"]]
    ranked = sorted(executable, key=lambda s: (s["residual_unmet"], s["incremental_cost_cents"], len(s["candidate_ids"]), s["scenario_id"]))
    best = ranked[0]
    full = best["fully_feasible"]
    message = (f"候选固定批量范围内，{best['scenario_id']} 满足预测期零数量短缺约束，建模增量成本 {best['incremental_cost']:.2f} 元。"
               if full else f"无完全可行方案。优先协调 {best['scenario_id']}，仍有 {best['residual_unmet']} 件未满足需求，首次残余缺料 {best['first_residual_shortage']}，建模增量成本 {best['incremental_cost']:.2f} 元。需人工重排生产或确认新增供给。")
    return {"algorithm": "bounded exhaustive enumeration of fixed-lot subsets (<=8 candidates)",
            "objective": "zero unmet over horizon; otherwise minimize residual units; then incremental cost",
            "cost_basis": "CNY incremental costs only; baseline committed purchase costs excluded; no shortage penalty or tax modeled",
            "candidates": validated, "scenarios": scenarios, "recommended": best,
            "has_fully_feasible": full, "recommendation_reason": message,
            "limitations": "conditional earliest dates and availability; fixed lots only; safety-stock restoration is not the zero-shortage constraint; no action executed"}


def build_mitigation_demo(result: dict) -> list[dict]:
    """Explicitly fictional snapshots. Dates/capacities are not supplier promises."""
    p, projection = result["selected_part"], result["inventory_projection"]
    start = day(projection["start_date"])
    first = day(projection["first_shortage_date"]) if projection["first_shortage_date"] else start + timedelta(days=3)
    early = max(start, first - timedelta(days=1))
    need = max(20, projection["total_unmet_demand"])
    half = max(1, (need + 1) // 2)
    common = {"part_code": p["part_code"], "qualified": True, "business_allowed": True,
              "minimum_quantity": 1, "pack_multiple": 1, "source_pool": "", "pool_capacity": 0,
              "linked_po_id": ""}
    rows = [
        {**common, "candidate_id": "SIM-BACKUP", "kind": "BACKUP", "source": "Fictional Qualified Backup",
         "quantity": half, "capacity": half, "earliest_available_date": early.isoformat(), "unit_cost": 55, "extra_cost": 200},
        {**common, "candidate_id": "SIM-TRANSFER", "kind": "TRANSFER", "source": "Fictional Plant B Free Stock",
         "quantity": half, "capacity": half, "earliest_available_date": early.isoformat(), "unit_cost": 12, "extra_cost": 100,
         "source_pool": "SIM-PLANT-B-" + p["part_code"], "pool_capacity": half},
        {**common, "candidate_id": "SIM-LATE", "kind": "BACKUP", "source": "Fictional Low-cost Late Supplier",
         "quantity": need, "capacity": need, "earliest_available_date": (first + timedelta(days=2)).isoformat(), "unit_cost": 1, "extra_cost": 0},
    ]
    future = [o for o in result["planning_input"]["orders"] if o["status"] == "CONFIRMED" and day(o["arrival_date"]) > early]
    if future:
        po = min(future, key=lambda o: day(o["arrival_date"]))
        rows.insert(0, {**common, "candidate_id": "SIM-EXPEDITE", "kind": "EXPEDITE", "source": po["supplier"],
                        "quantity": po["open_quantity"], "capacity": po["open_quantity"], "linked_po_id": po["po_id"],
                        "earliest_available_date": early.isoformat(), "unit_cost": 0, "extra_cost": 6000})
    else:
        # A missing original PO cannot be expedited; show that constraint explicitly.
        rows.insert(0, {**common, "candidate_id": "SIM-EXPEDITE", "kind": "EXPEDITE", "source": p["supplier"],
                        "quantity": need, "capacity": need, "earliest_available_date": early.isoformat(),
                        "unit_cost": 0, "extra_cost": 6000})
    return rows


def mitigation_report(comparison: dict) -> str:
    rows = ["供应缓解方案比较（虚构，未执行）：", comparison["recommendation_reason"],
            "算法：最多八个固定批量候选的组合穷举，仅在输入候选范围内比较。"]
    for s in comparison["scenarios"]:
        rows.append(f"{s['scenario_id']}：约束{'满足' if s['constraints_satisfied'] else '不满足'}；累计残余 {s['residual_unmet']} 件；残余日期 {', '.join(s['residual_shortage_dates']) or '无'}；增量成本 {s['incremental_cost']:.2f} 元。")
    rows.append("成本不含基准已承诺采购款、税费和停线损失；零数量短缺不代表恢复安全库存或真实到货承诺。")
    return "\n".join(rows)
