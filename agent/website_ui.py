"""Production website layout; business computations stay in existing modules."""
from copy import deepcopy
import hashlib
import html
import io
import json
from pathlib import Path
import pandas as pd
import streamlit as st

from batch_analysis import analyze_batch, validate_batch_dataframe, read_batch_file, REQUIRED_COLUMNS, template_xlsx_bytes, template_csv_bytes, batch_results_csv_bytes
from assistant import build_assistant_context
from demo_data import build_rich_batch, blank_part
from localized_ui import table, editor, uploader, column, zh, zh_text, user_error, risk_badge
from supply_data import SCENARIO_NAMES, DEFAULT_SCENARIO_PART_CODES, get_scenario_part

from portfolio_ui import SOURCES, migrate_sources, open_import, overview, reset_source_filters
SITE_UI_VERSION = 14


def shell(mode,app):
    st.markdown((Path(__file__).with_name("site_style.css")).read_text(encoding="utf-8"),unsafe_allow_html=True)
    st.markdown('<header class="site-header"><div class="site-brand"><span class="site-logo">A</span>AutoSupply Copilot</div><small>汽车零部件供应决策 · 中文工作台</small></header>',unsafe_allow_html=True)


def hero(mode,app):
    headings={app.SINGLE_ANALYSIS_MODE:("单物料风险与补货分析","调整库存、需求和交期，判断供应缺口与参考补货量。"),
              app.BATCH_ANALYSIS_MODE:("多物料批量风险分析","按风险排序，找到需要补货与协调交付的物料。"),
              app.PLANNING_ANALYSIS_MODE:("动态物料计划","逐日推算库存，定位缺料日期，比较不同交付情景。")}
    title,description=headings[mode]
    st.markdown(f'<div class="site-hero"><h2>{title}</h2><p>{description}</p></div>',unsafe_allow_html=True)
    st.markdown('<div class="site-flow"><span>① 准备数据</span><span>② 运行分析</span><span>③ 查看风险与建议</span></div>',unsafe_allow_html=True)


def _single_source(app):
    state=st.session_state
    migrate_sources('single')
    # Streamlit removes widget keys when changing modes; restore the independent draft.
    if state.get("site_last_mode")!=app.SINGLE_ANALYSIS_MODE and state.get("single_saved_widgets"):
        for key,value in state["single_saved_widgets"].items():state[key]=value
    state.setdefault("single_source",state.get("single_source_choice",SOURCES[0]))
    if state['single_source'] not in SOURCES[:2]:state['single_source']=SOURCES[0]
    source=st.radio("数据来源",SOURCES[:2],horizontal=True,key="single_source")
    state["single_source_choice"]=source
    return source


def _single_inputs(app,source):
    state=st.session_state
    previous_source=state.get('single_previous_source',SOURCES[0])
    if source!=previous_source:
        state['single_result_source']=None
        state['analysis_error']=''
        state.setdefault('single_source_parameters',{})[previous_source]={k:state[k] for k in ['current_inventory','daily_usage','lead_time_days','supplier','supplier_status','criticality','safety_days','backup_supplier_available'] if k in state}
        cached=state['single_source_parameters'].get(source)
        if cached:
            for key,value in cached.items():state[key]=value
        elif source==SOURCES[1]:
            for key,value in {'current_inventory':0.0,'daily_usage':0.0,'lead_time_days':0.0,'supplier':'','supplier_status':'NORMAL','criticality':'MEDIUM','safety_days':3.0,'backup_supplier_available':False}.items():state[key]=value
        elif source==SOURCES[0]:app._load_input_defaults(state['scenario_preset'],state['part_sku'])
    state['single_previous_source']=source
    if source==SOURCES[0]:
        pair=st.columns(2)
        pair[0].selectbox("演示数据情景",SCENARIO_NAMES,format_func=lambda v:app.SCENARIO_LABELS_ZH[v],key="scenario_preset",on_change=app._on_scenario_change)
        codes,labels=app._part_options(state["scenario_preset"])
        pair[1].selectbox("参考物料",codes,format_func=lambda v:labels[v],key="part_sku",on_change=app._on_part_change)
        state.pop("single_base_part",None)
    elif source==SOURCES[1]:
        st.caption("直接填写自己的业务条件，无需选择演示情景。修改后点击运行。")
        state.setdefault("single_custom_code",state.get("single_custom_code_saved",""))
        state.setdefault("single_custom_name",state.get("single_custom_name_saved",""))
        pair=st.columns(2)
        code=pair[0].text_input("物料编码",key="single_custom_code")
        name=pair[1].text_input("物料名称",key="single_custom_name")
        state["single_custom_code_saved"],state["single_custom_name_saved"]=code,name
        p=blank_part();p.update(part_code=code.strip(),part_name=name.strip())
        state["single_base_part"]=p
    pair=st.columns(2)
    pair[0].number_input("当前库存（件）",min_value=0.0,step=10.0,key="current_inventory")
    pair[1].number_input("日均需求（件）",min_value=0.0,step=1.0,key="daily_usage")
    pair=st.columns(2)
    pair[0].number_input("采购交期（天）",min_value=0.0,step=1.0,key="lead_time_days")
    pair[1].number_input("安全库存天数",min_value=0.0,step=1.0,key="safety_days")
    st.text_input("供应商名称",key="supplier")
    pair=st.columns(2)
    pair[0].selectbox("物料关键程度",app.CRITICALITY_OPTIONS,format_func=zh,key="criticality")
    pair[1].selectbox("供应商状态",app.SUPPLIER_STATUS_OPTIONS,format_func=zh,key="supplier_status")
    st.checkbox("备用供应商可评估",key="backup_supplier_available")
    run=st.button("运行单物料分析",key="run_single_analysis",type="primary",width="stretch")
    keys=['scenario_preset','part_sku','current_inventory','daily_usage','lead_time_days','supplier','supplier_status','criticality','safety_days','backup_supplier_available']
    state['single_saved_widgets']={k:state[k] for k in keys if k in state}
    return source,run


def _static_detail(app,result,chart_key,chart_height=None):
    p=result['selected_part'];risk=result['supplier_risk']['risk_level'];m=result['inventory_metrics']
    st.markdown(f'<div class="result-heading"><div><h3>{html.escape(zh(p["part_name"]))}</h3><small>{html.escape(p["part_code"])} · {html.escape(zh(p["supplier"]))}</small></div>{risk_badge(risk)}</div>',unsafe_allow_html=True)
    cols=st.columns(3)
    cols[0].metric('库存覆盖',app._display_number(m['days_of_stock'],' 天'))
    cols[1].metric('潜在覆盖缺口',app._display_number(m['stockout_gap'],' 天'))
    cols[2].metric('参考补货量',app._display_number(m['recommended_order_qty'],' 件'))
    st.markdown('**未来库存消耗趋势**')
    figure=app._stock_trend_figure(result)
    if chart_height:figure.update_layout(height=chart_height)
    st.plotly_chart(figure,width='stretch',config={'displayModeBar':False},key=chart_key)
    decision=result['replenishment_decision']
    action=zh_text(app.ACTION_LABELS_ZH.get(decision['recommended_action'],decision['recommended_action']))
    quantity=decision['recommended_order_qty']
    action_line=f'{action} · {app._display_number(quantity," 件")}' if quantity else action
    _,explanation=app._risk_conclusion(result)
    secondary='、'.join(zh_text(app.supporting_action_label_zh(item)) for item in decision['supporting_actions'])
    st.markdown(f'<div class="site-advice"><strong>{html.escape(action_line)}</strong><p>{html.escape(explanation)}</p>'+(f'<p>同步措施：{html.escape(secondary)}</p>' if secondary else '')+'</div>',unsafe_allow_html=True)
    st.caption('固定日均需求模型，未纳入在途订单；参考补货量不代表到货前缺口已经解决。')


def _single_footer(app,result):
    report,trace,exports=st.columns(3,gap='medium')
    with report,st.container(key='site_single_report'):
        st.markdown('**管理报告**');st.caption('查看风险判断依据与建议措施。')
        with st.expander('查看管理报告'):
            app._render_report(st.session_state['last_analyzed_input'],result)
            app._render_details(result)
    with trace,st.container(key='site_single_trace'):
        st.markdown('**分析过程**');st.caption('本次四节点工作流的实际执行记录。')
        app._render_trace(result)
    with exports,st.container(key='site_single_export'):
        st.markdown('**结果导出**');st.caption('下载当前分析快照的物料报告。')
        # Keep the existing report generator and its separate download key.
        st.download_button('下载本次物料 PDF',app.build_pdf_report(result),file_name=f"AutoSupply_{result['selected_part']['part_code']}.pdf",key='site_single_pdf',width='stretch')


def render_single(app):
    source=_single_source(app)
    st.session_state.setdefault('single_result_source',SOURCES[0])
    warning=st.empty()
    with st.container(key='single_pair'):
        left,right=st.columns(2,gap="large")
    with left:
        with st.container(key="single_inputs",height='stretch'):
            st.subheader("业务参数")
            source,run=_single_inputs(app,source)
            snapshot=app._current_input_snapshot()
            if source!=SOURCES[0] and st.session_state.get('single_base_part'):
                snapshot.update(part_code=st.session_state['single_base_part']['part_code'],part_name=st.session_state['single_base_part']['part_name'],base_part=deepcopy(st.session_state['single_base_part']),scenario='自行填写业务数据' if source==SOURCES[1] else '导入文件数据')
            if run or (st.session_state.get('last_result') is None and source==SOURCES[0]):
                errors=app._validate_input(snapshot)
                if source!=SOURCES[0] and (not snapshot.get('part_name') or not snapshot['part_code']):errors.append('物料编码和名称不能为空。')
                if source==SOURCES[2] and not st.session_state.get('single_import_signature'):errors.append('请先导入有效文件。')
                if errors:st.session_state['analysis_error']='；'.join(errors)
                else:
                    app._run_automatic_analysis(snapshot)
                    if st.session_state.get('last_result') is not None and not st.session_state.get('analysis_error'):
                        st.session_state['single_result_source']=source
            dirty=snapshot!=st.session_state.get('last_analyzed_input')
            st.session_state['assistant_input_dirty']=dirty
            st.session_state['chat_draft_scope']=('single',source,snapshot)
            if st.session_state.get('analysis_error'):st.error(st.session_state['analysis_error'])
    result=st.session_state.get('last_result') if st.session_state.get('single_result_source')==source else None
    if dirty and result:warning.warning('参数已修改，以下保留上次结果，请点击运行更新。')
    with right:
        with st.container(key="single_results",height='stretch'):
            if result is None:
                st.markdown('<div class="single-waiting"><h3>本次分析结果</h3><span class="waiting-label">等待输入并运行分析</span><div class="waiting-content"><div class="waiting-symbol">→</div><h4>准备好业务参数，即可开始分析</h4><p>填写左侧物料信息、库存、需求和交期，<br>然后点击「运行单物料分析」。</p><div class="waiting-steps"><span>库存覆盖</span><span>供应风险</span><span>补货建议</span></div><small>运行后在此查看真实计算的指标、库存曲线和建议。</small></div></div>',unsafe_allow_html=True)
            else:_static_detail(app,result,'single_stock_trend',chart_height=380)
    if result is None:
        app._synchronize_chat_context(None)
        return
    if result:
        context=build_assistant_context('single',single_result=result);app._synchronize_chat_context(context)
        with st.container(key='site_single_assistant'):app._render_inline_assistant(context,key_suffix='single')
        _single_footer(app,result)


def render_batch(app):
    state=st.session_state
    migrate_sources('batch')
    state.setdefault('batch_source',state.get('batch_source_choice',SOURCES[0]))
    source=st.radio('数据来源',SOURCES,horizontal=True,key='batch_source');state['batch_source_choice']=source
    st.button('导入业务数据',key='batch_import_entry',on_click=open_import,args=('batch',),help='支持 Excel、CSV；导入后可预览并运行分析。')
    if 'batch_demo_rows' not in state:
        scene=state.get('batch_demo_scenario','常规供给')
        state['batch_demo_rows']=build_rich_batch(scene).to_dict('records')
        state['batch_loaded_scene']=scene
    state.setdefault('batch_demo_scenario',state.get('batch_loaded_scene','常规供给'))
    state.setdefault('batch_edit_data',source==SOURCES[1])
    old_source=state.get('batch_workspace_source')
    state.setdefault('batch_result_source',SOURCES[0])
    if source!=old_source:
        if old_source is not None:state['batch_result_source']=None
        reset_source_filters('batch')
        if old_source is not None:state.setdefault('batch_source_drafts',{})[old_source]=deepcopy(state.get('batch_draft_rows',[]))
        state['batch_workspace_source']=source
        saved=state.get('batch_source_drafts',{}).get(source)
        if saved is not None:state['batch_draft_rows']=deepcopy(saved)
        elif source==SOURCES[1]:state['batch_draft_rows']=[]
        elif source==SOURCES[0]:state['batch_draft_rows']=state.get('batch_demo_rows',[])
        else:state['batch_draft_rows']=state.get('batch_file_rows',[])
        state['batch_revision']=state.get('batch_revision',0)+1
        state['batch_upload_error']=''
        state['batch_edit_data']=source==SOURCES[1]
        state['batch_preview_page']=0
        state['batch_validation_attempted']=False
    with st.container(key='batch_upload_panel'):
        st.subheader('准备本次输入数据')
        if source==SOURCES[0]:
            with st.container(key='batch_actions'):
                controls=st.columns((1.4,1,1),vertical_alignment='bottom')
            scenario=controls[0].selectbox('演示数据情景',('常规供给','交付延迟','需求增长','集中缺料'),key='batch_demo_scenario')
            # A persistent container retains its button until the next delta arrives.
            # st.empty() explicitly clears it first, causing a visible flash on rerun.
            run_slot=controls[2].container()
            if controls[1].button('加载参考数据',key='load_batch_demo',width='stretch'):
                state['batch_draft_rows']=build_rich_batch(scenario).to_dict('records');state['batch_demo_rows']=deepcopy(state['batch_draft_rows']);state['batch_revision']=state.get('batch_revision',0)+1
                state['batch_loaded_scene']=scenario
                state['batch_preview_page']=0;state['batch_validation_attempted']=False
            example=build_rich_batch(scenario)
        elif source==SOURCES[2]:
            uploaded=uploader('上传批量数据',types=('xlsx','csv'),key='batch_upload')
            run_slot=st.container()
            if uploaded:
                signature=hashlib.sha256(uploaded.getvalue()).hexdigest()
                if signature!=state.get('batch_file_signature'):
                    try:
                        frame=read_batch_file(uploaded.name,uploaded.getvalue());normalized,errors=validate_batch_dataframe(frame)
                        if errors:state['batch_upload_error']='；'.join(errors)
                        else:
                            state['batch_upload_error']=''
                            state['batch_draft_rows']=normalized.to_dict('records');state['batch_file_rows']=deepcopy(state['batch_draft_rows']);state['batch_file_signature']=signature;state['batch_revision']=state.get('batch_revision',0)+1
                    except Exception as exc:state['batch_upload_error']=f'文件读取失败：{exc}'
            example=build_rich_batch('常规供给')
        else:
            st.caption('新增物料并填写库存、日均需求、交期和供应商，不必选择演示情景。最多50种物料。')
            run_slot=st.container()
            example=build_rich_batch('常规供给')
        downloads=st.columns(2)
        buffer=io.BytesIO();example.to_excel(buffer,index=False)
        downloads[0].download_button('下载带数据的 Excel 示例',buffer.getvalue(),file_name='autosupply_batch_demo.xlsx',key='download_xlsx_template')
        downloads[1].download_button('下载 CSV 示例',example.to_csv(index=False).encode('utf-8-sig'),file_name='autosupply_batch_demo.csv',key='download_csv_template')
        columns=[column(n,kind='select' if n in ('criticality','supplier_status') else 'number' if n in ('current_stock','daily_usage','lead_time_days','safety_days') else 'text',choices=app.CRITICALITY_OPTIONS if n=='criticality' else app.SUPPLIER_STATUS_OPTIONS if n=='supplier_status' else None) for n in ['part_code','part_name','supplier','current_stock','daily_usage','lead_time_days','safety_days','criticality','supplier_status']]
        st.caption(f"当前输入：{len(state.get('batch_draft_rows',[]))}种物料。先核对数据，再运行分析；修改不会覆盖上次结果。")
        with st.container(key='batch_view_options'):
            flags=st.columns(2,vertical_alignment='center')
            editing=flags[0].toggle('编辑本次输入数据',key='batch_edit_data',disabled=source==SOURCES[1])
            full_preview=flags[1].toggle('全部预览输入数据',key='batch_preview_all',disabled=editing,help='完整字段逐页预览，所有表格固定每页10行。')
        if editing:
            rows=editor(state.get('batch_draft_rows',[]),columns,key=f"batch_editor_{state.get('batch_revision',0)}",add=source==SOURCES[1],defaults=blank_part())
        else:
            rows=state.get('batch_draft_rows',[])
            fields=['part_code','part_name','supplier','current_stock','daily_usage','lead_time_days','safety_days','criticality','supplier_status'] if full_preview else ['part_code','part_name','supplier','current_stock','daily_usage','lead_time_days']
            st.caption('表格每页10行；开启全部预览可查看完整业务字段，翻页浏览其余物料。')
            table(rows,columns=fields,key='batch_input_preview')
        state['batch_draft_rows']=rows
        normalized,errors=validate_batch_dataframe(pd.DataFrame(rows))
        if state.get('batch_upload_error'):st.error(state['batch_upload_error'])
        scene_pending=source==SOURCES[0] and bool(rows) and state.get('batch_loaded_scene')!=state.get('batch_demo_scenario')
        if scene_pending:st.warning('演示情景尚未加载，当前草稿和上次结果保持不变，请先点击加载参考数据。')
        run=run_slot.button('运行批量分析',type='primary',disabled=bool(state.get('batch_upload_error')) or scene_pending,key='start_batch_analysis',width='stretch')
        if run:state['batch_validation_attempted']=True
        if errors and state.get('batch_validation_attempted'):
            st.error(user_error('；'.join(errors[:3])))
            if len(errors)>3:
                with st.expander(f'查看全部{len(errors)}项输入问题'):st.write(user_error('；'.join(errors)))
        elif rows and errors:st.caption('草稿还有待填写的内容，填写完成后运行；分析前会校验必填项、数值和重复编码。')
        if run and not errors and normalized is not None:
            with st.spinner('正在逐项执行四节点分析…'):state['batch_result']=analyze_batch(normalized)
            state['batch_analyzed_rows']=deepcopy(rows)
            state['batch_result_source']=source
        if state.get('batch_result_source')==source and state.get('batch_result') and rows!=state.get('batch_analyzed_rows'):st.warning('数据已变更，以下保留上次分析结果，请重新运行。')
    result=state.get('batch_result') if state.get('batch_result_source')==source else None
    state['assistant_input_dirty']=rows!=state.get('batch_analyzed_rows') or scene_pending
    state['chat_draft_scope']=('batch',source,state.get('batch_demo_scenario'),rows)
    if not result:app._synchronize_chat_context(None);st.info('等待输入并运行分析：请先核对上方数据，再点击「运行批量分析」。');return
    st.subheader('本次分析结果')
    summary=result['summary'];counts=summary.risk_level.value_counts();cols=st.columns(3)
    cols[0].metric('分析物料',result['total_count']);cols[1].metric('高风险物料',int(counts.get('HIGH',0)));cols[2].metric('分析失败',result['failure_count'])
    selected=overview(result['details'],prefix='batch',selected_key='batch_selected_sku',display_frame=app._prepare_batch_display_frame(summary))
    if selected is None:app._synchronize_chat_context(None);return
    state['chat_draft_scope']+=(state.get('batch_risk_filter'),state.get('batch_search'))
    with st.container(key='batch_pair'):
        left,right=st.columns(2,gap='large')
    state.setdefault('batch_detail_open',False)
    with right,st.container(key='batch_right_panel',height='stretch'):
        with st.container(key='batch_selected_detail'):_static_detail(app,result['details'][selected],'batch_stock_trend',chart_height=380)
    context=build_assistant_context('batch',batch_result=result,selected_part_code=selected);app._synchronize_chat_context(context)
    with left,st.container(key='batch_left_panel',height='stretch'):
        with st.container(key='batch_priority_panel'):
            st.markdown('**物料风险优先级**')
            st.plotly_chart(app._batch_priority_figure(summary),width='stretch',config={'displayModeBar':False},key='batch_priority_chart')
        with st.container(key='batch_assistant_panel'):app._render_batch_assistant(context)
    report,trace,exports=st.columns(3,gap='medium');detail=result['details'][selected]
    with report,st.container(key='site_batch_report'):
        st.markdown('**管理报告**');st.caption('查看选中物料的风险依据与建议措施。')
        with st.expander('查看完整管理报告'):
            st.markdown(zh_text(detail['management_report']).replace('\n','\n\n'));app._render_details(detail)
    with trace,st.container(key='site_batch_trace'):
        st.markdown('**分析过程**');st.caption('本次四节点工作流的实际执行记录。');app._render_trace(detail)
    with exports,st.container(key='site_batch_export'):
        st.markdown('**结果导出**');st.caption('导出本次结果表与选中物料报告。')
        st.download_button('导出批量风险结果 CSV',batch_results_csv_bytes(result),file_name='autosupply_batch_results.csv',key='download_batch_results',width='stretch')
        st.download_button('下载该物料 PDF 报告',app.build_pdf_report(detail),file_name=f'AutoSupply_{selected}.pdf',key='download_batch_pdf',width='stretch')
