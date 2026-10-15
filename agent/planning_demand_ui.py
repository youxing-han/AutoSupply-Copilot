"""Chinese demand calendar backed by the canonical long demand table."""
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
from localized_ui import editor, editor_rows, column, table
from planning_calendar import demand_grid, natural_weeks

DEMAND_UI_VERSION = 2

_calendar = components.declare_component('autosupply_demand_calendar', path=str(Path(__file__).with_name('demand_calendar')))


def render_demands(bundle, revision):
    settings = bundle['settings'][0]
    key = f'planning_editor_demands_{revision}'
    pending = st.session_state.get(key)
    rows = editor_rows(pending, bundle['demands'])
    parts = bundle['parts']
    weeks = natural_weeks(settings['start_date'], settings['horizon_days'])
    controls = st.columns((1.5, 1.5, 1))
    options = ['全部物料'] + [p['part_code'] for p in parts]
    if st.session_state.get('demand_view_sku') not in options:
        st.session_state['demand_view_sku'] = options[0]
    sku = controls[0].selectbox('筛选需求物料', options, key='demand_view_sku')
    week_key = f'demand_calendar_week_{revision}'
    index = controls[1].selectbox('自然周', list(range(len(weeks))),
                                format_func=lambda i: f"{weeks[i][0]['date']} — {weeks[i][-1]['date']}", key=week_key)
    editing = controls[2].toggle('编辑需求', key='demand_calendar_editing')
    st.caption('固定周一至周日。灰色0为非预测期，仅作占位；停产日请明确填0，缺失需求显示“待填”。修改后需重新分析。')
    view = st.radio('需求展示', ['周计划矩阵', '明细列表'], horizontal=True, key='demand_calendar_view')
    if view == '明细列表':
        if editing:
            updated = editor(rows, [column('part_code', editable=False), column('date', editable=False), column('quantity', kind='number')],
                             key=key+'_list', filter_column='part_code')
            if updated != rows:
                st.session_state[key] = {'rows':updated,'edit_id':(pending or {}).get('edit_id',0)+1}
            return updated
        table([r for r in rows if sku == options[0] or r['part_code'] == sku], key='demand_long_preview')
        return rows
    grid = demand_grid(parts, rows, settings['start_date'], settings['horizon_days'], index,
                       None if sku == options[0] else sku)
    st.session_state.pop(key+'_list',None)
    value = _calendar(grid=grid, rows=rows, editing=editing,
                      editRevision=pending.get('edit_id',0) if isinstance(pending,dict) else 0,
                      default={'rows': rows}, key=key)
    return editor_rows(value, rows)
