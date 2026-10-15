"""Refresh obsolete in-process graph schemas after a Streamlit code upgrade.

Streamlit reruns app.py without necessarily replacing already imported helper
modules. A legacy TypedDict drops new LangGraph input/output channels silently.
Refresh only when the declared workflow contract is obsolete, never on ordinary
reruns, and verify actual graph output rather than manufacturing defaults.
"""
from __future__ import annotations

import importlib
import logging
import sys
import threading

LOGGER = logging.getLogger(__name__)
WORKFLOW_RUNTIME_VERSION = 6
_LOCK = threading.RLock()
REQUIRED_CHANNELS = {"planning_input", "inventory_projection", "mitigation_candidates", "mitigation_comparison"}


class WorkflowContractError(RuntimeError):
    """An internal graph/schema error, not bad user input."""


def current_workflow_module():
    with _LOCK:
        module = importlib.import_module("agents")
        if not REQUIRED_CHANNELS.issubset(module.SupplyChainState.__annotations__) or getattr(module,'DYNAMIC_INPUT_VERSION',None) != 2:
            LOGGER.warning("Refreshing obsolete LangGraph schema; dynamic planning channels were missing")
            module = importlib.reload(module)
            # Refresh by-value imports held by already loaded presentation helpers.
            for name in ("batch_analysis", "assistant", "report_pdf", "planning_data",
                         "mitigation_ui", "planning_ui"):
                if name in sys.modules:
                    importlib.reload(sys.modules[name])
        if not REQUIRED_CHANNELS.issubset(module.SupplyChainState.__annotations__):
            raise WorkflowContractError("LangGraph State still lacks dynamic planning channels after refresh")
        return module


def run_planning_workflow(part: dict, plan: dict, mitigation_candidates=None) -> dict:
    module = current_workflow_module()
    graph = module.build_supply_chain_graph()
    if not REQUIRED_CHANNELS.issubset(graph.channels):
        raise WorkflowContractError("Compiled LangGraph lacks dynamic planning channels")
    state = module.create_initial_state("Dynamic Planning", part)
    state["planning_input"] = plan
    if mitigation_candidates is not None:
        state["mitigation_candidates"] = mitigation_candidates
    result = graph.invoke(state)
    if result.get("workflow_error"):
        raise WorkflowContractError(result["workflow_error"])
    projection = result.get("inventory_projection")
    if (not isinstance(projection, dict) or projection.get("part_code") != part["part_code"]
            or not isinstance(projection.get("daily"), list)
            or len(projection["daily"]) != plan["horizon_days"]):
        raise WorkflowContractError("Inventory Monitor did not return a complete inventory_projection")
    if mitigation_candidates is not None and "mitigation_comparison" not in result:
        raise WorkflowContractError("Replenishment Decision did not return mitigation_comparison")
    return result


def current_planning_ui():
    """Version-check helpers so a warm server can adopt the editor upgrade."""
    with _LOCK:
        data = importlib.import_module("planning_data")
        data_changed=getattr(data, "PLANNING_DATA_VERSION", None) != 5
        if data_changed:
            importlib.reload(data)
        ui = importlib.import_module("planning_ui")
        if data_changed or getattr(ui, "PLANNING_UI_VERSION", None) != 8:
            ui = importlib.reload(ui)
        return ui
