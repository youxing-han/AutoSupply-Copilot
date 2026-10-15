"""Four-node LangGraph workflow for AutoSupply Copilot.

Inventory calculations, supplier-risk classification, and replenishment
decisions are deterministic Python logic. Ollama is optional and is used only
to turn the already-calculated structured result into a management summary.
"""

from __future__ import annotations

import json
import math
import re
from numbers import Real
from typing import Any, Literal, TypedDict

from langchain_ollama import OllamaLLM
from langgraph.graph import END, StateGraph
from runtime_mode import is_public_demo, require_local_llm, PUBLIC_LLM_MESSAGE

from calculations import InventoryMetrics, calculate_inventory_metrics
from inventory_planning import (
    simulate_inventory, evaluate_dynamic_risk, dynamic_decision, dynamic_report,
)
from mitigation import compare_mitigations, mitigation_report


TraceStatus = Literal["SUCCESS", "FAILED", "SKIPPED"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


class ExecutionTraceEntry(TypedDict):
    node_name: str
    execution_status: TraceStatus
    input_summary: str
    output_summary: str


class SupplierRiskResult(TypedDict):
    risk_level: RiskLevel
    reasons: list[str]
    mitigating_factors: list[str]


class ReplenishmentDecision(TypedDict):
    recommended_action: str
    supporting_actions: list[str]
    recommended_order_qty: int
    decision_reasons: list[str]
    caveats: list[str]


class SupplyChainState(TypedDict, total=False):
    mitigation_candidates: list[dict[str, Any]]
    mitigation_comparison: dict[str, Any]
    planning_input: dict[str, Any]
    inventory_projection: dict[str, Any]
    scenario: str
    selected_part: dict[str, Any]
    input_params: dict[str, Any]
    inventory_metrics: InventoryMetrics
    supplier_risk: SupplierRiskResult
    replenishment_decision: ReplenishmentDecision
    management_report: str
    report_source: str
    use_llm_report: bool
    execution_trace: list[ExecutionTraceEntry]
    workflow_error: str
    llm_error: str


SEVERE_SUPPLIER_STATUSES = {"DISRUPTED", "STOPPED", "UNAVAILABLE"}
DYNAMIC_INPUT_VERSION = 2
WARNING_SUPPLIER_STATUSES = {"DELAYED", "AT_RISK"}

REPORT_ASSUMPTIONS = [
    "Daily usage is assumed stable over the short planning horizon.",
    (
        "Current stock approximates inventory position because in-transit stock, "
        "open purchase orders, reservations, and backorders are not provided."
    ),
    "Safety days are a fictional policy parameter in the simulated data.",
    (
        "Stockout gap is a potential supply-coverage gap, not confirmed production "
        "downtime."
    ),
    (
        "Backup-supplier availability does not confirm lead time, capacity, stock, "
        "qualification, or delivery feasibility."
    ),
]

REPORT_ASSUMPTIONS_ZH = [
    "短期计划周期内，假设日均需求保持稳定。",
    (
        "由于未提供在途库存、未结采购订单、预留量和欠交量，当前库存被简化为"
        "库存位置。"
    ),
    "安全天数（Safety Days）来自模拟策略设定，并非基于历史波动统计估计。",
    "库存覆盖缺口是潜在供应缺口，不等同于已经发生的停产天数。",
    (
        "备用供应商可用仅表示可以评估，不代表其交期、产能、库存、资质或交付"
        "可行性已经得到确认。"
    ),
]

SCENARIO_LABELS_ZH = {
    "Normal Supply": "正常供应",
    "Supplier Delay": "供应商延迟",
    "Critical Shortage": "关键短缺",
}
RISK_LEVEL_LABELS_ZH = {
    "LOW": "低风险",
    "MEDIUM": "中风险",
    "HIGH": "高风险",
}
ACTION_LABELS_ZH = {
    "No Action": "无需行动",
    "Normal Reorder": "常规补货",
    "Emergency Reorder": "紧急补货",
}
SUPPORTING_ACTION_LABELS_ZH = {
    "Expedite Delivery": "加急交付",
    "Evaluate Backup Supplier": "评估备用供应商",
    "Activate Backup Supplier": "启用备用供应商",
    "Internal Transfer": "内部调拨",
}
SUPPLIER_STATUS_LABELS_ZH = {
    "NORMAL": "正常",
    "DELAYED": "延迟",
    "AT_RISK": "存在风险",
    "DISRUPTED": "供应中断",
    "STOPPED": "已停止",
    "UNAVAILABLE": "不可用",
    "UNKNOWN": "未知",
}


def risk_level_label_zh(level: str) -> str:
    """Return a bilingual display label without changing the state enum."""

    return f"{RISK_LEVEL_LABELS_ZH.get(level, level)}（{level}）"


def action_label_zh(action: str) -> str:
    """Return a bilingual display label for a deterministic main action."""

    return f"{ACTION_LABELS_ZH.get(action, action)}（{action}）"


def supporting_action_label_zh(action: str) -> str:
    """Return a bilingual display label for a deterministic supporting action."""

    return f"{SUPPORTING_ACTION_LABELS_ZH.get(action, action)}（{action}）"


def translate_risk_reason_zh(reason: str) -> str:
    """Translate known risk-rule explanations for presentation only."""

    gap_match = re.fullmatch(
        r"Potential supply-coverage gap is (.+) days\.", reason
    )
    if gap_match:
        return f"存在 {gap_match.group(1)} 天潜在供应覆盖缺口。"

    status_match = re.fullmatch(
        r"Primary supplier status is (.+), indicating interruption\.", reason
    )
    if status_match:
        status = status_match.group(1)
        return (
            f"主供应商状态为 {SUPPLIER_STATUS_LABELS_ZH.get(status, status)}"
            f"（{status}），表明供应已中断。"
        )

    critical_status_match = re.fullmatch(
        r"HIGH criticality combined with supplier status (.+) raises the risk "
        r"priority\.",
        reason,
    )
    if critical_status_match:
        status = critical_status_match.group(1)
        return (
            "高关键度零部件叠加供应商状态 "
            f"{SUPPLIER_STATUS_LABELS_ZH.get(status, status)}（{status}），提高了风险优先级。"
        )

    exact = {
        "HIGH criticality part is below its calculated reorder point.": (
            "高关键度零部件的当前库存低于计算得到的再订货点。"
        ),
        (
            "Current stock is below the calculated reorder point, but it still "
            "covers the stated lead time."
        ): "当前库存低于再订货点，但仍能覆盖所设定的供应商交期。",
        (
            "Stock covers the stated lead time, inventory is not below the "
            "reorder point, and no supplier warning is active."
        ): "库存可覆盖当前交期，且未低于再订货点，供应商也没有有效预警。",
    }
    if reason in exact:
        return exact[reason]

    warning_match = re.fullmatch(
        r"Supplier status is (.+), but no coverage gap is currently calculated\.",
        reason,
    )
    if warning_match:
        status = warning_match.group(1)
        return (
            f"供应商状态为 {SUPPLIER_STATUS_LABELS_ZH.get(status, status)}"
            f"（{status}），但当前未计算出库存覆盖缺口。"
        )
    return reason


def translate_decision_reason_zh(reason: str) -> str:
    """Translate known decision-rule explanations for presentation only."""

    order_match = re.fullmatch(
        r"Order (.+) units to reach the simulated target inventory of (.+) units\.",
        reason,
    )
    if order_match:
        return (
            f"建议订购 {order_match.group(1)} 件，使库存恢复至模拟目标库存 "
            f"{order_match.group(2)} 件。"
        )

    gap_match = re.fullmatch(
        r"Placing the calculated order does not by itself remove the (.+)-day "
        r"potential coverage gap before arrival\.",
        reason,
    )
    if gap_match:
        return (
            "仅按建议数量下单，不能自动消除到货前 "
            f"{gap_match.group(1)} 天的潜在供应覆盖缺口。"
        )

    exact = {
        "Current stock already meets the simulated target-inventory policy.": (
            "当前库存已满足模拟目标库存策略。"
        ),
        (
            "The recorded backup supplier requires feasibility, qualification, "
            "capacity, stock, lead-time, and cost checks before activation."
        ): (
            "启用已记录的备用供应商前，仍需核验可行性、资质、产能、库存、交期和成本。"
        ),
    }
    return exact.get(reason, reason)


def translate_mitigating_factor_zh(factor: str) -> str:
    """Translate known mitigation notes without changing risk evaluation."""

    available_match = re.fullmatch(
        r"(.+) is marked available for evaluation; lead time, stock, capacity, "
        r"qualification, and delivery feasibility are not provided\.",
        factor,
    )
    if available_match:
        return (
            f"{available_match.group(1)} 已标记为可评估；其交期、库存、产能、资质和"
            "交付可行性尚未提供。"
        )
    if factor == "No available backup supplier is recorded.":
        return "当前未记录可用的备用供应商。"
    return factor


def _trace_entry(
    node_name: str,
    status: TraceStatus,
    input_summary: str,
    output_summary: str,
) -> ExecutionTraceEntry:
    return {
        "node_name": node_name,
        "execution_status": status,
        "input_summary": input_summary,
        "output_summary": output_summary,
    }


def _append_trace(
    state: SupplyChainState,
    node_name: str,
    status: TraceStatus,
    input_summary: str,
    output_summary: str,
) -> list[ExecutionTraceEntry]:
    return [
        *state.get("execution_trace", []),
        _trace_entry(node_name, status, input_summary, output_summary),
    ]


def _skip_after_error(
    state: SupplyChainState, node_name: str, input_summary: str
) -> dict[str, Any] | None:
    error = state.get("workflow_error")
    if not error:
        return None
    return {
        "execution_trace": _append_trace(
            state,
            node_name,
            "SKIPPED",
            input_summary,
            f"Skipped because an earlier node failed: {error}",
        )
    }


def _format_number(value: Real) -> str:
    if value is None:
        return '不适用（逐日计划模型）'
    numeric = float(value)
    if math.isinf(numeric):
        return "infinite"
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.2f}".rstrip("0").rstrip(".")


def create_initial_state(
    scenario: str,
    selected_part: dict[str, Any],
    use_llm_report: bool = False,
) -> SupplyChainState:
    """Create a complete initial state for one selected simulated part."""

    input_fields = (
        "part_code",
        "part_name",
        "supplier",
        "current_stock",
        "daily_usage",
        "lead_time_days",
        "supplier_status",
        "criticality",
        "backup_supplier",
        "backup_supplier_available",
        "destination_line",
        "unit_cost",
        "safety_days",
    )
    return {
        "scenario": scenario,
        "selected_part": dict(selected_part),
        "input_params": {
            field: selected_part.get(field) for field in input_fields
        },
        "inventory_metrics": {},
        "supplier_risk": {},
        "replenishment_decision": {},
        "management_report": "",
        "report_source": "",
        "use_llm_report": use_llm_report,
        "execution_trace": [],
        "workflow_error": "",
        "llm_error": "",
    }


def inventory_monitor_agent(state: SupplyChainState) -> dict[str, Any]:
    """Calculate inventory metrics by reusing ``calculations.py``."""

    part = state["selected_part"]
    input_summary = (
        f"{part.get('part_code')} stock={part.get('current_stock')}, "
        f"daily_usage={part.get('daily_usage')}, "
        f"lead_time={part.get('lead_time_days')}, "
        f"safety_days={part.get('safety_days')}"
    )
    try:
        projection = None
        if state.get("planning_input"):
            plan = state["planning_input"]
            projection = simulate_inventory(
                part, plan["demands"], plan["orders"],
                plan["start_date"], plan["horizon_days"],
            )
            mean = sum(r['quantity'] for r in plan['demands']) / plan['horizon_days']
            metrics = dict(days_of_stock=part['current_stock']/mean if mean else math.inf,
                           safety_stock=part.get('safety_stock', mean*part['safety_days']),
                           stockout_gap=None, reorder_point=None, target_coverage_days=None,
                           target_stock=None, recommended_order_qty=None)
        else:
            metrics = calculate_inventory_metrics(
                current_stock=part['current_stock'], daily_usage=part['daily_usage'],
                lead_time_days=part['lead_time_days'], safety_days=part['safety_days'])
    except (KeyError, TypeError, ValueError) as exc:
        error = f"Inventory Monitor failed: {exc}"
        return {
            "workflow_error": error,
            "execution_trace": _append_trace(
                state, "Inventory Monitor", "FAILED", input_summary, error
            ),
        }

    output_summary = (
        f"days_of_stock={_format_number(metrics['days_of_stock'])}, "
        f"stockout_gap={_format_number(metrics['stockout_gap'])}, "
        f"reorder_point={_format_number(metrics['reorder_point'])}, "
        f"recommended_order_qty={metrics['recommended_order_qty']}"
    )
    if projection is not None:
        output_summary += f"; time-phased-v2 first_shortage={projection['first_shortage_date']}, unmet={projection['total_unmet_demand']}"
    return {
        **({"inventory_projection": projection} if projection is not None else {}),
        "inventory_metrics": metrics,
        "execution_trace": _append_trace(
            state, "Inventory Monitor", "SUCCESS", input_summary, output_summary
        ),
    }


def evaluate_supplier_risk(
    part: dict[str, Any], metrics: InventoryMetrics
) -> SupplierRiskResult:
    """Classify supplier risk with explicit HIGH-first priority rules.

    Priority avoids conflicting outcomes:

    * HIGH: a positive coverage gap, a severe supplier interruption, or a HIGH
      criticality part that is either delayed/at risk or below reorder point.
    * MEDIUM: only when no HIGH rule matched, stock is below reorder point or
      supplier status is delayed/at risk without a coverage gap.
    * LOW: no HIGH or MEDIUM rule matched.

    Backup-supplier availability is reported as a mitigating factor but never
    automatically lowers risk because capacity and lead-time evidence is absent.
    """

    supplier_status = str(part.get("supplier_status", "UNKNOWN")).upper()
    criticality = str(part.get("criticality", "UNKNOWN")).upper()
    current_stock = float(part["current_stock"])
    gap = float(metrics["stockout_gap"])
    reorder_point = float(metrics["reorder_point"])
    below_reorder_point = current_stock < reorder_point

    high_reasons: list[str] = []
    if gap > 0:
        high_reasons.append(
            f"Potential supply-coverage gap is {_format_number(gap)} days."
        )
    if supplier_status in SEVERE_SUPPLIER_STATUSES:
        high_reasons.append(
            f"Primary supplier status is {supplier_status}, indicating interruption."
        )
    if criticality == "HIGH" and supplier_status in WARNING_SUPPLIER_STATUSES:
        high_reasons.append(
            f"HIGH criticality combined with supplier status {supplier_status} "
            "raises the risk priority."
        )
    if criticality == "HIGH" and below_reorder_point:
        high_reasons.append(
            "HIGH criticality part is below its calculated reorder point."
        )

    if high_reasons:
        risk_level: RiskLevel = "HIGH"
        reasons = high_reasons
    else:
        medium_reasons: list[str] = []
        if below_reorder_point:
            medium_reasons.append(
                "Current stock is below the calculated reorder point, but it still "
                "covers the stated lead time."
            )
        if supplier_status in WARNING_SUPPLIER_STATUSES:
            medium_reasons.append(
                f"Supplier status is {supplier_status}, but no coverage gap is "
                "currently calculated."
            )

        if medium_reasons:
            risk_level = "MEDIUM"
            reasons = medium_reasons
        else:
            risk_level = "LOW"
            reasons = [
                "Stock covers the stated lead time, inventory is not below the "
                "reorder point, and no supplier warning is active."
            ]

    mitigating_factors: list[str] = []
    if bool(part.get("backup_supplier_available")):
        backup_name = part.get("backup_supplier") or "an unnamed backup supplier"
        mitigating_factors.append(
            f"{backup_name} is marked available for evaluation; lead time, stock, "
            "capacity, qualification, and delivery feasibility are not provided."
        )
    elif risk_level != "LOW":
        mitigating_factors.append("No available backup supplier is recorded.")

    return {
        "risk_level": risk_level,
        "reasons": reasons,
        "mitigating_factors": mitigating_factors,
    }


def supplier_risk_agent(state: SupplyChainState) -> dict[str, Any]:
    """Evaluate inventory and supplier factors without using an LLM."""

    skipped = _skip_after_error(
        state, "Supplier Risk", "Selected part and Inventory Monitor metrics"
    )
    if skipped is not None:
        return skipped

    part = state["selected_part"]
    metrics = state["inventory_metrics"]
    input_summary = (
        f"days_of_stock={_format_number(metrics['days_of_stock'])}, "
        f"lead_time={part['lead_time_days']}, "
        f"stockout_gap={_format_number(metrics['stockout_gap'])}, "
        f"supplier_status={part['supplier_status']}, "
        f"criticality={part['criticality']}, "
        f"backup_available={bool(part.get('backup_supplier_available'))}"
    )
    try:
        risk = (evaluate_dynamic_risk(part, state["inventory_projection"])
                if state.get("inventory_projection") else evaluate_supplier_risk(part, metrics))
    except (KeyError, TypeError, ValueError) as exc:
        error = f"Supplier Risk failed: {exc}"
        return {
            "workflow_error": error,
            "execution_trace": _append_trace(
                state, "Supplier Risk", "FAILED", input_summary, error
            ),
        }

    output_summary = (
        f"risk_level={risk['risk_level']}; reasons={' | '.join(risk['reasons'])}"
    )
    return {
        "supplier_risk": risk,
        "execution_trace": _append_trace(
            state, "Supplier Risk", "SUCCESS", input_summary, output_summary
        ),
    }


def make_replenishment_decision(
    part: dict[str, Any],
    metrics: InventoryMetrics,
    risk: SupplierRiskResult,
) -> ReplenishmentDecision:
    """Choose actions while preserving the calculated order quantity."""

    risk_level = risk["risk_level"]
    gap = float(metrics["stockout_gap"])
    quantity = int(metrics["recommended_order_qty"])
    supplier_status = str(part.get("supplier_status", "UNKNOWN")).upper()

    if risk_level == "HIGH" or gap > 0:
        recommended_action = "Emergency Reorder"
    elif quantity > 0:
        recommended_action = "Normal Reorder"
    else:
        recommended_action = "No Action"

    decision_reasons: list[str] = []
    if quantity > 0:
        decision_reasons.append(
            f"Order {quantity} units to reach the simulated target inventory of "
            f"{_format_number(metrics['target_stock'])} units."
        )
    else:
        decision_reasons.append(
            "Current stock already meets the simulated target-inventory policy."
        )

    supporting_actions: list[str] = []
    if gap > 0:
        supporting_actions.append("Expedite Delivery")
        decision_reasons.append(
            f"Placing the calculated order does not by itself remove the "
            f"{_format_number(gap)}-day potential coverage gap before arrival."
        )

    if bool(part.get("backup_supplier_available")) and (
        risk_level == "HIGH"
        or supplier_status in SEVERE_SUPPLIER_STATUSES
        or supplier_status in WARNING_SUPPLIER_STATUSES
    ):
        supporting_actions.append("Evaluate Backup Supplier")
        decision_reasons.append(
            "The recorded backup supplier requires feasibility, qualification, "
            "capacity, stock, lead-time, and cost checks before activation."
        )

    caveats = [
        (
            "Recommended order quantity restores the simulated target inventory; "
            "it is not proof that a pre-arrival coverage gap can be avoided."
        ),
        (
            "Internal Transfer is not recommended because no source-location stock, "
            "transfer lead time, or logistics-feasibility data is available."
        ),
    ]

    return {
        "recommended_action": recommended_action,
        "supporting_actions": supporting_actions,
        "recommended_order_qty": quantity,
        "decision_reasons": decision_reasons,
        "caveats": caveats,
    }


def replenishment_agent(state: SupplyChainState) -> dict[str, Any]:
    """Generate a deterministic replenishment decision."""

    skipped = _skip_after_error(
        state,
        "Replenishment Decision",
        "Inventory metrics and supplier-risk result",
    )
    if skipped is not None:
        return skipped

    part = state["selected_part"]
    metrics = state["inventory_metrics"]
    risk = state["supplier_risk"]
    input_summary = (
        f"risk_level={risk['risk_level']}, "
        f"stockout_gap={_format_number(metrics['stockout_gap'])}, "
        f"calculated_order_qty={metrics['recommended_order_qty']}, "
        f"backup_available={bool(part.get('backup_supplier_available'))}"
    )
    try:
        decision = (dynamic_decision(part, state["inventory_projection"])
                    if state.get("inventory_projection") else make_replenishment_decision(part, metrics, risk))
        comparison = None
        if "mitigation_candidates" in state:
            if not state.get("inventory_projection"):
                raise ValueError("mitigation comparison requires time-phased planning data")
            comparison = compare_mitigations(part, state["planning_input"], state["mitigation_candidates"])
    except (KeyError, TypeError, ValueError) as exc:
        error = f"Replenishment Decision failed: {exc}"
        return {
            "workflow_error": error,
            "execution_trace": _append_trace(
                state, "Replenishment Decision", "FAILED", input_summary, error
            ),
        }

    output_summary = (
        f"action={decision['recommended_action']}, "
        f"supporting_actions={decision['supporting_actions']}, "
        f"recommended_order_qty={decision['recommended_order_qty']}"
    )
    if comparison is not None:
        output_summary += f"; mitigation={comparison['recommended']['scenario_id']}, residual={comparison['recommended']['residual_unmet']}, incremental_cost={comparison['recommended']['incremental_cost']}"
    return {
        **({"mitigation_comparison": comparison} if comparison is not None else {}),
        "replenishment_decision": decision,
        "execution_trace": _append_trace(
            state,
            "Replenishment Decision",
            "SUCCESS",
            input_summary,
            output_summary,
        ),
    }


def build_template_report(state: SupplyChainState) -> str:
    """Build a complete Chinese management report without an LLM."""

    if state.get("inventory_projection"):
        report = dynamic_report(state)
        if state.get("mitigation_comparison"):
            report += "\n\n" + mitigation_report(state["mitigation_comparison"])
        return report
    part = state["selected_part"]
    metrics = state["inventory_metrics"]
    risk = state["supplier_risk"]
    decision = state["replenishment_decision"]
    supporting = "、".join(
        supporting_action_label_zh(item)
        for item in decision["supporting_actions"]
    ) or "无"
    reasons = "".join(translate_risk_reason_zh(item) for item in risk["reasons"])
    mitigations = "".join(
        translate_mitigating_factor_zh(item)
        for item in risk["mitigating_factors"]
    ) or "暂无额外缓解因素。"
    decision_reasons = "".join(
        translate_decision_reason_zh(item)
        for item in decision["decision_reasons"]
    )
    assumptions = "".join(REPORT_ASSUMPTIONS_ZH)
    if math.isinf(float(metrics["days_of_stock"])):
        coverage_description = "因日均需求为零，无法表示为有限天数"
    else:
        coverage_description = f"为 {_format_number(metrics['days_of_stock'])} 天"

    scenario = state["scenario"]
    scenario_label = SCENARIO_LABELS_ZH.get(scenario, scenario)

    return (
        f"管理层分析报告｜{scenario_label}（{scenario}）\n"
        f"零部件：{part['part_code']} {part['part_name']}，用于"
        f"{part['destination_line']}；主供应商为 {part['supplier']}。\n"
        f"当前状态：库存 {_format_number(part['current_stock'])} 件，日均需求 "
        f"{_format_number(part['daily_usage'])} 件，供应商交期 "
        f"{_format_number(part['lead_time_days'])} 天，库存覆盖天数{coverage_description}；"
        f"潜在库存覆盖缺口为 {_format_number(metrics['stockout_gap'])} 天。\n"
        f"风险判断：{risk_level_label_zh(risk['risk_level'])}。依据：{reasons}"
        f"缓解信息：{mitigations}\n"
        f"补货建议：{action_label_zh(decision['recommended_action'])}；辅助措施："
        f"{supporting}；建议订货量为 {decision['recommended_order_qty']} 件。\n"
        f"决策说明：{decision_reasons}\n"
        f"业务假设：{assumptions}"
    )


def _create_ollama_llm() -> OllamaLLM:
    """Create a CPU-only local client that ignores machine-level proxies."""

    require_local_llm()
    return OllamaLLM(
        model="llama3.2",
        temperature=0,
        num_gpu=0,
        base_url="http://127.0.0.1:11434",
        client_kwargs={"trust_env": False, "timeout": 45.0},
    )


def _validate_llm_commentary(
    commentary: str, risk_level: str, recommended_action: str
) -> None:
    """Keep optional prose away from all deterministic facts and quantities."""

    if re.search(r"\d", commentary):
        raise ValueError("LLM commentary contains a numeric value")
    risk_label = risk_level_label_zh(risk_level)
    action_label = action_label_zh(recommended_action)
    if risk_label not in commentary or action_label not in commentary:
        raise ValueError("LLM commentary omitted the verified risk or action")

    forbidden_topics = (
        "stock",
        "inventory",
        "lead time",
        "coverage",
        "gap",
        "quantity",
        "unit",
        "day",
        "库存",
        "交期",
        "覆盖",
        "缺口",
        "数量",
        "件",
        "天",
    )
    lowered = commentary.lower()
    if any(topic in lowered for topic in forbidden_topics):
        raise ValueError("LLM commentary attempted to restate a verified metric")


def _generate_llm_report(state: SupplyChainState) -> str:
    verified_risk = risk_level_label_zh(state["supplier_risk"]["risk_level"])
    verified_action = action_label_zh(
        state["replenishment_decision"]["recommended_action"]
    )
    payload = {
        "scenario": state["scenario"],
        "part_name": state["selected_part"]["part_name"],
        "supplier_status": state["selected_part"]["supplier_status"],
        "criticality": state["selected_part"]["criticality"],
        "risk_level": verified_risk,
        "recommended_action": verified_action,
        "supporting_actions": [
            supporting_action_label_zh(item)
            for item in state["replenishment_decision"]["supporting_actions"]
        ],
    }
    prompt = (
        "请根据以下结构化事实，用简体中文撰写一段不超过两句的管理层定性说明。"
        f"第一句必须逐字包含：风险等级为{verified_risk}，建议主要行动为"
        f"{verified_action}。"
        "不要使用任何数字；不要讨论或复述库存、交期、覆盖、缺口、数量、件数或"
        "天数，这些经过校验的数据将由应用单独展示。不得断言备用供应商已经可行或"
        "能够解决问题。只返回正文段落，不要解释任务。\n\n"
        + json.dumps(payload, ensure_ascii=False, allow_nan=False)
    )
    commentary = str(_create_ollama_llm().invoke(prompt)).strip()
    if not commentary:
        raise ValueError("Ollama returned empty commentary")
    _validate_llm_commentary(
        commentary,
        state["supplier_risk"]["risk_level"],
        state["replenishment_decision"]["recommended_action"],
    )
    return (
        build_template_report(state)
        + "\n\nLLM 管理层补充："
        + commentary
    )


def management_report_agent(state: SupplyChainState) -> dict[str, Any]:
    """Create a template report, optionally enhancing it through local Ollama."""

    skipped = _skip_after_error(
        state,
        "Management Report",
        "Structured inventory, risk, and replenishment results",
    )
    if skipped is not None:
        return skipped

    input_summary = (
        f"risk_level={state['supplier_risk']['risk_level']}, "
        f"action={state['replenishment_decision']['recommended_action']}, "
        f"order_qty={state['replenishment_decision']['recommended_order_qty']}, "
        f"llm_requested={bool(state.get('use_llm_report'))}"
    )
    template_report = build_template_report(state)
    report = template_report
    report_source = "template"
    llm_error = ""

    if state.get("use_llm_report") and is_public_demo():
        llm_error = PUBLIC_LLM_MESSAGE
        report_source = "template_fallback"
    elif state.get("use_llm_report"):
        try:
            report = _generate_llm_report(state)
            report_source = "llm"
        except Exception as exc:  # Fallback must also handle connection failures.
            llm_error = f"{type(exc).__name__}: {exc}"
            report_source = "template_fallback"

    output_summary = (
        f"report_source={report_source}, report_length={len(report)} characters"
    )
    if llm_error:
        output_summary += f", llm_error={llm_error}"

    return {
        "management_report": report,
        "report_source": report_source,
        "llm_error": llm_error,
        "execution_trace": _append_trace(
            state,
            "Management Report",
            "SUCCESS",
            input_summary,
            output_summary,
        ),
    }


def build_supply_chain_graph():
    """Compile the fixed four-node AutoSupply LangGraph workflow."""

    graph = StateGraph(SupplyChainState)
    graph.add_node("inventory_monitor", inventory_monitor_agent)
    graph.add_node("supplier_risk", supplier_risk_agent)
    graph.add_node("replenishment_decision", replenishment_agent)
    graph.add_node("management_report", management_report_agent)

    graph.set_entry_point("inventory_monitor")
    graph.add_edge("inventory_monitor", "supplier_risk")
    graph.add_edge("supplier_risk", "replenishment_decision")
    graph.add_edge("replenishment_decision", "management_report")
    graph.add_edge("management_report", END)

    return graph.compile()
