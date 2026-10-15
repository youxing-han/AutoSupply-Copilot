"""Chinese production planning workbench with explicit data-source separation."""
from copy import deepcopy
import hashlib
import html
import plotly.graph_objects as go
from datetime import date
import pandas as pd
import streamlit as st

from demo_data import RICH_SCENARIOS,SCENE_LABELS,build_rich_planning,blank_part,custom_plan
from localized_ui import table,editor,uploader,column,zh,zh_text,risk_badge
from planning_data import build_interview_demo,planning_xlsx_bytes,analyze_planning_bundle,normal_arrival_baseline,PlanningInputError
from planning_workspace import fingerprint,analysis_totals,risk_overview_rows
from inventory_planning import day
from assistant import build_assistant_context
from mitigation_ui import render_mitigation
from report_pdf import build_pdf_report
from portfolio_ui import SOURCES, migrate_sources, open_import, overview, order_totals, reset_source_filters
from planning_demand_ui import render_demands

PLANNING_SITE_VERSION = 12


def render_priority(analysis):
    rows=risk_overview_rows(analysis)
    shortages=[r for r in rows if r['累计未满足需求']>0]
    warnings=[r for r in rows if r['累计未满足需求']==0 and r['安全库存预警天数']>0]
    st.markdown('**物料风险摘要**')
    if shortages:
        st.caption('下图按预测周期内累计未满足需求排序：柱越长，计划中未能满足的需求越多；不代表当前库存为负或已经停线。')
        figure=go.Figure(go.Bar(x=[r['累计未满足需求'] for r in shortages],
                              y=[f"{r['SKU']} · {zh(r['名称'])}" for r in shortages],orientation='h',
                              marker_color=[{'HIGH':'#C94A4A','MEDIUM':'#C88B35','LOW':'#23836B'}[r['风险']] for r in shortages],
                              text=[r['累计未满足需求'] for r in shortages],textposition='auto'))
        figure.update_layout(height=min(350,130+len(shortages)*28),margin={'l':5,'r':12,'t':8,'b':12},
                             paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
                             xaxis_title='累计未满足需求（件）',xaxis={'rangemode':'tozero'},
                             yaxis={'autorange':'reversed','automargin':True})
        st.plotly_chart(figure,width='stretch',config={'displayModeBar':False},key='planning_priority_chart')
    else:
        settings=analysis['bundle']['settings'][0]
        st.success(f"本次{settings['horizon_days']}天预测内，{len(rows)}种物料均未出现数量短缺。")
        st.caption('累计未满足需求全部为0，因此不绘制空柱状图。无数量短缺不代表没有安全库存或供应商风险。')
    if warnings:
        st.markdown(f'**{len(warnings)}种物料有安全库存预警，尚未出现数量短缺**')
        table(warnings,columns=['SKU','名称','安全库存预警天数'],key='planning_buffer_warnings')
    supplier_only=[r for r in rows if not r['累计未满足需求'] and not r['安全库存预警天数'] and r['供应商状态']!='NORMAL']
    if supplier_only:st.caption(f"另有{len(supplier_only)}种物料存在供应商状态预警，当前计划未出现数量短缺或安全库存不足。")


def edit_data(helper,workspace,source):
    draft=deepcopy(st.session_state.get('planning_draft',workspace['bundle']))
    tabs=st.tabs(['物料与库存','逐日需求','采购到货','供应商与模板'])
    custom=source==SOURCES[1]
    with tabs[0]:
        columns=[column(n,editable=custom or n in ('current_stock','safety_days','criticality'),kind='select' if n in ('criticality','supplier_status') else 'number' if n in ('current_stock','safety_days') else 'text',choices=('LOW','MEDIUM','HIGH') if n=='criticality' else ('NORMAL','DELAYED','AT_RISK','DISRUPTED','STOPPED','UNAVAILABLE') if n=='supplier_status' else None) for n in ['part_code','part_name','supplier','current_stock','safety_days','criticality','supplier_status']]
        defaults=blank_part();defaults['lead_time_days']=None
        draft['parts']=editor(draft['parts'],columns,key=f"planning_editor_parts_{workspace['revision']}",add=custom,defaults=defaults)
        st.caption('日均需求由完整逐日计划自动计算；库存按逐日需求与订单日期推算，不要求填写日均需求或标准交期。安全天数是可调整的策略参数，默认3天。')
        if custom:
            st.caption('填写物料后，建立完整需求表，再到“逐日需求”按实际计划编辑。重建会覆盖旧需求，订单保留。')
            if st.button('建立或重建逐日需求表（初始全为0）',key='generate_custom_demands',help='主动建立零需求草稿，请逐日填写后再分析；不会将上传文件的缺失需求自动补0。'):
                parts=deepcopy(draft['parts'])
                for p in parts:p['daily_usage']=0
                rebuilt=custom_plan(parts,st.session_state['planning_start'],st.session_state['planning_horizon'])
                rebuilt['orders']=draft['orders'];helper._replace_workspace(rebuilt,'自行填写的业务数据',helper._controls());st.rerun()
    with tabs[1]:
        draft['demands']=render_demands(draft,workspace['revision'])
    with tabs[2]:
        st.caption('已确认订单按日期计入；待确认和已取消订单不计入库存。修改预计日期不改变原定日期。')
        first=draft['parts'][0] if draft['parts'] else blank_part()
        defaults={'po_id':'','part_code':first['part_code'],'supplier':first['supplier'],'open_quantity':0,'arrival_date':st.session_state['planning_start'].isoformat(),'original_arrival_date':st.session_state['planning_start'].isoformat(),'status':'PENDING'}
        columns=[column('po_id',editable=custom),column('part_code',editable=custom),column('supplier',editable=custom),column('open_quantity',kind='number'),column('arrival_date',kind='date'),column('original_arrival_date',editable=custom,kind='date'),column('status',kind='select',choices=('CONFIRMED','PENDING','CANCELLED'))]
        draft['orders']=editor(draft['orders'],columns,key=f"planning_editor_orders_{workspace['revision']}",add=custom,defaults=defaults,filter_column=None if custom else 'part_code')
    with tabs[3]:
        if custom:
            st.session_state.setdefault('custom_suppliers_qualified',bool(draft['suppliers']) and all(s.get('qualified',False) for s in draft['suppliers']))
            qualified=st.checkbox('上述采购来源已完成供应资格核验',key='custom_suppliers_qualified',help='未核验来源不能用于已确认采购到货。')
            draft['suppliers']=list({p['supplier']:{'supplier':p['supplier'],'lead_time_days':p['lead_time_days'],'status':p['supplier_status'],'qualified':qualified} for p in draft['parts'] if p['supplier']}.values())
        table(draft['suppliers'])
        valid=build_interview_demo(st.session_state['planning_start'],st.session_state['planning_horizon'])
        st.download_button('下载空白 Excel 模板',planning_xlsx_bytes(valid,named_sheets=True,blank=True),file_name='autosupply_dynamic_blank.xlsx',key='download_planning_blank')
        st.caption('空白模板需填写后导入；带数据的示例可直接运行。内部字段名保留兼容，页面均以中文显示。')
    return draft


def render(helper,render_trace,render_assistant,synchronize_chat):
    helper._initialize_workspace();state=st.session_state
    migrate_sources('planning')
    state.setdefault('planning_source',state.get('planning_source_choice',SOURCES[0]))
    source=st.radio('数据来源',SOURCES,horizontal=True,key='planning_source');state['planning_source_choice']=source
    st.button('导入业务数据',key='planning_import_entry',on_click=open_import,args=('planning',),help='上传多工作表 Excel，预览库存、逐日需求和采购订单后运行。')
    state.setdefault('planning_result_source',SOURCES[0])
    if source!=state.get('planning_workspace_source',SOURCES[0]):
        state['planning_result_source']=None
        reset_source_filters('planning')
        for key in ('planning_input_error','planning_internal_error','planning_internal_trace'):
            state.pop(key,None)
        previous=state.get('planning_workspace_source',SOURCES[0]);state.setdefault('planning_source_drafts',{})[previous]=deepcopy(state['planning_draft'])
        stored=state['planning_source_drafts'].get(source)
        if stored is None and source in SOURCES[1:]:stored=custom_plan([],state['planning_start'],state['planning_horizon'])
        if stored is not None:helper._replace_workspace(stored,source,helper._controls())
        state['planning_workspace_source']=source
    with st.container(key='planning_data_panel'):
        st.subheader('准备本次输入数据')
        if source==SOURCES[2]:
            upload=uploader('上传动态计划 Excel',key='planning_upload')
            if upload:
                signature=hashlib.sha256(upload.getvalue()).hexdigest()
                if signature!=state.get('planning_import_signature'):
                    helper._import_upload(upload)
                    if not state.get('planning_upload_error'):state['planning_import_signature']=signature
            else:st.info('上传只加载数据，不自动分析。可先下载带数据示例，在 Excel 中修改后上传。')
        controls=st.columns((1.3,1.2,1,0.7) if source==SOURCES[0] else (1,1))
        if source==SOURCES[0]:
            state.setdefault('planning_data_pack',state.get('planning_loaded_pack','多物料排产 · 12种物料'))
            controls[0].selectbox('参考数据',('多物料排产 · 12种物料','公式核验 · 5种物料'),key='planning_data_pack')
            scenarios=RICH_SCENARIOS if state['planning_data_pack'].startswith('多物料') else RICH_SCENARIOS[:4]
            if state['planning_scenario'] not in scenarios:state['planning_scenario']='正常到货'
            controls[1].selectbox('演示数据情景',scenarios,format_func=lambda v:SCENE_LABELS[v],key='planning_scenario')
            offset=2
        else:offset=0
        controls[offset].date_input('预测首日',key='planning_start')
        controls[offset+1].number_input('预测天数',min_value=1,max_value=90,key='planning_horizon')
        state['planning_controls_choice']=helper._controls()
        pack=state.get('planning_data_pack','多物料排产 · 12种物料')
        example=build_rich_planning(state['planning_start'],state['planning_horizon'],state['planning_scenario']) if pack.startswith('多物料') else build_interview_demo(state['planning_start'],state['planning_horizon'],state['planning_scenario'] if state['planning_scenario'] in RICH_SCENARIOS[:4] else '正常到货')
        actions=st.columns(3)
        if source==SOURCES[0]:actions[0].button('加载演示数据',key='load_planning_demo',on_click=helper._load_demo,width='stretch')
        else:actions[0].caption('直接填写库存、需求和订单，不需要选择演示情景。' if source==SOURCES[1] else '上传文件的预测设置优先生效。')
        actions[1].download_button('下载带数据的 Excel 示例',planning_xlsx_bytes(example,named_sheets=True),file_name='autosupply_dynamic_demo.xlsx',key='download_planning_template',width='stretch')
        workspace=state['planning_workspace']
        controls_changed=workspace['controls']!=helper._controls() or (source==SOURCES[0] and state.get('planning_loaded_pack')!=pack)
        if controls_changed:st.warning('选择尚未应用：演示数据请点击加载；自行填写请重建逐日计划以应用新周期。当前草稿仍保留。')
        if state.get('planning_upload_error'):st.error(state['planning_upload_error'])
        run=actions[2].button('运行动态分析',key='run_planning_analysis',type='primary',width='stretch',disabled=controls_changed or bool(state.get('planning_upload_error')))
        st.caption(f"当前数据：{workspace['source']} · {len(state['planning_draft']['parts'])}种物料。先收货后消耗；待确认不计入；缺口不自动结转。")
        draft=edit_data(helper,workspace,source)
    state['planning_draft']=draft
    state['chat_draft_scope']=('planning',source,helper._controls(),fingerprint(draft))
    if run:
        helper._run_analysis(draft,workspace['source'])
        if not state.get('planning_input_error') and not state.get('planning_internal_error'):
            state['planning_result_source']=source
    for key in ('planning_input_error','planning_internal_error'):
        if state.get(key):st.error(state[key])
    from runtime_mode import is_public_demo
    if state.get('planning_internal_trace') and not is_public_demo():
        with st.expander('工作流诊断信息'):st.code(state['planning_internal_trace'])
    analysis=state.get('planning_analysis') if state.get('planning_result_source')==source else None
    if analysis is None:
        synchronize_chat(None)
        st.info('等待输入并运行分析：请先核对上方库存、逐日需求和采购订单，再点击「运行动态分析」。')
        return
    dirty=fingerprint(draft)!=state['planning_analysis_fingerprint'] or controls_changed
    state['planning_results_dirty']=dirty
    state['assistant_input_dirty']=dirty
    if dirty:st.warning('数据已变更，以下保留上次成功分析结果，请重新运行后更新。')
    st.subheader('本次分析结果')
    st.caption(f"分析快照：{state['planning_analysis_source']} · {analysis['bundle']['settings'][0]['start_date']}起，{analysis['bundle']['settings'][0]['horizon_days']}天")
    totals=analysis_totals(analysis)
    with st.container(key='planning_summary_metrics'):
        cols=st.columns(4)
        cols[0].metric('分析物料',f"{totals['sku_count']} 种")
        cols[1].metric('预计缺料物料',f"{totals['shortage_sku_count']} 种")
        cols[2].metric('首次预计缺料',totals['first_shortage_date'] or '本期无')
        cols[3].metric('累计未满足需求',f"{totals['total_unmet_demand']} 件")
    st.caption('未满足需求是各物料件数合计，不等于车辆产量损失。')
    ordered_details={sku:analysis['details'][sku] for sku in analysis['summary']['SKU']}
    sku=overview(ordered_details,prefix='planning',selected_key='planning_sku',display_frame=analysis['summary'])
    if sku is None:synchronize_chat(None);return
    state['chat_draft_scope']+=(state.get('planning_risk_filter'),state.get('planning_search'))
    result=analysis['details'][sku];projection=result['inventory_projection']
    with st.container(key='planning_context_row'):
        left,right=st.columns(2,gap='large')
    state.setdefault('planning_detail_open',False)
    with st.expander('单物料详析',key='planning_detail_open',on_change='rerun'):
        with st.container(key='planning_result_panel'):
            st.markdown(f'<div class="result-heading"><div><h3>{html.escape(zh(result["selected_part"]["part_name"]))}</h3><small>{html.escape(sku)} · {html.escape(zh(result["selected_part"]["supplier"]))}</small></div>{risk_badge(result["supplier_risk"]["risk_level"])}</div>',unsafe_allow_html=True)
            c=st.columns(3)
            c[0].metric('首次短缺',projection['first_shortage_date'] or '本期无')
            c[1].metric('未满足需求',f"{projection['total_unmet_demand']} 件")
            c[2].metric('期末可用库存',f"{projection['final_available']} 件")
            incoming=order_totals(projection)
            table([{'期初可用库存（件）':projection['initial_available'],'已确认未到货（件）':incoming['confirmed'],'本期确认到货（件）':incoming['in_period'],'待确认数量（件）':incoming['pending']}],key='planning_supply_position')
            all_orders=projection['confirmed_orders']+projection['excluded_orders']
            period_orders=[o for o in all_orders if projection['daily'][0]['date']<=o['arrival_date']<=projection['daily'][-1]['date']]
            trend,arrivals=st.tabs(['库存变化与风险','采购到货明细'])
            with trend:
                st.markdown('**逐日期末可用库存**')
                st.plotly_chart(helper.inventory_figure(result),width='stretch',config={'displayModeBar':False},key='planning_inventory_chart')
                for reason in result['supplier_risk']['reasons']:st.caption(zh_text(reason))
            with arrivals:
                table(period_orders,columns=['po_id','supplier','arrival_date','open_quantity','status','delivery_status'],key='planning_selected_orders')
                if len(all_orders)>len(period_orders):st.caption(f"本期外还有{len(all_orders)-len(period_orders)}笔订单，可在完整报告中查看。")
                st.caption('已确认未到货含预测期外订单；本期确认到货为其中本周期预计收货的部分。订单确认不等于已发运，当前未接入承运商物流。待确认和已取消不计入库存。')
    with st.expander('场景与应急方案比较'):
        compare=st.checkbox('比较正常到货基准（保留当前库存、需求和订单量）',value=state.get('planning_compare_choice',True),key='planning_compare_normal');state['planning_compare_choice']=compare
        if compare:
            st.caption('按原计划到货对照：保留库存、需求和数量；未取消订单恢复原始日期，并假设已确认。这是比较假设，不是到货保证。')
            try:
                if 'normal_baseline' not in analysis:analysis['normal_baseline']=analyze_planning_bundle(normal_arrival_baseline(analysis['bundle']))
                reference=analysis['normal_baseline']['details'][sku]
                rows=[]
                for label,item in [('当前计划',result),('按原计划到货',reference)]:
                    p=item['inventory_projection'];rows.append({'场景':label,'首次缺料':p['first_shortage_date'] or '无','累计未满足需求':p['total_unmet_demand'],'期末库存':p['final_available']})
                table(rows);st.plotly_chart(helper.inventory_figure(result,reference),width='stretch',config={'displayModeBar':False},key='planning_compare_chart')
            except (PlanningInputError,ValueError) as exc:st.warning(f'无法建立对照：{exc}')
        if st.checkbox('展开供应应急方案比较',key='planning_show_mitigation'):result=render_mitigation(result)
    state['planning_selected_result']=result
    context=build_assistant_context('single',single_result=result);synchronize_chat(context)
    with left:
        with st.container(key='planning_priority_panel',height='stretch'):render_priority(analysis)
    with right:
        with st.container(key='planning_assistant_panel',height='stretch'):render_assistant(context,key_suffix='planning')
    report,trace,exports=st.columns(3,gap='medium')
    with report,st.container(key='site_planning_report'):
        st.markdown('**管理报告**');st.caption('查看本物料的结论、逐日库存和缺料依据。')
        with st.expander('查看完整动态报告'):
            st.markdown(zh_text(result['management_report']))
            table(projection['daily']);table(projection['risk_windows']);table(all_orders)
    with trace,st.container(key='site_planning_trace'):
        st.markdown('**分析过程**');st.caption('本次四节点工作流的实际执行记录。');render_trace(result)
    with exports,st.container(key='site_planning_export'):
        st.markdown('**结果导出**');st.caption('下载本次动态风险表和选中物料报告。')
        st.download_button('下载动态风险汇总 CSV',analysis['summary'].to_csv(index=False).encode('utf-8-sig'),file_name='dynamic_risks.csv',key='download_planning_csv',width='stretch')
        st.download_button('下载动态 PDF 报告',build_pdf_report(result),file_name=f'planning_{sku}.pdf',key='download_planning_pdf',width='stretch')
