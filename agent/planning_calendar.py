"""Natural-week demand views. Padding is display-only, never forecast input."""
from copy import deepcopy
import math
from numbers import Real
from datetime import timedelta
from inventory_planning import day, quantity

WEEKDAYS = ('周一', '周二', '周三', '周四', '周五', '周六', '周日')


def valid_cell(value):
    return isinstance(value, Real) and not isinstance(value,bool) and math.isfinite(value) and value >= 0 and int(value)==value


def natural_weeks(start_date, horizon_days):
    start = day(start_date)
    horizon = quantity(horizon_days, '预测天数')
    if not 1 <= horizon <= 90:
        raise ValueError('预测天数必须为1—90天')
    end = start + timedelta(days=horizon - 1)
    monday = start - timedelta(days=start.weekday())
    weeks = []
    while monday <= end:
        weeks.append([{'date': (monday + timedelta(days=i)).isoformat(),
                       'weekday': WEEKDAYS[i],
                       'in_period': start <= monday + timedelta(days=i) <= end}
                      for i in range(7)])
        monday += timedelta(days=7)
    return weeks


def demand_grid(parts, demands, start_date, horizon_days, week_index=0, sku=None):
    weeks = natural_weeks(start_date, horizon_days)
    dates = weeks[max(0, min(week_index, len(weeks)-1))]
    lookup = {(r['part_code'], day(r['date']).isoformat()): r['quantity'] for r in demands}
    rows = []
    for part in parts:
        if sku and part['part_code'] != sku:
            continue
        values = [lookup.get((part['part_code'], d['date'])) if d['in_period'] else 0 for d in dates]
        rows.append({'part_code': part['part_code'], 'part_name': part['part_name'],
                     'values': values, 'total': sum(values) if all(valid_cell(v) for v in values) else None})
    totals = [None if any(not valid_cell(r['values'][i]) for r in rows)
              else sum(r['values'][i] for r in rows) for i in range(7)]
    return {'dates': dates, 'rows': rows, 'totals': totals, 'week_count': len(weeks)}


def apply_demand_patches(demands, parts, start_date, horizon_days, patches):
    """Only explicitly edited in-period cells can add or change demand rows."""
    valid_dates = {d['date'] for w in natural_weeks(start_date, horizon_days) for d in w if d['in_period']}
    codes = {p['part_code'] for p in parts}
    result = deepcopy(demands)
    lookup = {}
    for r in result:
        key = (r['part_code'], day(r['date']).isoformat())
        if key in lookup:
            raise ValueError('需求日期重复，请先修正源数据')
        lookup[key] = r
    for patch in patches:
        code, date = patch['part_code'], day(patch['date']).isoformat()
        if code not in codes or date not in valid_dates:
            raise ValueError('只能编辑已知物料在预测期内的需求')
        value = quantity(patch['quantity'], '计划需求')
        key = (code, date)
        if key not in lookup:
            row = {'part_code': code, 'date': date, 'quantity': value}
            result.append(row)
            lookup[key] = row
        else:
            lookup[key]['quantity'] = value
    return result
