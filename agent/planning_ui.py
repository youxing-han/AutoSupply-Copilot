"""Explicit load/edit/run workflow, preserving drafts and validated results."""
from __future__ import annotations

from copy import deepcopy
import logging
import traceback

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from assistant import build_assistant_context
from inventory_planning import day
from planning_data import (INTERVIEW_SCENARIOS, SHEETS, PlanningInputError, analyze_planning_bundle,
                           build_interview_demo, normal_arrival_baseline,
                           planning_xlsx_bytes, read_planning_xlsx)
from planning_workspace import analysis_totals, fingerprint, new_workspace
from report_pdf import build_pdf_report
from mitigation_ui import render_mitigation
from runtime_mode import is_public_demo

LOGGER = logging.getLogger(__name__)
PLANNING_UI_VERSION = 8


def inventory_figure(result: dict, baseline: dict | None = None) -> go.Figure:
    projection = result["inventory_projection"]
    frame = pd.DataFrame(projection["daily"])
    figure = go.Figure()
    figure.add_scatter(x=frame["date"], y=frame["closing_available"], name="期末预计可用库存",
                       mode="lines+markers", line={"color": "#176B5B", "width": 3})
    figure.add_bar(x=frame["date"], y=frame["unmet_demand"], name="当日未满足需求",
                   marker_color="#C94A4A")
    figure.add_bar(x=frame['date'], y=frame['confirmed_receipts'], name='当日确认到货量',marker_color='#98cdb2',opacity=.65)
    figure.add_scatter(x=frame['date'], y=frame['planned_demand'], name='当日计划需求',mode='lines',line={'color':'#7291a5','dash':'dot'})
    figure.add_scatter(x=frame["date"], y=[result["selected_part"]["safety_stock"]] * len(frame),
                       name="安全库存阈值", mode="lines", line={"color": "#C88B35", "dash": "dot"})
    arrivals = frame.loc[frame["confirmed_receipts"] > 0]
    figure.add_scatter(x=arrivals["date"], y=arrivals["closing_available"], mode="markers",
                       name="已确认采购到货", marker={"size": 13, "symbol": "diamond", "color": "#416B9C"},
                       customdata=[[", ".join(r["po_ids"]), r["confirmed_receipts"]] for _, r in arrivals.iterrows()],
                       hovertemplate="%{x}<br>%{customdata[0]}<br>到货 %{customdata[1]} 件<extra></extra>")
    pending = [o for o in projection["excluded_orders"] if o["status"] == "PENDING"
               and frame.iloc[0]["date"] <= o["arrival_date"] <= frame.iloc[-1]["date"]]
    if pending:
        figure.add_scatter(x=[o["arrival_date"] for o in pending], y=[0] * len(pending),
                           name="待确认订单（未计入库存）", mode="markers",
                           marker={"symbol": "diamond-open", "size": 13, "color": "#788482"},
                           text=[o["po_id"] for o in pending],
                           hovertemplate="%{x}<br>%{text}<br>待确认，未纳入库存<extra></extra>")
    if baseline is not None:
        reference = baseline["inventory_projection"]["daily"]
        figure.add_scatter(x=[r["date"] for r in reference], y=[r["closing_available"] for r in reference],
                           name="正常到货基准库存", mode="lines", line={"color": "#758CB5", "dash": "dash"})
    figure.update_layout(height=350, margin={"l": 12, "r": 12, "t": 52, "b": 10},
                         paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                         hovermode="x unified", legend={"orientation": "h", "y": 1.03,'yanchor':'bottom','font':{'size':10}},
                         yaxis_title="件", xaxis_title="生产日期", yaxis={"rangemode": "tozero"},
                         font={"family": "Microsoft YaHei, sans-serif"})
    figure.update_xaxes(tickformat='%m月%d日',hoverformat='%Y年%m月%d日')
    return figure


def _controls() -> tuple:
    return (st.session_state["planning_scenario"], st.session_state["planning_start"].isoformat(),
            st.session_state["planning_horizon"])


def _replace_workspace(bundle: dict, source: str, controls: tuple) -> None:
    revision = st.session_state.get("planning_workspace", {}).get("revision", 0) + 1
    st.session_state["planning_workspace"] = new_workspace(bundle, source, controls, revision)
    st.session_state["planning_draft"] = deepcopy(bundle)
    st.session_state["planning_input_error"] = ""
    st.session_state["planning_upload_error"] = ""


def _load_demo() -> None:
    scenario, start, horizon = _controls()
    from demo_data import build_rich_planning
    from localized_ui import zh
    pack=st.session_state.get('planning_data_pack','多物料排产 · 12种物料')
    bundle=build_rich_planning(start,horizon,scenario) if pack.startswith('多物料') else build_interview_demo(start,horizon,scenario)
    for p in bundle['parts']:
        p['part_name']=zh(p['part_name']);p['supplier']=zh(p['supplier'])
    for s in bundle['suppliers']:s['supplier']=zh(s['supplier'])
    for o in bundle['orders']:o['supplier']=zh(o['supplier'])
    st.session_state['planning_loaded_pack']=pack
    _replace_workspace(bundle, f"演示数据 · {scenario} · {pack}", _controls())


def _import_upload(upload=None) -> None:
    from localized_ui import upload_value
    upload = upload_value(upload or st.session_state.get("planning_upload"))
    if upload is None:
        st.session_state["planning_upload_error"] = ""
        return
    try:
        bundle = read_planning_xlsx(upload.getvalue())
    except (ValueError, OSError) as exc:
        from localized_ui import user_error
        st.session_state["planning_upload_error"] = f"Excel 输入校验失败：{user_error(exc)}"
        return
    settings = bundle["settings"][0]
    st.session_state["planning_start"] = day(settings["start_date"])
    st.session_state["planning_horizon"] = settings["horizon_days"]
    _replace_workspace(bundle, f"上传文件 · {upload.name}", _controls())


def _initialize_workspace() -> None:
    aliases = {"延迟到货": "供应商交付延迟", "待确认订单": "采购订单待确认", "波动需求": "生产需求激增"}
    saved = st.session_state.get("planning_controls_choice", st.session_state.get("planning_workspace", {}).get("controls", ("正常到货", "2026-10-12", 30)))
    selected = st.session_state.get("planning_scenario", saved[0])
    selected = aliases.get(selected, selected)
    from demo_data import RICH_SCENARIOS
    st.session_state["planning_scenario"] = selected if selected in RICH_SCENARIOS else "正常到货"
    st.session_state.setdefault("planning_start", day(saved[1]))
    st.session_state.setdefault("planning_horizon", saved[2])
    if "planning_workspace" not in st.session_state:
        _load_demo()
        # A pre-editor result has no explicit immutable analysis snapshot.
        st.session_state.pop("planning_analysis", None)
        st.session_state.pop("planning_selected_result", None)
        st.session_state.pop("mitigation_comparison", None)




def _run_analysis(draft: dict, source: str) -> None:
    st.session_state['planning_input_error']=''
    st.session_state['planning_internal_error']=''
    st.session_state.pop('planning_internal_trace',None)
    try:
        analysis = analyze_planning_bundle(draft)
    except PlanningInputError as exc:
        from localized_ui import user_error
        st.session_state["planning_input_error"] = f"动态计划输入校验失败：{user_error(exc)}"
        return
    except Exception as exc:
        if is_public_demo():
            LOGGER.error("Dynamic workflow failed (%s)", type(exc).__name__)
            st.session_state["planning_internal_error"] = "动态分析未完成，请检查输入或稍后重试。"
            return
        LOGGER.exception("Internal dynamic planning workflow failed")
        st.session_state["planning_internal_error"] = f"动态分析工作流异常（非输入校验错误）：{exc}"
        st.session_state["planning_internal_trace"] = traceback.format_exc()
        return
    st.session_state["planning_analysis"] = analysis
    st.session_state["planning_analysis_fingerprint"] = fingerprint(draft)
    st.session_state["planning_analysis_source"] = source
    st.session_state["planning_analyzed_controls"] = _controls()
    st.session_state["planning_input_error"] = ""
    st.session_state["planning_internal_error"] = ""
    st.session_state.pop("planning_internal_trace", None)






def render_planning_mode(render_trace,render_assistant,synchronize_chat):
    import sys
    from planning_site import render
    return render(sys.modules[__name__],render_trace,render_assistant,synchronize_chat)
