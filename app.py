"""紧凑的 AutoSupply Copilot Streamlit Dashboard。"""

from __future__ import annotations

import math
import json
import hashlib
import html
import importlib
import sys
from pathlib import Path
from typing import Any
from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent
AGENT_DIR = PROJECT_ROOT / "agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import workflow_runtime
from runtime_mode import is_public_demo, PUBLIC_LLM_MESSAGE

runtime_changed=getattr(workflow_runtime, "WORKFLOW_RUNTIME_VERSION", None) != 6
if runtime_changed:
    importlib.reload(workflow_runtime)
workflow_runtime.current_workflow_module()
for module_name,version_name,expected in (('localized_ui','LOCALIZED_UI_VERSION',5),('demo_data','DEMO_DATA_VERSION',2),('batch_analysis','BATCH_DATA_VERSION',2),('assistant','ASSISTANT_VERSION',4),('mitigation_ui','MITIGATION_UI_VERSION',3),('portfolio_ui','PORTFOLIO_UI_VERSION',5),('website_ui','SITE_UI_VERSION',14),('planning_workspace','WORKSPACE_VERSION',2),('planning_demand_ui','DEMAND_UI_VERSION',2),('planning_site','PLANNING_SITE_VERSION',12)):
    presentation_module=importlib.import_module(module_name)
    if getattr(presentation_module,version_name,None)!=expected or (runtime_changed and module_name=='mitigation_ui'):
        importlib.reload(presentation_module)

from agents import (
    ACTION_LABELS_ZH,
    RISK_LEVEL_LABELS_ZH,
    SCENARIO_LABELS_ZH,
    SUPPLIER_STATUS_LABELS_ZH,
    action_label_zh,
    build_supply_chain_graph,
    create_initial_state,
    risk_level_label_zh,
    supporting_action_label_zh,
    translate_decision_reason_zh,
    translate_mitigating_factor_zh,
    translate_risk_reason_zh,
)
from assistant import (
    AssistantUnavailableError,
    answer_supply_chain_question,
    build_assistant_context,
)
from batch_analysis import (
    analyze_batch,
    batch_results_csv_bytes,
    build_batch_template,
    read_batch_file,
    template_csv_bytes,
    template_xlsx_bytes,
    validate_batch_dataframe,
)
from report_pdf import build_pdf_report
from localized_ui import zh_text
render_planning_mode = workflow_runtime.current_planning_ui().render_planning_mode
from supply_data import (
    CRITICAL_SHORTAGE,
    DEFAULT_SCENARIO_PART_CODES,
    NORMAL_SUPPLY,
    SCENARIO_NAMES,
    SUPPLIER_DELAY,
    generate_automotive_supply_data,
    get_scenario_part,
)


SUPPLIER_STATUS_OPTIONS = (
    "NORMAL",
    "DELAYED",
    "AT_RISK",
    "DISRUPTED",
    "STOPPED",
    "UNAVAILABLE",
)
CRITICALITY_OPTIONS = ("LOW", "MEDIUM", "HIGH")
CRITICALITY_LABELS_ZH = {"LOW": "低", "MEDIUM": "中", "HIGH": "高"}
PART_NAME_LABELS_ZH = {
    "Sensor": "传感器",
    "Bearing": "轴承",
    "Controller": "控制器",
    "Brake Module": "制动模块",
    "Battery Component": "电池组件",
}
SCENARIO_DESCRIPTIONS_ZH = {
    "Normal Supply": "供应正常，库存可以覆盖当前交期。",
    "Supplier Delay": "传感器交期由 7 天延长至 14 天，形成潜在覆盖缺口。",
    "Critical Shortage": "关键制动模块库存不足，主供应商中断，备用供应商仅可评估。",
}
NODE_LABELS_ZH = {
    "Inventory Monitor": "库存监控",
    "Supplier Risk": "供应商风险",
    "Replenishment Decision": "补货决策",
    "Management Report": "管理报告",
}
STATUS_LABELS_ZH = {
    "SUCCESS": "成功",
    "FAILED": "失败",
    "SKIPPED": "已跳过",
}
RISK_COLORS = {"LOW": "#23836B", "MEDIUM": "#C88B35", "HIGH": "#C94A4A"}
SINGLE_ANALYSIS_MODE = "单零部件情景分析"
BATCH_ANALYSIS_MODE = "Excel / CSV 批量风险分析"
PLANNING_ANALYSIS_MODE = "动态物料计划"


def _risk_color(risk_level: str) -> str:
    """Return the fixed dashboard color for one business risk level."""

    return RISK_COLORS.get(risk_level, "#788482")


def _safe(value: Any) -> str:
    return html.escape(str(value))


def _load_input_defaults(scenario: str, part_code: str) -> None:
    part = get_scenario_part(scenario, part_code)
    st.session_state["current_inventory"] = float(part["current_stock"])
    st.session_state["daily_usage"] = float(part["daily_usage"])
    st.session_state["supplier"] = str(part["supplier"])
    st.session_state["lead_time_days"] = float(part["lead_time_days"])
    st.session_state["supplier_status"] = str(part["supplier_status"])
    st.session_state["criticality"] = str(part["criticality"])
    st.session_state["backup_supplier_available"] = bool(
        part["backup_supplier_available"]
    )
    st.session_state["safety_days"] = float(part["safety_days"])


def _initialize_session_state() -> None:
    # Streamlit owns this widget value after the first render. setdefault keeps
    # the selected mode across reruns instead of overwriting a user's choice.
    st.session_state.setdefault("analysis_mode", SINGLE_ANALYSIS_MODE)
    if "scenario_preset" not in st.session_state:
        st.session_state["scenario_preset"] = NORMAL_SUPPLY
        st.session_state["part_sku"] = DEFAULT_SCENARIO_PART_CODES[NORMAL_SUPPLY]
        if "current_inventory" not in st.session_state:
            _load_input_defaults(NORMAL_SUPPLY, st.session_state["part_sku"])
    st.session_state.setdefault("last_result", None)
    st.session_state.setdefault("last_analyzed_input", None)
    st.session_state.setdefault("analysis_error", "")
    st.session_state.setdefault("batch_file_signature", "")
    st.session_state.setdefault("batch_result", None)
    st.session_state.setdefault("batch_errors", [])
    st.session_state.setdefault("batch_demo_active", False)
    st.session_state.setdefault("chat_messages", [])
    st.session_state.setdefault("chat_context_id", "")


def _on_scenario_change() -> None:
    scenario = st.session_state["scenario_preset"]
    part_code = DEFAULT_SCENARIO_PART_CODES[scenario]
    st.session_state["part_sku"] = part_code
    _load_input_defaults(scenario, part_code)


def _on_part_change() -> None:
    _load_input_defaults(
        st.session_state["scenario_preset"], st.session_state["part_sku"]
    )


def _part_options(scenario: str) -> tuple[list[str], dict[str, str]]:
    data = generate_automotive_supply_data(scenario)
    labels = {
        str(row["part_code"]): (
            f"{row['part_code']} · "
            f"{PART_NAME_LABELS_ZH.get(str(row['part_name']), row['part_name'])}"
        )
        for _, row in data.iterrows()
    }
    return list(labels), labels


def _current_input_snapshot() -> dict[str, Any]:
    """Capture every value used by one workflow run as a stable snapshot."""

    return {
        "scenario": st.session_state["scenario_preset"],
        "part_code": st.session_state["part_sku"],
        "current_stock": st.session_state["current_inventory"],
        "daily_usage": st.session_state["daily_usage"],
        "supplier": st.session_state["supplier"].strip(),
        "lead_time_days": st.session_state["lead_time_days"],
        "supplier_status": st.session_state["supplier_status"],
        "criticality": st.session_state["criticality"],
        "backup_supplier_available": st.session_state[
            "backup_supplier_available"
        ],
        "safety_days": st.session_state["safety_days"],
    }


def _validate_input(snapshot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not snapshot["supplier"]:
        errors.append("供应商名称不能为空。")

    field_labels = {
        "current_stock": "当前库存",
        "daily_usage": "日均需求",
        "lead_time_days": "供应商交期",
        "safety_days": "安全天数",
    }
    for field, label in field_labels.items():
        value = snapshot[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{label}必须是数值。")
        elif not math.isfinite(float(value)) or float(value) < 0:
            errors.append(f"{label}必须是有限的非负数。")
    return errors


def _build_selected_part(snapshot: dict[str, Any]) -> dict[str, Any]:
    part = dict(snapshot["base_part"]) if snapshot.get('base_part') else get_scenario_part(snapshot["scenario"], snapshot["part_code"])
    part.update(
        {
            "current_stock": snapshot["current_stock"],
            "daily_usage": snapshot["daily_usage"],
            "supplier": snapshot["supplier"],
            "lead_time_days": snapshot["lead_time_days"],
            "supplier_status": snapshot["supplier_status"],
            "criticality": snapshot["criticality"],
            "backup_supplier_available": snapshot[
                "backup_supplier_available"
            ],
            "safety_days": snapshot["safety_days"],
        }
    )
    return part


def run_dashboard_analysis(
    snapshot: dict[str, Any], use_llm_report: bool = False
) -> dict[str, Any]:
    """Invoke the existing four-node graph with one immutable UI snapshot."""

    selected_part = _build_selected_part(snapshot)
    initial_state = create_initial_state(
        scenario=snapshot["scenario"],
        selected_part=selected_part,
        use_llm_report=use_llm_report,
    )
    return build_supply_chain_graph().invoke(initial_state)


def _display_number(value: float | int, suffix: str = "") -> str:
    numeric = float(value)
    if math.isinf(numeric):
        return "无消耗"
    if numeric.is_integer():
        return f"{int(numeric):,}{suffix}"
    return f"{numeric:,.2f}{suffix}"




def _run_automatic_analysis(snapshot: dict[str, Any]) -> None:
    errors = _validate_input(snapshot)
    if errors:
        st.session_state["last_result"] = None
        st.session_state["last_analyzed_input"] = None
        st.session_state["analysis_error"] = "\n".join(errors)
        return

    if (
        st.session_state.get("last_result") is not None
        and snapshot == st.session_state.get("last_analyzed_input")
    ):
        return

    try:
        st.session_state["last_result"] = run_dashboard_analysis(
            snapshot, use_llm_report=False
        )
        st.session_state["last_analyzed_input"] = dict(snapshot)
        st.session_state["analysis_error"] = ""
    except Exception as exc:
        st.session_state["last_result"] = None
        st.session_state["last_analyzed_input"] = None
        st.session_state["analysis_error"] = (
            f"分析未能完成：{type(exc).__name__}: {exc}"
        )


def _risk_conclusion(result: dict[str, Any]) -> tuple[str, str]:
    """Describe verified relationships without changing the business rules."""

    metrics = result["inventory_metrics"]
    part = result["selected_part"]
    risk_level = result["supplier_risk"]["risk_level"]
    days = float(metrics["days_of_stock"])
    lead = float(part["lead_time_days"])
    gap = float(metrics["stockout_gap"])
    if math.isinf(days):
        headline = "当前没有库存消耗，供应风险主要取决于供应商状态。"
        detail = "日均需求为零，因此库存覆盖天数不显示为无限值。"
    elif gap > 0 and str(part.get("criticality", "")).upper() == "HIGH":
        headline = f"关键零部件存在 {_display_number(gap, ' 天')}潜在供应覆盖缺口。"
        detail = (
            f"现有库存覆盖 {_display_number(days, ' 天')}，供应商交期为 "
            f"{_display_number(lead, ' 天')}；需同步评估交付缓解措施。"
        )
    elif gap > 0:
        headline = (
            f"库存只能支撑 {_display_number(days, ' 天')}，"
            f"交付却需要 {_display_number(lead, ' 天')}。"
        )
        detail = (
            f"预计存在 {_display_number(gap, ' 天')}潜在供应缺口。"
            "及时下单不等于能够在库存耗尽前到货。"
        )
    elif risk_level == "HIGH":
        headline = "库存可以覆盖交期，但供应异常仍需立即关注。"
        detail = "风险来自供应商状态、零部件关键程度或再订货点规则。"
    else:
        headline = (
            f"现有库存可覆盖 {_display_number(days, ' 天')}，"
            f"足以等待 {_display_number(lead, ' 天')}的交付。"
        )
        detail = "按当前模拟需求和供应状态，交期内没有潜在库存覆盖缺口。"
    return headline, detail


def _stock_trend_figure(result: dict[str, Any]) -> go.Figure:
    """Build an interactive trend from the same facts used by LangGraph."""

    part = result["selected_part"]
    metrics = result["inventory_metrics"]
    stock = float(part["current_stock"])
    usage = float(part["daily_usage"])
    lead = float(part["lead_time_days"])
    days = float(metrics["days_of_stock"])
    gap = float(metrics["stockout_gap"])
    horizon = max(14.0, lead * 1.18)
    if math.isfinite(days):
        horizon = max(horizon, days * 1.12)
    horizon = min(horizon, 90.0)
    sample_count = 81
    future_days = [horizon * index / (sample_count - 1) for index in range(sample_count)]
    remaining = [max(0.0, stock - usage * day) for day in future_days]
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=future_days,
            y=remaining,
            mode="lines",
            line={"color": "#176B5B", "width": 3.5},
            name="预计库存",
            hovertemplate="第 %{x:.1f} 天<br>预计剩余 %{y:,.0f} 件<extra></extra>",
        )
    )
    figure.add_vline(
        x=lead,
        line_width=1.4,
        line_dash="dash",
        line_color="#C94A4A",
        annotation_text=f"交期 {_display_number(lead, ' 天')}",
        annotation_position="top right",
        annotation_font={"color": "#C94A4A", "size": 11},
    )
    if gap > 0 and math.isfinite(days):
        figure.add_vrect(
            x0=min(days, lead),
            x1=max(days, lead),
            fillcolor="#C94A4A",
            opacity=0.08,
            line_width=0,
            annotation_text="潜在覆盖缺口",
            annotation_position="top left",
            annotation_font={"color": "#C94A4A", "size": 11},
        )
    if math.isfinite(days):
        figure.add_trace(
            go.Scatter(
                x=[min(days, horizon)],
                y=[0],
                mode="markers+text",
                marker={"color": "#176B5B", "size": 8},
                text=[f"预计第 {_display_number(days)} 天耗尽"],
                textposition="top left",
                textfont={"color": "#788482", "size": 10},
                hovertemplate="预计库存耗尽：第 %{x:.1f} 天<extra></extra>",
                showlegend=False,
            )
        )
    figure.add_trace(
        go.Scatter(
            x=[0],
            y=[stock],
            mode="markers",
            marker={"color": "#176B5B", "size": 9},
            name="今天",
            hovertemplate="今天<br>当前库存 %{y:,.0f} 件<extra></extra>",
            showlegend=False,
        )
    )
    figure.update_layout(
        height=300,
        margin={"l": 10, "r": 12, "t": 24, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
        showlegend=False,
        font={"family": "Microsoft YaHei, PingFang SC, sans-serif", "color": "#788482"},
        xaxis={
            "title": "未来天数",
            "showgrid": False,
            "zeroline": False,
            "range": [0, horizon],
            "fixedrange": True,
        },
        yaxis={
            "title": "预计剩余库存（件）",
            "gridcolor": "#EEF1EF",
            "zerolinecolor": "#DDE3E0",
            "rangemode": "tozero",
            "fixedrange": True,
        },
    )
    return figure




def _render_decision(result: dict[str, Any]) -> None:
    decision = result["replenishment_decision"]
    metrics = result["inventory_metrics"]
    secondary = "、".join(
        supporting_action_label_zh(item) for item in decision["supporting_actions"]
    ) or "无"
    reasons = [
        translate_decision_reason_zh(item) for item in decision["decision_reasons"]
    ]
    action = ACTION_LABELS_ZH.get(
        decision["recommended_action"], decision["recommended_action"]
    )
    quantity = int(decision["recommended_order_qty"])
    action_line = f"{action} {_display_number(quantity, ' 件')}" if quantity else action
    with st.container(key="decision_panel", border=False):
        primary, rationale = st.columns((0.42, 0.58), gap="large")
        with primary:
            st.markdown(
                '<div class="section-label">建议采取的行动</div>'
                f'<div class="decision-title">{_safe(action_line)}</div>'
                f'<div class="decision-quantity">补货数量来自 Python 规则：'
                f'<strong>{_safe(_display_number(quantity))}</strong> 件</div>',
                unsafe_allow_html=True,
            )
        with rationale:
            st.markdown('<div class="section-label">为什么这样建议</div>', unsafe_allow_html=True)
            for reason in reasons:
                st.markdown(f"- {reason}")
            st.markdown(f"**同步措施：** {secondary}")
            if float(metrics["stockout_gap"]) > 0:
                st.markdown(
                    '<div class="gap-note">建议订货用于恢复目标库存，不代表已下单，'
                    '也不能自动消除到货前缺口。</div>',
                    unsafe_allow_html=True,
                )


def _management_summary(result: dict[str, Any]) -> str:
    part = result["selected_part"]
    metrics = result["inventory_metrics"]
    risk = result["supplier_risk"]
    decision = result["replenishment_decision"]
    gap = float(metrics["stockout_gap"])
    gap_sentence = (
        f"存在 {_display_number(gap, ' 天')}潜在供应缺口。"
        if gap > 0
        else "当前没有交期内库存覆盖缺口。"
    )
    return (
        f"{part['part_code']} {part['part_name']}的库存可覆盖 "
        f"{_display_number(metrics['days_of_stock'], ' 天')}，供应商交期为 "
        f"{_display_number(part['lead_time_days'], ' 天')}。{gap_sentence}"
        f"系统判定为{RISK_LEVEL_LABELS_ZH.get(risk['risk_level'], risk['risk_level'])}，"
        f"建议{ACTION_LABELS_ZH.get(decision['recommended_action'], decision['recommended_action'])}"
        f" {_display_number(decision['recommended_order_qty'], ' 件')}。"
    )


def _render_report(
    snapshot: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    with st.container(key="management_report", border=False):
        st.markdown('<div class="section-label">管理层分析报告</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="management-summary">{_safe(zh_text(_management_summary(result)))}</div>', unsafe_allow_html=True)
        source_labels = {
            "template": "中文模板",
            "llm": "本地模型",
            "template_fallback": "中文模板回退",
        }
        report_source = result.get("report_source", "unknown")
        controls = st.columns(2, gap="small")
        if controls[0].button(
            "生成本地模型解读",
            key="generate_llm_report",
            width="stretch",
            help="主动请求时才调用本地 Ollama。",
            disabled=is_public_demo(),
        ):
            with st.spinner("本地 Ollama 正在生成管理说明…"):
                result = run_dashboard_analysis(snapshot, use_llm_report=True)
            st.session_state["last_result"] = result
            st.session_state["last_analyzed_input"] = dict(snapshot)
            report_source = result.get("report_source", "unknown")
        controls[1].download_button(
            "下载 PDF 报告",
            data=build_pdf_report(result),
            file_name=f"AutoSupply_{result['selected_part']['part_code']}.pdf",
            mime="application/pdf",
            key="download_single_pdf",
            width="stretch",
        )
        st.caption(f"报告来源：{source_labels.get(report_source, report_source)}")
        if report_source == "template_fallback":
            st.warning(
                "本地模型不可用或输出未通过校验，已自动展示可靠的中文模板报告。"
            )
            if result.get("llm_error"):
                with st.expander("查看本地模型回退原因"):
                    st.code(result["llm_error"], language=None)
        with st.expander("查看完整报告", expanded=False):
            st.markdown(zh_text(result["management_report"]).replace("\n", "\n\n"))
    return result


def _render_inline_assistant(context, *, key_suffix):
    st.markdown('**智能决策助手**')
    st.caption('回答基于当前成功分析的快照。模型只解释结果，不执行采购或修改库存。')
    if is_public_demo():
        st.info(PUBLIC_LLM_MESSAGE)
        if context:
            with st.expander('查看 Python 核验事实（非 AI 生成）'):
                st.write(zh_text(context['facts_text']))
        return
    if context is None:
        st.info('请先完成分析。')
        return
    if st.session_state.get('assistant_input_dirty'):
        st.info('输入数据已变更，旧问答已清理。重新运行分析后可询问当前结果。')
        return
    if st.button('检查本地模型连接',key=f'check_model_{key_suffix}'):
        try:
            import urllib.request,json
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open('http://127.0.0.1:11434/api/tags',timeout=5) as response:
                models=json.load(response)['models']
            if any(m['name'].startswith('llama3.2') for m in models):st.success('本地模型服务正常，已找到当前配置的模型。')
            else:st.error('本地服务正常，但尚未找到当前配置的模型。')
        except Exception:st.error('无法连接本机模型服务，请打开 Ollama 后重试；库存计算不受影响。')
    questions=('为什么会出现这个风险？','建议订货量是怎么计算的？','目前最应该采取什么措施？') if key_suffix!='batch' else ('哪些零部件需要优先关注？','为什么当前物料风险较高？','应该先采取哪些缓解措施？')
    selected=''
    columns=st.columns(3)
    for index,question in enumerate(questions):
        if columns[index].button(question,key=f'quick_{key_suffix}_{index}',width='stretch'):selected=question
    with st.form(f'assistant_form_{key_suffix}',clear_on_submit=True):
        entry,submit=st.columns((.78,.22),vertical_alignment='bottom')
        typed=entry.text_input('询问当前分析',key='batch_ai_input' if key_suffix=='batch' else f'inline_chat_{key_suffix}',placeholder='输入关于库存、风险或补货的问题')
        submitted=submit.form_submit_button('发送',type='primary',width='stretch')
    messages=st.session_state['chat_messages']
    question=selected or (typed if submitted else '')
    if question:
        prior=[];messages[:]=[{'role':'user','content':question}]
        try:
            with st.spinner('本地模型正在解释当前结果…'):
                answer=answer_supply_chain_question(question,context,history=prior)
            messages.append({'role':'assistant','content':answer})
        except (AssistantUnavailableError,ValueError) as exc:
            messages.append({'role':'assistant','content':f'本次解读未完成，库存分析结果仍有效。\n\n{exc}','is_error':True})
    if not messages:st.info('选择一个快捷问题，或输入自己的问题。')
    for message in messages[-2:]:
        with st.container():
            if message.get('is_error'):st.error(zh_text(message['content']))
            elif message['role']=='assistant' and '\n\n**AI' in message['content']:
                facts,explanation=message['content'].split('\n\n**AI',1)
                st.markdown(zh_text('**AI'+explanation))
                with st.expander('查看本次核验事实'):st.markdown(zh_text(facts))
            else:st.markdown(('**本次提问：** ' if message['role']=='user' else '')+zh_text(message['content']))



def _render_trace(result: dict[str, Any]) -> None:
    traces = result.get("execution_trace", [])
    icons = {"SUCCESS": "✓", "FAILED": "!", "SKIPPED": "–"}
    steps = []
    for trace in traces[:4]:
        status = trace["execution_status"]
        node = trace["node_name"]
        steps.append(
            '<span class="agent-step">'
            f'<i class="status-{status.lower()}">{icons.get(status, "•")}</i>'
            f'{_safe(NODE_LABELS_ZH.get(node, node))}'
            f'<small>{_safe(STATUS_LABELS_ZH.get(status, status))}</small></span>'
        )
    st.markdown(
        '<div class="agent-strip"><span class="agent-label">分析路径</span>'
        + '<b>→</b>'.join(steps)
        + '</div>',
        unsafe_allow_html=True,
    )
    with st.expander("查看完整分析过程", expanded=False):
        st.caption("节点与执行状态来自本次实际工作流。诊断数据可供开发排查。")
        for trace in traces:
            node = trace["node_name"]
            status = trace["execution_status"]
            st.markdown(
                f"**{NODE_LABELS_ZH.get(node, node)} · "
                f"{STATUS_LABELS_ZH.get(status, status)}**"
            )
        import json
        st.download_button("导出工作流诊断 JSON",json.dumps(traces,ensure_ascii=False,indent=2),file_name="workflow_trace.json",key="trace_json")


def _render_details(result: dict[str, Any]) -> None:
    risk = result["supplier_risk"]
    decision = result["replenishment_decision"]
    with st.expander("分析依据、策略参数与业务假设", expanded=False):
        left, right = st.columns(2, gap="large")
        with left:
            st.markdown("**风险判断依据**")
            for reason in risk["reasons"]:
                st.markdown(f"- {zh_text(translate_risk_reason_zh(reason))}")
            for factor in risk["mitigating_factors"]:
                st.markdown(f"- {zh_text(translate_mitigating_factor_zh(factor))}")
        with right:
            st.markdown("**模型边界**")
            for caveat in decision["caveats"]:
                st.markdown(f"- {zh_text(caveat)}")
            st.caption("安全天数为模拟策略设定；当前模型未包含在途库存与未结订单。")


def _render_batch_detail(result: dict[str, Any]) -> None:
    risk = result["supplier_risk"]
    decision = result["replenishment_decision"]
    metrics = result["inventory_metrics"]

    risk_level = risk["risk_level"]
    st.markdown(
        '<div class="batch-detail-heading"><div>'
        f'<strong>{_safe(result["selected_part"]["part_code"])}</strong>'
        f'<span>{_safe(zh_text(result["selected_part"]["part_name"]))}</span></div>'
        f'<em style="--risk-color:{_risk_color(risk_level)}">'
        f'{_safe(zh_text(RISK_LEVEL_LABELS_ZH.get(risk_level, risk_level)).split("（")[0])}</em></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="batch-detail-grid">'
        '<div><span>库存覆盖</span><strong>'
        f'{_safe(_display_number(metrics["days_of_stock"], " 天"))}</strong></div>'
        '<div><span>潜在缺口</span><strong>'
        f'{_safe(_display_number(metrics["stockout_gap"], " 天"))}</strong></div>'
        '<div><span>建议订货</span><strong>'
        f'{_safe(_display_number(decision["recommended_order_qty"], " 件"))}</strong></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="batch-decision">'
        '<span>主要行动</span><strong>'
        f'{_safe(action_label_zh(decision["recommended_action"]))}</strong>'
        '</div>',
        unsafe_allow_html=True,
    )
    secondary = "、".join(
        supporting_action_label_zh(item)
        for item in decision["supporting_actions"]
    ) or "无"
    st.caption(f"同步措施：{zh_text(secondary)}")
    st.markdown(
        '<div class="batch-management-summary"><span>管理摘要</span>'
        f'<p>{_safe(zh_text(_management_summary(result)))}</p></div>',
        unsafe_allow_html=True,
    )
    st.download_button(
        "下载该物料 PDF 报告",
        data=build_pdf_report(result),
        file_name=f"AutoSupply_{result['selected_part']['part_code']}.pdf",
        mime="application/pdf",
        key="download_batch_pdf",
        width="stretch",
    )
    with st.expander("查看完整管理报告", expanded=False):
        st.markdown(zh_text(result["management_report"]).replace("\n", "\n\n"))
    _render_trace(result)


def _format_batch_day(value: Any) -> str:
    """Format an existing day value for compact display without recalculation."""

    if value == "无消耗":
        return "无消耗"
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    try:
        return _display_number(float(value), " 天")
    except (TypeError, ValueError):
        return "—"


def _prepare_batch_display_frame(summary: pd.DataFrame) -> pd.DataFrame:
    """Create the six-column presentation view from the sorted workflow result."""

    display_frame = summary.loc[
        :,
        [
            "part_code",
            "part_name",
            "days_of_stock",
            "stockout_gap",
            "risk_level",
            "recommended_order_qty",
        ],
    ].copy()
    display_frame["days_of_stock"] = display_frame["days_of_stock"].map(
        _format_batch_day
    )
    display_frame["stockout_gap"] = display_frame["stockout_gap"].map(
        _format_batch_day
    )
    display_frame["recommended_order_qty"] = display_frame[
        "recommended_order_qty"
    ].map(
        lambda value: "—"
        if value == "" or pd.isna(value)
        else _display_number(value, " 件")
    )
    return display_frame.rename(
        columns={
            "part_code": "SKU",
            "part_name": "零部件",
            "days_of_stock": "库存覆盖",
            "stockout_gap": "潜在缺口",
            "risk_level": "风险等级",
            "recommended_order_qty": "建议订货量",
        }
    )


def _batch_table_height(row_count: int) -> int:
    """Fit small batches tightly and cap larger batches for internal scrolling."""

    return min(68 + max(row_count, 1) * 35, 348)


def _render_batch_assistant(context):
    return _render_inline_assistant(context,key_suffix='batch')



def _build_batch_demo_data() -> pd.DataFrame:
    """Create a fictional mixed-risk batch from the three existing presets."""

    demo = build_batch_template()
    for scenario, part_code in (
        (SUPPLIER_DELAY, DEFAULT_SCENARIO_PART_CODES[SUPPLIER_DELAY]),
        (CRITICAL_SHORTAGE, DEFAULT_SCENARIO_PART_CODES[CRITICAL_SHORTAGE]),
    ):
        replacement = get_scenario_part(scenario, part_code)
        row_mask = demo["part_code"].eq(part_code)
        for column in demo.columns:
            if column in replacement:
                demo.loc[row_mask, column] = replacement[column]
    return demo


def _batch_priority_figure(summary: pd.DataFrame) -> go.Figure:
    """Visualize the already sorted top ten rows without inventing a score."""

    successful = summary[summary["analysis_status"] == "SUCCESS"].head(10).copy()
    successful = successful.iloc[::-1]
    gaps = pd.to_numeric(successful["stockout_gap"], errors="coerce").fillna(0.0)
    colors = successful["risk_level"].map(RISK_COLORS).fillna("#788482")
    labels = successful["part_code"].astype(str)
    hover = [
        f"{row.part_code} {zh_text(row.part_name)}<br>风险：{zh_text(row.risk_level)}"
        f"<br>潜在缺口：{row.stockout_gap} 天<br>建议订货：{row.recommended_order_qty} 件"
        for row in successful.itertuples()
    ]
    figure = go.Figure(
        go.Bar(
            x=gaps,
            y=labels,
            orientation="h",
            marker_color=list(colors),
            customdata=hover,
            hovertemplate="%{customdata}<extra></extra>",
            text=[f"{zh_text(risk)} · {gap:g} 天" for risk, gap in zip(successful["risk_level"], gaps)],
            textposition="outside",
            cliponaxis=False,
        )
    )
    figure.update_layout(
        height=300,
        margin={"l": 8, "r": 78, "t": 8, "b": 26},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        font={"family": "Microsoft YaHei, PingFang SC, sans-serif", "color": "#788482"},
        xaxis={"title": "潜在覆盖缺口（天）", "showgrid": False, "fixedrange": True},
        yaxis={"title": "", "fixedrange": True},
    )
    return figure






def _synchronize_chat_context(context: dict[str, Any] | None) -> None:
    context_id = json.dumps([st.session_state.get('analysis_mode'),st.session_state.get('chat_draft_scope'),context['context_id'] if context else ''],ensure_ascii=False,sort_keys=True,default=str)
    if context_id == st.session_state.get("chat_context_id", ""):
        return
    st.session_state["chat_context_id"] = context_id
    st.session_state["chat_messages"] = []
    for key in ('batch_ai_input','inline_chat_single','inline_chat_planning'):
        st.session_state.pop(key,None)


def _page_api():
    # Streamlit registers a new __main__ for every session. The global module
    # registry can therefore point at another session's half-initialized script.
    # Keep this run's functions and constants instead of reading that registry.
    return SimpleNamespace(**globals())


def render_app() -> None:
    st.set_page_config(
        page_title="AutoSupply Copilot",
        page_icon="🚗",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(
        """
        <style>
        :root {
            --ink:#172326; --accent:#176B5B; --bg:#F8F9F7;
            --paper:#FFFFFF; --muted:#788482; --stroke:#E6EAE8;
            --danger:#C94A4A; --warning:#C88B35; --success:#23836B;
        }
        html, body, .stApp {font-family:"Microsoft YaHei","PingFang SC","Segoe UI",sans-serif;}
        .stApp {background:var(--bg); color:var(--ink);}
        .block-container {padding-top:.7rem; padding-bottom:2rem; max-width:1380px;}
        h1 {font-size:1.68rem !important; color:var(--ink) !important;
            letter-spacing:-.035em; margin:0 !important; font-weight:700 !important;}
        h2, h3, h4 {color:var(--ink) !important; letter-spacing:-.025em;}
        h3 {font-size:1.18rem !important; margin-top:.7rem !important;}
        p, li {line-height:1.6;}
        [data-testid="stHeader"] {
            background:transparent; height:0; pointer-events:none;
        }
        /* Streamlit's transparent 60px toolbar spans the whole viewport. The
           mode switch sits visually below its empty area, so let pointer events
           pass through while keeping Deploy and the main menu interactive. */
        [data-testid="stToolbar"] {pointer-events:none;}
        [data-testid="stHeader"] button {pointer-events:auto;}
        .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
            background:var(--accent); border-color:var(--accent); font-weight:650;
        }
        .stButton > button, .stDownloadButton > button {
            border-color:#DCE3E0; color:var(--ink); border-radius:10px;
            min-height:2.35rem;
        }
        div[role="radiogroup"] {gap:.35rem; justify-content:flex-end;}
        div[role="radiogroup"] label {
            background:var(--paper); border:1px solid var(--stroke);
            border-radius:999px; padding:.28rem .78rem;
        }
        .brand-row {display:flex; align-items:center; gap:.68rem;}
        .brand-mark {display:grid; place-items:center; width:31px; height:31px;
            border-radius:9px; background:var(--ink); color:white; font-weight:750;}
        .app-subtitle {color:var(--muted); font-size:.82rem; margin-top:.15rem;}
        .simulation-badge {text-align:right; color:var(--muted); font-size:.72rem;
            margin-top:.2rem;}
        .simulation-badge b {color:var(--success);}
        .st-key-input_bar {background:var(--paper); border:1px solid var(--stroke);
            border-radius:16px; padding:.72rem 1rem .15rem; margin:.5rem 0 .35rem;}
        .input-heading {display:flex; align-items:baseline; gap:.65rem; margin-bottom:.15rem;}
        .input-heading strong {font-size:.88rem; color:var(--ink);}
        .input-heading span {font-size:.72rem; color:var(--muted);}
        .analysis-context {color:var(--muted); padding:.12rem .15rem .25rem;
            font-size:.75rem;}
        .st-key-risk_diagnosis {background:var(--paper); border-radius:20px;
            padding:1rem 1.15rem .55rem; margin-bottom:.55rem;}
        .hero-copy {padding:.2rem .15rem .25rem;}
        .hero-overline {display:flex; align-items:center; justify-content:space-between;
            color:var(--muted); font-size:.75rem; font-weight:650; letter-spacing:.02em;}
        .hero-overline b {font-size:.76rem; letter-spacing:.04em;}
        .hero-statement {font-size:2.05rem; line-height:1.25; letter-spacing:-.045em;
            color:var(--ink); font-weight:680; margin:.85rem 0 .55rem; max-width:560px;}
        .hero-description {color:var(--muted); line-height:1.62; font-size:.9rem; max-width:540px;}
        .relationship-row {display:grid; grid-template-columns:repeat(3,1fr); gap:.55rem;
            border-top:1px solid var(--stroke); margin-top:.9rem; padding-top:.72rem;}
        .relationship-row div {display:flex; flex-direction:column; gap:.12rem;}
        .relationship-row span {font-size:.72rem; color:var(--muted);}
        .relationship-row strong {font-size:1.18rem; color:var(--ink); font-weight:680;}
        .relationship-row .gap strong {color:var(--danger);}
        .chart-heading {display:flex; justify-content:space-between; align-items:baseline;
            padding:.05rem .15rem 0;}
        .chart-heading strong {font-size:.9rem; color:var(--ink);}
        .chart-heading span {font-size:.68rem; color:var(--muted);}
        .section-label {font-size:.69rem; color:var(--muted); font-weight:750;
            letter-spacing:.11em; text-transform:uppercase; margin-bottom:.65rem;}
        .st-key-decision_panel {background:#F0F3F1; border-radius:18px;
            padding:1rem 1.15rem .7rem; margin-bottom:.65rem;}
        .decision-title {font-size:1.85rem; color:var(--ink); font-weight:680;
            letter-spacing:-.035em; line-height:1.2;}
        .decision-quantity {color:var(--muted); margin:.55rem 0 .4rem;}
        .decision-quantity strong {color:var(--accent); font-size:1.38rem;}
        .gap-note {color:var(--warning); background:#FBF7ED; border-left:3px solid var(--warning);
            border-radius:7px; padding:.38rem .52rem; font-size:.72rem; margin-top:.5rem;}
        .st-key-management_report,.st-key-assistant_single,.st-key-assistant_batch {
            background:var(--paper); border:1px solid var(--stroke); border-radius:18px;
            padding:1rem 1.05rem .8rem; min-height:390px;}
        .management-summary {font-size:.96rem; line-height:1.75; color:var(--ink);
            min-height:6rem;}
        .st-key-chat_history_single,.st-key-chat_history_batch {background:#FAFBFA;
            border-radius:12px; padding:.25rem .45rem;}
        .st-key-assistant_single .stButton button p,
        .st-key-assistant_batch .stButton button p {white-space:normal; line-height:1.25;
            font-size:.72rem; overflow:visible; text-overflow:clip;}
        .agent-strip {display:flex; align-items:center; gap:.52rem; background:var(--paper);
            border-top:1px solid var(--stroke); border-bottom:1px solid var(--stroke);
            padding:.65rem .2rem; margin-top:.65rem; overflow-x:auto; white-space:nowrap;}
        .agent-label {font-size:.7rem; color:var(--muted); padding-right:.25rem;}
        .agent-strip>b {color:#C8D1CD; font-weight:400;}
        .agent-step {display:inline-flex; align-items:center; gap:.3rem; font-size:.76rem;
            color:var(--ink); font-weight:650;}
        .agent-step small {font-size:.62rem; color:var(--muted); font-weight:400;}
        .status-success {display:grid; place-items:center; width:17px; height:17px;
            border-radius:50%; background:#E8F3EF; color:var(--success); font-style:normal;}
        .status-failed {color:var(--danger); font-style:normal;}
        .status-skipped {color:var(--warning); font-style:normal;}
        .batch-intro {display:flex; align-items:baseline; gap:.7rem; margin:.15rem 0 .65rem;}
        .batch-intro span {font-size:.68rem; color:var(--accent); font-weight:750;
            text-transform:uppercase; letter-spacing:.1em;}
        .batch-intro strong {font-size:1.25rem; color:var(--ink);}
        .batch-intro small {color:var(--muted); margin-left:auto;}
        .st-key-batch_detail_panel {background:var(--paper); border:1px solid var(--stroke);
            border-radius:18px; padding:.72rem .85rem .55rem;}
        .batch-detail-heading {display:flex; align-items:center; justify-content:space-between;
            gap:.8rem; margin:.12rem 0 .48rem;}
        .batch-detail-heading>div {display:flex; align-items:baseline; gap:.48rem; min-width:0;}
        .batch-detail-heading strong {font-size:1.18rem; color:var(--ink);}
        .batch-detail-heading span {font-size:.82rem; color:var(--muted); white-space:nowrap;
            overflow:hidden; text-overflow:ellipsis;}
        .batch-detail-heading em {font-style:normal; flex:none; color:var(--risk-color);
            background:color-mix(in srgb, var(--risk-color) 10%, white); border:1px solid
            color-mix(in srgb, var(--risk-color) 24%, white); padding:.22rem .55rem;
            border-radius:999px; font-size:.72rem; font-weight:750;}
        .batch-detail-grid {display:grid; grid-template-columns:repeat(3,1fr); gap:.4rem;
            margin:.45rem 0;}
        .batch-detail-grid div {background:#F7F9F8; padding:.55rem; border-radius:10px;}
        .batch-detail-grid span,.batch-decision span {display:block; color:var(--muted);
            font-size:.66rem; margin-bottom:.16rem;}
        .batch-detail-grid strong {font-size:.94rem; color:var(--ink);}
        .batch-decision {border-left:3px solid var(--accent); padding:.35rem .6rem;
            margin:.4rem 0 .25rem;}
        .batch-decision strong {font-size:1.08rem; color:var(--ink);}
        .batch-management-summary {background:#F7F9F8; border-radius:11px;
            padding:.58rem .68rem; margin:.48rem 0 .55rem;}
        .batch-management-summary span {display:block; color:var(--muted); font-size:.66rem;
            margin-bottom:.18rem;}
        .batch-management-summary p {margin:0; color:var(--ink); font-size:.78rem;
            line-height:1.58;}
        .batch-summary {display:grid; grid-template-columns:repeat(5,1fr); gap:.55rem;
            margin:.7rem 0;}
        .batch-summary div {padding:.65rem .75rem; background:var(--paper);
            border-bottom:2px solid var(--stroke);}
        .batch-summary span {display:block; color:var(--muted); font-size:.72rem;}
        .batch-summary strong {font-size:1.35rem; color:var(--ink);}
        .batch-summary .high {border-color:var(--danger);}
        .batch-summary .medium {border-color:var(--warning);}
        .batch-summary .low {border-color:var(--success);}
        .st-key-batch_assistant_wide {background:var(--paper); border:1px solid var(--stroke);
            border-radius:18px; padding:.85rem 1rem .7rem; margin-top:.8rem;}
        .batch-ai-title {font-size:1.08rem; line-height:1.4; font-weight:680;
            color:var(--ink); margin-bottom:.28rem;}
        .batch-ai-guide {font-size:.76rem; color:var(--muted); line-height:1.55;
            margin:0 0 .45rem;}
        .st-key-batch_assistant_wide .stButton button p {white-space:normal;
            line-height:1.25; font-size:.72rem;}
        .st-key-batch_chat_history {background:#F7F9F8; border:1px solid var(--stroke);
            border-radius:12px; padding:.18rem .55rem;}
        .batch-chat-empty {display:flex; align-items:center; min-height:180px;
            justify-content:center; text-align:center; color:var(--muted); font-size:.78rem;
            line-height:1.6; padding:1rem;}
        .batch-chat-role {font-size:.64rem; font-weight:750; letter-spacing:.05em;
            color:var(--muted); margin:.08rem 0 -.35rem;}
        .batch-chat-role.user {color:var(--accent);}
        .st-key-batch_assistant_wide [data-testid="stForm"] {border:0; padding:.4rem 0 0;}
        .st-key-batch_assistant_wide [data-testid="stForm"] [data-testid="stHorizontalBlock"] {
            align-items:flex-end;}
        [data-testid="stDataFrame"] {border: 1px solid var(--stroke); border-radius: 14px; overflow: hidden;}
        [data-testid="stAlert"] {border-radius: 12px;}
        details {border-color:var(--stroke) !important; border-radius:12px !important;}
        @media (max-width: 1300px) {
            .block-container {padding-top:.45rem; padding-left:1.5rem; padding-right:1.5rem;}
            .hero-statement {font-size:1.78rem;}
            .management-summary {min-height:5rem;}
            .agent-step small {display:none;}
        }
        @media (max-width: 900px) {
            .block-container {padding-left:.85rem; padding-right:.85rem;}
            .hero-statement {font-size:1.65rem;}
            .relationship-row {grid-template-columns:repeat(3,1fr);}
            .batch-intro {display:block;}
            .batch-intro > * {display:block; margin:.2rem 0;}
            .batch-summary {grid-template-columns:repeat(3,1fr);}
            .chart-heading span {display:none;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _initialize_session_state()

    import website_ui
    page_api=_page_api()
    website_ui.shell(st.session_state['analysis_mode'],page_api)
    if is_public_demo():
        st.caption('公开演示环境：内置汽车零部件数据完全虚构。请仅上传模拟或非敏感数据；上传内容不写入磁盘或公开仓库。关闭会话前请自行下载所需结果。')
    mode = st.radio(
            "分析模式",
            options=(SINGLE_ANALYSIS_MODE, BATCH_ANALYSIS_MODE, PLANNING_ANALYSIS_MODE),
            horizontal=True,
            key="analysis_mode",
            label_visibility="collapsed",
            format_func=lambda value:{SINGLE_ANALYSIS_MODE:'单物料分析',BATCH_ANALYSIS_MODE:'多物料批量分析',PLANNING_ANALYSIS_MODE:'动态物料计划'}[value],
        )
    website_ui.hero(mode,page_api)
    if mode == SINGLE_ANALYSIS_MODE:
        website_ui.render_single(page_api)
    elif mode == PLANNING_ANALYSIS_MODE:
        render_planning_mode(_render_trace, _render_inline_assistant, _synchronize_chat_context)
    else:
        website_ui.render_batch(page_api)
    st.session_state['site_last_mode']=mode
    st.caption('AutoSupply Copilot · 决策支持演示 · 内置数据均为虚构，未执行采购或调拨。')


if __name__ == "__main__":
    render_app()
