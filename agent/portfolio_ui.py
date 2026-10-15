"""Shared multi-material overview; all metrics come from Python analysis."""
import html
import math
import streamlit as st
from localized_ui import zh, table, risk_badge

SOURCES = ('演示数据', '业务数据录入', '文件导入')
PORTFOLIO_UI_VERSION = 5
OLD_SOURCES = dict(zip(('体验演示数据','填写我的业务数据','导入文件'), SOURCES))


def migrate_sources(prefix):
    state = st.session_state
    for name in (f'{prefix}_source', f'{prefix}_source_choice', f'{prefix}_workspace_source', f'{prefix}_previous_source'):
        if name in state:
            state[name] = OLD_SOURCES.get(state[name], state[name])
    for key in (f'{prefix}_source_drafts', f'{prefix}_source_parameters'):
        if key in state:
            state[key] = {OLD_SOURCES.get(k,k): v for k,v in state[key].items()}


def open_import(prefix):
    st.session_state[f'{prefix}_source'] = SOURCES[2]


def reset_source_filters(prefix):
    """A previous source's search must not conceal the next source's new results."""
    state=st.session_state
    for suffix,value in (('risk_filter','全部'),('search','')):
        state[f'{prefix}_{suffix}']=value
        state[f'{prefix}_{suffix}_choice']=value
    state[f'{prefix}_overview_page']=0
    state.pop(f'{prefix}_filter_scope',None)


def open_detail(prefix):
    st.session_state[f'{prefix}_detail_open'] = True


def _sparkline(values, color):
    if not values:
        return ''
    minimum, maximum = min(values), max(values)
    scale = max(1, maximum-minimum)
    points = ' '.join(f'{i*280/max(1,len(values)-1):.1f},{50-(v-minimum)*44/scale:.1f}' for i,v in enumerate(values))
    return f'<svg viewBox="0 0 280 56" width="100%" height="56" aria-label="库存趋势"><polyline fill="none" stroke="{color}" stroke-width="2.5" points="{points}"/></svg>'


def filtered_codes(details, risk='全部', search=''):
    wanted = {'高风险':'HIGH','中风险':'MEDIUM','低风险':'LOW'}.get(risk)
    return [code for code,result in details.items()
            if (not wanted or result['supplier_risk']['risk_level'] == wanted)
            and search.casefold() in ' '.join(str(zh(result['selected_part'].get(k,''))) for k in ('part_code','part_name','supplier')).casefold()]


def order_totals(projection):
    start = projection['start_date']
    end = projection['daily'][-1]['date']
    confirmed = projection['confirmed_orders']
    return {'confirmed': sum(o['open_quantity'] for o in confirmed if o['arrival_date'] >= start),
            'in_period': sum(o['open_quantity'] for o in confirmed if start <= o['arrival_date'] <= end),
            'pending': sum(o['open_quantity'] for o in projection['excluded_orders'] if o['status']=='PENDING' and o['arrival_date']>=start)}


def overview(details, *, prefix, selected_key, display_frame):
    state = st.session_state
    st.markdown('**多物料风险总览**')
    counts = {v: sum(r['supplier_risk']['risk_level']==v for r in details.values()) for v in ('HIGH','MEDIUM','LOW')}
    labels = {'全部':len(details),'高风险':counts['HIGH'],'中风险':counts['MEDIUM'],'低风险':counts['LOW']}
    for suffix,default in [('risk_filter','全部'),('search',''),('overview_view','卡片'),('show_all',False)]:
        state.setdefault(f'{prefix}_{suffix}',state.get(f'{prefix}_{suffix}_choice',default))
    risk = st.radio('风险筛选', list(labels), horizontal=True, format_func=lambda v:f'{v}（{labels[v]}）', key=f'{prefix}_risk_filter')
    controls = st.columns((2,1,1))
    search = controls[0].text_input('搜索物料编码、名称或供应商', key=f'{prefix}_search', placeholder='输入关键词')
    view = controls[1].selectbox('展示方式', ('卡片','表格'), key=f'{prefix}_overview_view')
    all_rows = controls[2].toggle('全部展示', key=f'{prefix}_show_all',disabled=view=='表格',help='仅适用于卡片；表格固定每页10行。')
    for suffix in ('risk_filter','search','overview_view','show_all'):
        state[f'{prefix}_{suffix}_choice']=state[f'{prefix}_{suffix}']
    codes = filtered_codes(details,risk,search.strip())
    if not codes:
        st.info('没有符合条件的物料，请调整筛选条件。')
        return None
    scope = (risk,search)
    if state.get(f'{prefix}_filter_scope') != scope:
        state[f'{prefix}_filter_scope'] = scope
        state[f'{prefix}_overview_page'] = 0
    if state.get(selected_key) not in codes:
        saved = state.get(f'{prefix}_viewed_sku')
        state[selected_key] = saved if saved in codes else codes[0]
    page = min(state.get(f'{prefix}_overview_page',0), (len(codes)-1)//6)
    shown = codes if all_rows else codes[page*6:page*6+6]
    if view == '表格':
        frame = display_frame
        code_col = 'SKU' if 'SKU' in frame else '物料编码'
        table(frame[frame[code_col].isin(codes)], key=f'{prefix}_risk_table' if prefix=='batch' else 'planning_risks')
    else:
        for offset in range(0,len(shown),3):
            cols = st.columns(3)
            for col,code in zip(cols,shown[offset:offset+3]):
                result = details[code]; part = result['selected_part']; level = result['supplier_risk']['risk_level']
                projection = result.get('inventory_projection')
                with col, st.container(key=f'{prefix}_card_{code}'):
                    heading = f'<div class="result-heading"><div><strong>{html.escape(zh(part["part_name"]))}</strong><small>{html.escape(code)}</small></div>{risk_badge(level)}</div>'
                    if projection:
                        totals = order_totals(projection)
                        values = [projection['initial_available']] + [r['closing_available'] for r in projection['daily']]
                        facts = f"<span>期初库存 <b>{projection['initial_available']}件</b></span><span>本期确认到货 <b>{totals['in_period']}件</b></span><span>已确认未到货 <b>{totals['confirmed']}件</b></span><span>待确认数量 <b>{totals['pending']}件</b></span><span>首次缺料 <b>{projection['first_shortage_date'] or '本期无'}</b></span><span>未满足需求 <b>{projection['total_unmet_demand']}件</b></span>"
                    else:
                        m = result['inventory_metrics']; stock, usage = part['current_stock'],part['daily_usage']
                        values = [max(0, stock-usage*i) for i in range(15)]
                        coverage = '无消耗' if math.isinf(m['days_of_stock']) else f"{m['days_of_stock']:.2f}天"
                        facts = f"<span>库存覆盖 <b>{coverage}</b></span><span>潜在缺口 <b>{m['stockout_gap']:.2f}天</b></span><span>参考补货 <b>{m['recommended_order_qty']}件</b></span>"
                    color = {'HIGH':'#c94a4a','MEDIUM':'#c88b35','LOW':'#23836b'}[level]
                    st.markdown(heading + '<div class="card-facts">'+facts+'</div>'+_sparkline(values,color), unsafe_allow_html=True)
                    if st.button('查看物料详析',key=f'{prefix}_open_{code}',width='stretch'):
                        state[selected_key] = code
                        state[f'{prefix}_detail_open'] = True
    if not all_rows and view=='卡片':
        prev,info,next_button = st.columns((1,3,1))
        if prev.button('上一组',key=f'{prefix}_overview_previous',disabled=page==0):
            state[f'{prefix}_overview_page']=page-1;st.rerun()
        info.caption(f'筛选后{len(codes)}种物料 · 第{page+1}/{(len(codes)+5)//6}页，每页6种')
        if next_button.button('下一组',key=f'{prefix}_overview_next',disabled=(page+1)*6>=len(codes)):
            state[f'{prefix}_overview_page']=page+1;st.rerun()
    selected = st.selectbox('选择物料查看详析',codes,format_func=lambda v:f"{v} · {zh(details[v]['selected_part']['part_name'])}",key=selected_key,on_change=open_detail,args=(prefix,))
    state[f'{prefix}_viewed_sku'] = selected
    return selected
