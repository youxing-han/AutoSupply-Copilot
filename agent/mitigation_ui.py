"""Scenario controls and compact comparison backed by the actual graph."""
import hashlib
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from workflow_runtime import run_planning_workflow, WorkflowContractError
from mitigation import build_mitigation_demo
from localized_ui import editor,table,column,zh,zh_text
MITIGATION_UI_VERSION = 3


def render_mitigation(result: dict) -> dict:
    st.subheader("供应应急方案比较")
    st.caption("模拟供给快照，未执行任何采购或调拨。固定批量组合穷举，以预测期零数量短缺为首要约束，再比较建模增量成本。")
    candidates = build_mitigation_demo(result)
    identity = hashlib.sha256(json.dumps({"part": result["selected_part"], "plan": result["planning_input"]}, sort_keys=True, default=str).encode()).hexdigest()[:12]
    with st.expander("调整候选措施参数（数量、最早日期、资格与成本）"):
        st.caption("数量为本次固定批量，可供上限是来源能力约束。现有订单加急只改变原订单日期，不增加采购数量；内部调拨需满足共享库存限制。")
        readonly={"candidate_id","part_code","kind","source","linked_po_id","source_pool"}
        columns=[column(c,editable=c not in readonly,kind='date' if c=='earliest_available_date' else 'boolean' if isinstance(candidates[0][c],bool) else 'number' if isinstance(candidates[0][c],(int,float)) else 'select' if c=='kind' else 'text',choices=('EXPEDITE','BACKUP','TRANSFER') if c=='kind' else None) for c in candidates[0]]
        edited=editor(candidates,columns,key=f"mitigation_editor_{identity}")
    try:
        updated = run_planning_workflow(result["selected_part"], result["planning_input"], edited)
    except WorkflowContractError as exc:
        st.error(str(exc))
        st.session_state.pop("mitigation_comparison", None)
        return result
    comparison = updated["mitigation_comparison"]
    st.session_state["mitigation_comparison"] = comparison
    summary = []
    for row in comparison["scenarios"]:
        summary.append({"方案": row["scenario_id"], "主要约束": "满足" if row["constraints_satisfied"] else "不满足",
                        "零数量短缺": "是" if row["fully_feasible"] else "否",
                        "减少未满足需求": row["reduction_unmet"], "残余缺料量": row["residual_unmet"],
                        "首次残余缺料": row["first_residual_shortage"] or "无", "增量成本（元）": row["incremental_cost"]})
    table(summary)
    if comparison["has_fully_feasible"]:
        st.success(zh_text(comparison["recommendation_reason"]))
    else:
        st.warning(zh_text(comparison["recommendation_reason"]))
    ids = [s["scenario_id"] for s in comparison["scenarios"]]
    selected = st.selectbox("查看方案库存结果", ids, format_func=zh,index=ids.index(comparison["recommended"]["scenario_id"]), key=f"mitigation_selection_{identity}")
    selected_scenario = next(s for s in comparison["scenarios"] if s["scenario_id"] == selected)
    updated["selected_mitigation_scenario"] = {k: v for k, v in selected_scenario.items() if k != "projection"}
    if not selected_scenario["constraints_satisfied"]:
        st.error("此方案不可执行：" + "；".join(selected_scenario["constraint_reasons"]))
        st.caption("未将违规供给加入库存。下列残余指标保留基准结果。")
    st.caption(f"残余缺料日期：{'、'.join(selected_scenario['residual_shortage_dates']) or '无'}；增量成本 {selected_scenario['incremental_cost']:.2f} 元。")
    figure = go.Figure()
    for label, projection, color in [("基准未满足需求", result["inventory_projection"], "#C94A4A"),
                                      ("所选方案未满足需求", selected_scenario["projection"], "#176B5B")]:
        figure.add_scatter(x=[r["date"] for r in projection["daily"]], y=[r["unmet_demand"] for r in projection["daily"]],
                           name=label, mode="lines+markers", line={"color": color})
    figure.update_layout(height=210, margin={"l": 12, "r": 12, "t": 15, "b": 10}, yaxis_title="未满足需求（件）",
                         legend={"orientation": "h", "y": 1.2}, hovermode="x unified",
                         paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(figure, width="stretch",config={'displayModeBar':False}, key="mitigation_inventory_chart")
    st.caption("成本以人民币计，仅比较采购/调拨单价 × 固定数量 + 加急/物流费；原 PO 采购款是各场景共同成本，不重复计入。不含税费、停线损失或安全库存不足罚金。最早日期和资格都是虚构输入条件。")
    with st.expander("方案约束详情与导出"):
        table([{k:v for k,v in row.items() if k in ('candidate_id','eligible','constraint_reasons')} for row in comparison['candidates']])
        st.download_button("下载方案比较 CSV", pd.DataFrame(summary).to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"mitigation_{result['selected_part']['part_code']}.csv", key="download_mitigation_csv")
    return updated
