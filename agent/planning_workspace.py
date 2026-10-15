"""Serializable editor workspace and immutable analysis snapshots."""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
WORKSPACE_VERSION = 2


def fingerprint(bundle: dict) -> str:
    def encode(value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return str(value)
    return hashlib.sha256(json.dumps(bundle, sort_keys=True, ensure_ascii=False, default=encode).encode()).hexdigest()


def new_workspace(bundle: dict, source: str, controls: tuple, revision=1) -> dict:
    return {"bundle": deepcopy(bundle), "source": source, "controls": controls, "revision": revision}


def analysis_totals(analysis: dict) -> dict:
    projections = [r["inventory_projection"] for r in analysis["details"].values()]
    shortages = [r for r in projections if r["total_unmet_demand"] > 0]
    return {"sku_count": len(projections), "shortage_sku_count": len(shortages),
            "first_shortage_date": min((r["first_shortage_date"] for r in shortages), default=None),
            "total_unmet_demand": sum(r["total_unmet_demand"] for r in projections)}


def risk_overview_rows(analysis: dict) -> list[dict]:
    """Keep quantity shortages distinct from buffer and supplier warnings."""
    rows=[]
    for sku,result in analysis['details'].items():
        p=result['inventory_projection']
        rows.append({'SKU':sku,'名称':result['selected_part']['part_name'],
                     '风险':result['supplier_risk']['risk_level'],
                     '累计未满足需求':p['total_unmet_demand'],
                     '安全库存预警天数':len(p['safety_warning_dates']),
                     '供应商状态':result['selected_part']['supplier_status']})
    return sorted(rows,key=lambda r:(-r['累计未满足需求'],-r['安全库存预警天数'],r['SKU']))
