"""Simulated supply-chain data used by the original and AutoSupply workflows.

The automotive records in this module are entirely fictional. They are
designed to make scenario differences observable through business inputs such
as stock, lead time, and supplier status rather than preassigned risk labels.
"""

from __future__ import annotations

from copy import deepcopy

import pandas as pd


NORMAL_SUPPLY = "Normal Supply"
SUPPLIER_DELAY = "Supplier Delay"
CRITICAL_SHORTAGE = "Critical Shortage"
SCENARIO_NAMES = (NORMAL_SUPPLY, SUPPLIER_DELAY, CRITICAL_SHORTAGE)
DEFAULT_SCENARIO_PART_CODES = {
    NORMAL_SUPPLY: "SEN-001",
    SUPPLIER_DELAY: "SEN-001",
    CRITICAL_SHORTAGE: "BRK-004",
}


_BASE_AUTOMOTIVE_PARTS = [
    {
        "part_code": "SEN-001",
        "part_name": "Sensor",
        "supplier": "VisionSense Components",
        "current_stock": 800,
        "daily_usage": 80,
        "lead_time_days": 7,
        "supplier_status": "NORMAL",
        "criticality": "MEDIUM",
        "backup_supplier": None,
        "backup_supplier_available": False,
        "destination_line": "Final Assembly Line 1",
        "unit_cost": 42.50,
        "safety_days": 3,
    },
    {
        "part_code": "BRG-002",
        "part_name": "Bearing",
        "supplier": "Precision Bearing Works",
        "current_stock": 1500,
        "daily_usage": 100,
        "lead_time_days": 5,
        "supplier_status": "NORMAL",
        "criticality": "MEDIUM",
        "backup_supplier": "Northern Bearing Co.",
        "backup_supplier_available": True,
        "destination_line": "Powertrain Line",
        "unit_cost": 18.20,
        "safety_days": 2,
    },
    {
        "part_code": "CTL-003",
        "part_name": "Controller",
        "supplier": "AutoControl Electronics",
        "current_stock": 600,
        "daily_usage": 30,
        "lead_time_days": 10,
        "supplier_status": "NORMAL",
        "criticality": "HIGH",
        "backup_supplier": None,
        "backup_supplier_available": False,
        "destination_line": "Electronic Control Line",
        "unit_cost": 186.00,
        "safety_days": 4,
    },
    {
        "part_code": "BRK-004",
        "part_name": "Brake Module",
        "supplier": "PrimeBrake Systems",
        "current_stock": 400,
        "daily_usage": 20,
        "lead_time_days": 8,
        "supplier_status": "NORMAL",
        "criticality": "HIGH",
        "backup_supplier": None,
        "backup_supplier_available": False,
        "destination_line": "Brake Assembly Line",
        "unit_cost": 245.00,
        "safety_days": 3,
    },
    {
        "part_code": "BAT-005",
        "part_name": "Battery Component",
        "supplier": "GreenCell Mobility",
        "current_stock": 900,
        "daily_usage": 50,
        "lead_time_days": 9,
        "supplier_status": "NORMAL",
        "criticality": "HIGH",
        "backup_supplier": "VoltSource Industries",
        "backup_supplier_available": True,
        "destination_line": "Battery Pack Line",
        "unit_cost": 132.00,
        "safety_days": 3,
    },
]


SCENARIO_DESCRIPTIONS = {
    NORMAL_SUPPLY: (
        "All suppliers are operating normally and every part has enough stock "
        "to cover its stated lead time."
    ),
    SUPPLIER_DELAY: (
        "The Sensor supplier lead time increases from 7 to 14 days while stock "
        "and daily usage stay unchanged, creating a potential coverage gap."
    ),
    CRITICAL_SHORTAGE: (
        "Brake Module stock falls from 400 to 40 units, the primary supplier is "
        "disrupted, lead time rises to 10 days, and a backup supplier is available."
    ),
}


def generate_automotive_supply_data(scenario: str = NORMAL_SUPPLY) -> pd.DataFrame:
    """Return fictional automotive-part data for one predefined scenario.

    Scenario changes are applied to operational inputs. No risk level or
    replenishment result is embedded in the source data; those outputs must be
    calculated by later modules.
    """

    if scenario not in SCENARIO_NAMES:
        choices = ", ".join(SCENARIO_NAMES)
        raise ValueError(f"Unknown scenario {scenario!r}. Expected one of: {choices}")

    parts = deepcopy(_BASE_AUTOMOTIVE_PARTS)

    if scenario == SUPPLIER_DELAY:
        sensor = next(part for part in parts if part["part_code"] == "SEN-001")
        sensor["lead_time_days"] = 14
        sensor["supplier_status"] = "DELAYED"

    if scenario == CRITICAL_SHORTAGE:
        brake_module = next(part for part in parts if part["part_code"] == "BRK-004")
        brake_module["current_stock"] = 40
        brake_module["lead_time_days"] = 10
        brake_module["supplier_status"] = "DISRUPTED"
        brake_module["backup_supplier"] = "SafeBrake Components"
        brake_module["backup_supplier_available"] = True

    for part in parts:
        part["scenario"] = scenario

    return pd.DataFrame(parts)


def get_scenario_description(scenario: str) -> str:
    """Return the documented business meaning of a predefined scenario."""

    try:
        return SCENARIO_DESCRIPTIONS[scenario]
    except KeyError as exc:
        raise ValueError(f"Unknown scenario {scenario!r}") from exc


def get_scenario_part(
    scenario: str, part_code: str | None = None
) -> dict[str, object]:
    """Return one scenario record using ordinary Python scalar values.

    Each predefined scenario has a default focus part, while callers may select
    another part code for later UI-driven analysis.
    """

    data = generate_automotive_supply_data(scenario)
    selected_code = part_code or DEFAULT_SCENARIO_PART_CODES[scenario]
    rows = data.loc[data["part_code"] == selected_code]
    if rows.empty:
        raise ValueError(
            f"Unknown part_code {selected_code!r} for scenario {scenario!r}"
        )

    record: dict[str, object] = {}
    for field, value in rows.iloc[0].to_dict().items():
        if pd.isna(value):
            record[field] = None
        elif hasattr(value, "item"):
            record[field] = value.item()
        else:
            record[field] = value
    return record


# Legacy food-supply functions are retained until the LangGraph workflow is
# migrated in the next development stage. This keeps agent/main.py runnable
# without changing agents.py in Stage A.
def generate_supply_chain_data(disruption: bool = False) -> pd.DataFrame:
    """Simulate the original food supply chain for backward compatibility."""

    data = {
        "node": ["Farm_A", "Farm_B", "Warehouse_Central", "Dist_Stockholm", "Dist_Gothenburg"],
        "stock_level": [850, 200, 450, 120, 380],
        "daily_demand": [100, 100, 200, 80, 120],
        "days_of_stock": [8.5, 2.0, 2.25, 1.5, 3.17],
        "status": ["OK", "CRITICAL", "LOW", "CRITICAL", "OK"],
    }

    if disruption:
        data["stock_level"][0] = 340
        data["days_of_stock"][0] = 3.4
        data["status"][0] = "DISRUPTED"

    return pd.DataFrame(data)


def get_chain_summary(df: pd.DataFrame) -> str:
    """Convert the original food-supply dataframe to an agent text summary."""

    summary = "SUPPLY CHAIN STATUS REPORT:\n"
    for _, row in df.iterrows():
        summary += f"- {row['node']}: stock={row['stock_level']} units, "
        summary += f"days_remaining={row['days_of_stock']:.1f}, status={row['status']}\n"
    return summary


if __name__ == "__main__":
    for scenario_name in SCENARIO_NAMES:
        print(f"\n=== {scenario_name} ===")
        print(get_scenario_description(scenario_name))
        print(generate_automotive_supply_data(scenario_name).to_string(index=False))
