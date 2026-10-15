"""Reproducible fictional business inputs, independent of presentation code."""
from copy import deepcopy
from datetime import timedelta
import pandas as pd
from inventory_planning import day, quantity
from supply_data import generate_automotive_supply_data, NORMAL_SUPPLY
DEMO_DATA_VERSION = 2

RICH_SCENARIOS = ("正常到货", "供应商交付延迟", "生产需求激增", "采购订单待确认", "周末检修", "集中到货")
SCENE_LABELS = {"正常到货":"平稳排产", "供应商交付延迟":"供应商延期", "生产需求激增":"排产高峰", "采购订单待确认":"订单待确认", "周末检修":"周末检修", "集中到货":"集中到货"}
SPECS = (
 ("SEN-001","前向感知传感器","星澜传感科技",80,640,3,7),
 ("BRG-002","轮毂轴承","精衡轴承制造",100,1080,2,5),
 ("CTL-003","车身控制器","启程汽车电子",30,240,4,10),
 ("BRK-004","制动控制模块","安驰制动系统",20,180,3,8),
 ("BAT-005","电池连接组件","澄能动力部件",50,420,3,9),
 ("HRN-006","低压线束","联序线束制造",180,1500,2,6),
 ("PUM-007","冷却水泵","清源热管理",48,390,3,8),
 ("VLV-008","电磁控制阀","锐控精密部件",65,610,2,7),
 ("RAD-009","散热器总成","清源热管理",36,320,3,8),
 ("CON-010","高压连接器","联序线束制造",210,1780,2,6),
 ("SEA-011","动力系统密封圈","恒密高分子",320,2800,2,6),
 ("CAM-012","环视摄像头","星澜传感科技",96,720,3,7))


def rich_parts():
    seed = generate_automotive_supply_data(NORMAL_SUPPLY).iloc[0].to_dict()
    parts=[]
    for i,(code,name,supplier,rate,stock,safety,lead) in enumerate(SPECS):
        p=deepcopy(seed)
        p.update(part_code=code,part_name=name,supplier=supplier,current_stock=stock,daily_usage=rate,
                 safety_days=safety,lead_time_days=lead,supplier_status="NORMAL",criticality="HIGH" if i in (0,2,3,4,8,11) else "MEDIUM",
                 backup_supplier=None,backup_supplier_available=False,destination_line="模拟汽车总装线",unit_cost=50+i*12)
        parts.append(p)
    return parts


def build_rich_planning(start_date="2026-10-14",horizon_days=30,scenario="正常到货"):
    start,horizon=day(start_date),quantity(horizon_days)
    if not 1<=horizon<=90 or scenario not in RICH_SCENARIOS:
        raise ValueError("请选择合法情景与1—90天预测周期。")
    parts,demands,orders=rich_parts(),[],[]
    for index,p in enumerate(parts):
        for offset in range(horizon):
            weekday=(start+timedelta(days=offset)).weekday()
            factor=(1.05,1,1.1,.95,1.15,.45,0)[weekday]
            week=(1,1.15,.92,1.08,1.02,1.1,.96,1.04)[(offset//7)%8]
            q=round(p['daily_usage']*factor*week)
            if scenario=="生产需求激增" and 6<=offset<=9:q=round(q*1.75)
            if scenario=="周末检修" and weekday>=5:q=0
            demands.append({"part_code":p['part_code'],"date":(start+timedelta(days=offset)).isoformat(),"quantity":q})
        for k in range(12):  # Same 90-day PO schedule for every viewing horizon.
            original=7+index%3+8*k
            arrival=original+4 if scenario=="供应商交付延迟" and index in (0,2,5) and k==0 else original
            if scenario=="集中到货":arrival=((original-1)//7+1)*7
            status="PENDING" if scenario=="采购订单待确认" and index in (0,2,5) and k==0 else "CONFIRMED"
            orders.append({"po_id":f"SIM-{p['part_code']}-{k+1:02d}","part_code":p['part_code'],"supplier":p['supplier'],
                           "open_quantity":round(p['daily_usage']*(7.6 if k%2==0 else 7.1)),
                           "arrival_date":(start+timedelta(days=arrival-1)).isoformat(),"original_arrival_date":(start+timedelta(days=original-1)).isoformat(),"status":status})
        if scenario=="供应商交付延迟" and index in (0,2,5):p['supplier_status']="DELAYED"
    # A supplier may serve several SKUs; its status and lead-time are shared.
    affected={parts[i]['supplier'] for i in (0,2,5)} if scenario=="供应商交付延迟" else set()
    for p in parts:
        if p['supplier'] in affected:p['supplier_status']="DELAYED"
    suppliers=list({p['supplier']:{"supplier":p['supplier'],"lead_time_days":p['lead_time_days'],"status":p['supplier_status'],"qualified":True} for p in parts}.values())
    return {"settings":[{"start_date":start.isoformat(),"horizon_days":horizon}],"parts":parts,"suppliers":suppliers,"demands":demands,"orders":orders}


def build_rich_batch(scenario="交付延迟"):
    parts=rich_parts()
    for i,p in enumerate(parts):
        if scenario=="交付延迟" and i in (0,2,5):p.update(lead_time_days=p['lead_time_days']+4,supplier_status="DELAYED")
        if scenario=="需求增长" and i in (0,2,5,9):p['daily_usage']=round(p['daily_usage']*1.5)
        if scenario=="集中缺料" and i in (3,8,11):p['current_stock']=round(p['daily_usage']*1.5)
    return pd.DataFrame(parts)


def blank_part():
    p=rich_parts()[0]
    p.update(part_code="",part_name="",supplier="",current_stock=0,daily_usage=0,lead_time_days=0,
             supplier_status="NORMAL",criticality="MEDIUM",backup_supplier=None,backup_supplier_available=False,
             destination_line="自定义产线",unit_cost=0,safety_days=3)
    return p


def custom_plan(parts,start_date,horizon_days):
    start=day(start_date);horizon=quantity(horizon_days)
    suppliers=list({p['supplier']:{"supplier":p['supplier'],"lead_time_days":p['lead_time_days'],"status":p['supplier_status'],"qualified":True} for p in parts if p['supplier']}.values())
    return {"settings":[{"start_date":start.isoformat(),"horizon_days":horizon}],"parts":deepcopy(parts),"suppliers":suppliers,
            "demands":[{"part_code":p['part_code'],"date":(start+timedelta(days=i)).isoformat(),"quantity":p['daily_usage']} for p in parts for i in range(horizon)],"orders":[]}
