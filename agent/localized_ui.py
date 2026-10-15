"""Chinese tables, safe JSON editor and file uploader; no vendor grid menus."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import html
import hashlib
import inspect
from pathlib import Path
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
LOCALIZED_UI_VERSION = 5
TABLE_PAGE_SIZE = 10

_widget = components.declare_component("autosupply_chinese_controls", path=str(Path(__file__).with_name("chinese_controls")))
ENUMS = {"LOW":"低", "MEDIUM":"中", "HIGH":"高", "NORMAL":"正常交付", "DELAYED":"交付延迟",
         "AT_RISK":"存在风险", "DISRUPTED":"供应中断", "STOPPED":"停止供货", "UNAVAILABLE":"暂无供给",
         "CONFIRMED":"已确认", "PENDING":"待确认", "CANCELLED":"已取消", "ON_TIME":"按期到货",
         "UNCONFIRMED":"待确认", "SUCCESS":"成功", "FAILED":"失败", "SKIPPED":"已跳过"}
NAMES = {"Sensor":"传感器", "Bearing":"轴承", "Controller":"控制器", "Brake Module":"制动模块", "Battery Component":"电池组件"}
SUPPLIERS = {"VisionSense Components":"星澜传感科技", "Precision Bearing Works":"精衡轴承制造",
             "AutoControl Electronics":"启程汽车电子", "PrimeBrake Systems":"安驰制动系统", "GreenCell Mobility":"澄能动力部件",
             "Northern Bearing Co.":"北辰轴承", "VoltSource Industries":"合源动力"}
ENUMS.update({'EXPEDITE':'现有订单加急','BACKUP':'备用供应商供货','TRANSFER':'内部库存调拨','BASELINE':'不采取应急措施',
              'SIM-EXPEDITE':'现有订单加急','SIM-BACKUP':'备用来源供货','SIM-TRANSFER':'内部调拨','SIM-LATE':'低价但较晚到货',
              'Fictional Qualified Backup':'模拟合格备用来源','Fictional Plant B Free Stock':'模拟工厂可用库存'})
ENUMS['Fictional Low-cost Late Supplier']='模拟低价延迟供货来源'
LABELS = {"part_code":"物料编码", "part_name":"物料名称", "supplier":"供应商", "current_stock":"期初可用库存（件）",
          "daily_usage":"日均需求（件）", "lead_time_days":"交期（天）", "supplier_status":"供应商状态", "criticality":"关键程度",
          "backup_supplier":"备用供应商", "backup_supplier_available":"备用来源可用", "destination_line":"使用产线",
          "unit_cost":"参考单价（元）", "safety_days":"安全库存天数", "date":"日期", "quantity":"需求（件）",
          "po_id":"采购订单编号", "open_quantity":"未交数量（件）", "arrival_date":"预计到货日期", "original_arrival_date":"原定到货日期",
          "status":"状态", "delivery_status":"履约情况", "qualified":"供应资格已核验",
          "opening_available":"期初可用库存", "confirmed_receipts":"确认到货", "planned_demand":"计划需求",
          "satisfied_demand":"已满足需求", "unmet_demand":"未满足需求", "projected_balance":"当日供需余额",
          "closing_available":"期末可用库存", "below_safety_stock":"低于安全库存", "po_ids":"关联订单",
          "start":"开始日期", "end":"结束日期", "days":"持续天数", "SKU":"物料编码", "risk_level":"风险等级"}
LABELS.update({'candidate_id':'措施编号','kind':'措施类型','source':'供给来源','capacity':'可供上限','earliest_available_date':'最早可用日期',
               'extra_cost':'额外费用（元）','minimum_quantity':'最小批量','pack_multiple':'包装倍数','source_pool':'共享库存池',
               'pool_capacity':'库存池上限','business_allowed':'业务允许','linked_po_id':'关联采购订单'})
LABELS.update({'eligible':'可执行','constraint_reasons':'约束说明'})


def zh(value):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (list, tuple)):
        return "、".join(zh(v) for v in value) or "无"
    if isinstance(value,str) and ' + ' in value:return ' ＋ '.join(zh(v) for v in value.split(' + '))
    return ENUMS.get(str(value), NAMES.get(str(value), SUPPLIERS.get(str(value), str(value))))


def zh_text(text):
    result=str(text)
    phrases={
      'Recommended order quantity restores the simulated target inventory; it is not proof that a pre-arrival coverage gap can be avoided.':'参考补货量用于恢复目标库存，不能证明到货前的缺口已经解决。',
      'Internal Transfer is not recommended because no source-location stock, transfer lead time, or logistics-feasibility data is available.':'尚未提供来源库存、调拨时间和物流可行性，当前不推荐直接执行内部调拨。',
      'Normal Supply':'正常供应','Supplier Delay':'供应商延期','Critical Shortage':'关键物料短缺',
      'No Action':'无需行动','Normal Reorder':'常规补货','Emergency Reorder':'紧急补货',
      'Expedite Delivery':'协调加急交付','Evaluate Backup Supplier':'评估备用来源',
      'Final Assembly Line 1':'模拟总装一线','Powertrain Line':'模拟动力总成线','Electronic Control Line':'模拟电子装配线',
      'Brake Assembly Line':'模拟制动装配线','Battery Pack Line':'模拟电池装配线','Safety Days':'安全库存天数',
      'LLM':'本地模型'}
    for a,b in {**phrases,**NAMES,**SUPPLIERS}.items():result=result.replace(a,b)
    import re
    for a,b in ENUMS.items():result=re.sub(r'(?<![A-Za-z0-9_-])'+re.escape(a)+r'(?![A-Za-z0-9_-])',lambda m:b,result)
    for old,new in {'高风险（高）':'高风险','中风险（中）':'中风险','低风险（低）':'低风险','紧急补货（紧急补货）':'紧急补货','无需行动（无需行动）':'无需行动','常规补货（常规补货）':'常规补货'}.items():result=result.replace(old,new)
    return result


def risk_badge(value):
    """Render only known risk values; keep unknown input escaped as plain text."""
    levels={"HIGH":"HIGH","高":"HIGH","高风险":"HIGH","MEDIUM":"MEDIUM","中":"MEDIUM","中风险":"MEDIUM",
            "LOW":"LOW","低":"LOW","低风险":"LOW"}
    level=levels.get(str(value).split("（")[0])
    if level is None:return html.escape(zh(value))
    label={"HIGH":"高风险","MEDIUM":"中风险","LOW":"低风险"}[level]
    return f'<span class="risk-badge risk-{level.lower()}" data-risk="{level}">{label}</span>'


def table_page(frame, page):
    """A display slice only: the complete input remains available to calculations."""
    count=len(frame)
    pages=max(1,(count+TABLE_PAGE_SIZE-1)//TABLE_PAGE_SIZE)
    page=max(0,min(int(page),pages-1))
    return frame.iloc[page*TABLE_PAGE_SIZE:(page+1)*TABLE_PAGE_SIZE],page,pages


def table(data, *, key=None, columns=None):
    frame = data.copy() if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    if columns:
        frame = frame.loc[:, [c for c in columns if c in frame]]
    identity=hashlib.sha256(frame.to_json(orient='split',date_format='iso').encode()).hexdigest()
    caller=inspect.currentframe().f_back
    scope=key or hashlib.sha256(f'{caller.f_code.co_filename}:{caller.f_lineno}:{identity}'.encode()).hexdigest()[:16]
    page_key=f'table_page_{scope}'
    if len(frame)>TABLE_PAGE_SIZE:
        if st.session_state.get(f'table_source_{scope}')!=identity:
            st.session_state[page_key]=0
            st.session_state[f'table_source_{scope}']=identity
        visible,page,pages=table_page(frame,st.session_state.get(page_key,0))
    else:visible,page,pages=frame,0,1
    headers = "".join(f"<th>{html.escape(LABELS.get(c,c))}</th>" for c in frame.columns)
    rows = "".join("<tr>"+"".join(f"<td>{risk_badge(v) if c in ('risk_level','风险等级','风险') else html.escape(zh(v))}</td>" for c,v in zip(frame.columns,row))+"</tr>" for row in visible.itertuples(index=False,name=None))
    st.markdown(f'<div class="chinese-table" data-table="{html.escape(key or "table")}"><table><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table></div>',unsafe_allow_html=True)
    if len(frame)>TABLE_PAGE_SIZE:
        previous,info,next_button=st.columns((1,3,1),vertical_alignment='center')
        if previous.button('上一页',key=f'table_previous_{scope}',disabled=page==0):
            st.session_state[page_key]=page-1;st.rerun()
        info.caption(f'显示第{page*TABLE_PAGE_SIZE+1}—{min((page+1)*TABLE_PAGE_SIZE,len(frame))}行，共{len(frame)}行 · 第{page+1}/{pages}页 · 每页10行')
        if next_button.button('下一页',key=f'table_next_{scope}',disabled=page+1>=pages):
            st.session_state[page_key]=page+1;st.rerun()


def user_error(value):
    message=str(value)
    phrases={
      'expected YYYY-MM-DD date':'请输入有效年月日日期，例如2026-10-14',
      'use a date without time/timezone':'日期不要包含时刻或时区',
      'expected a finite non-negative integer':'请输入有限的非负整数',
      'horizon_days must be between 1 and 90':'预测天数必须为1—90天',
      'provide exactly one demand row per SKU per day, including zero days':'每种物料每天必须有且只有一行需求，停产日填写0',
      'demand date is duplicate or outside horizon':'需求日期重复或超出预测周期',
      'duplicate PO identifier; each PO may appear only once':'采购订单编号重复，每笔订单只能出现一次',
      'PO identifier is empty or duplicate':'采购订单编号为空或重复',
      'overdue confirmed PO must have its arrival date reconfirmed':'已逾期的确认订单需要重新确认到货日期',
      'PO status must be CONFIRMED/PENDING/CANCELLED':'订单状态必须为已确认、待确认或已取消',
      'demand/PO references unknown SKU':'需求或采购订单引用了不存在的物料编码',
      'part and supplier status/lead time must agree':'同一供应商的状态与交期必须一致',
      'part references unknown supplier':'物料引用了不存在的供应商',
      'PO references unknown supplier':'采购订单引用了不存在的供应商',
      'confirmed PO supplier is not qualified':'已确认订单的供应商尚未完成资格核验',
      'supplier name is empty or duplicate':'供应商名称为空或重复',
      'invalid supplier status':'供应商状态不合法',
      'settings must contain exactly one row':'预测设置必须有且只有一行',
      'invalid or damaged XLSX workbook':'Excel 文件损坏或格式不正确',
      'planning workbook must be at most 5 MB':'动态计划文件不能超过5MB',
      'missing sheets:':'缺少工作表：','required sheets:':'需要的工作表：',
      'duplicate column headers':'存在重复表头','missing columns':'缺少必要字段'}
    for a,b in phrases.items():message=message.replace(a,b)
    for a,b in sorted({**LABELS,'parts':'物料主数据','demands':'逐日需求','orders':'采购订单','suppliers':'供应商','settings':'预测设置','start_date':'预测首日','horizon_days':'预测天数'}.items(),key=lambda pair:len(pair[0]),reverse=True):message=message.replace(a,b)
    return zh_text(message)


def editor(rows, columns, *, key, add=False, filter_column=None, defaults=None):
    # Convert dates/numpy scalars to JSON-compatible values through pandas.
    import json
    clean = json.loads(pd.DataFrame(rows).to_json(orient="records",date_format="iso")) if rows else []
    # Component events are available before this rerun. Echo the newest payload,
    # rather than the caller's previous draft, which is only updated after return.
    pending=st.session_state.get(key)
    clean=editor_rows(pending,clean)
    edit_revision=pending.get('edit_id',0) if isinstance(pending,dict) else 0
    value = _widget(kind="editor", rows=clean, editRevision=edit_revision, columns=columns, add=add, filterColumn=filter_column,labels={**ENUMS,**NAMES,**SUPPLIERS},
                    defaults=defaults or {}, default={"rows":clean}, key=key)
    return editor_rows(value,clean)


def editor_rows(value, fallback):
    """Apply an editor snapshot without mutating the immutable input workspace."""
    from copy import deepcopy
    if isinstance(value,dict) and isinstance(value.get('rows'),list):return deepcopy(value['rows'])
    clean=deepcopy(fallback)
    if isinstance(value,dict) and 'edited_rows' in value:
        for index,updates in value['edited_rows'].items():
            if 0<=int(index)<len(clean):clean[int(index)].update(updates)
    return clean


@dataclass
class Upload:
    name: str
    content: bytes
    def getvalue(self):
        return self.content


def upload_value(value):
    if hasattr(value,"getvalue"):
        return value
    if isinstance(value,dict) and value.get("data"):
        if not isinstance(value.get('name'),str) or not isinstance(value['data'],str):raise ValueError('文件内容或名称不合法。')
        if len(value['data'])>6_666_668:raise ValueError('文件超过5MB，请减少数据行后重新上传。')
        payload = base64.b64decode(value["data"],validate=True)
        if len(payload)>5_000_000:
            raise ValueError("文件超过5MB，请减少数据行后重新上传。")
        return Upload(value["name"],payload)
    return None


def uploader(label, *, key, types=("xlsx",)):
    saved=st.session_state.get(key+'_saved_upload')
    value = _widget(kind="upload",label=label,accept=",".join("."+t for t in types),filename=saved.get('name','') if saved else '',default=saved,key=key)
    if value:st.session_state[key+'_saved_upload']=value
    try:
        return upload_value(value)
    except (ValueError,KeyError) as exc:
        st.error(f"文件读取失败：{exc}")
        return None


def column(name, *, editable=True, kind="text", choices=None):
    return {"name":name,"label":LABELS.get(name,name),"editable":editable,"type":kind,
            "choices":[{"value":v,"label":zh(v)} for v in (choices or [])]}
