"""Command-line runner for the AutoSupply Copilot four-node workflow."""

from __future__ import annotations

import argparse
from typing import Any

from agents import SupplyChainState, build_supply_chain_graph, create_initial_state
from supply_data import SCENARIO_NAMES, get_scenario_part


def run_scenario(
    scenario: str,
    part_code: str | None = None,
    use_llm_report: bool = False,
) -> SupplyChainState:
    """Run one predefined automotive scenario through the actual graph."""

    selected_part = get_scenario_part(scenario, part_code)
    initial_state = create_initial_state(
        scenario=scenario,
        selected_part=selected_part,
        use_llm_report=use_llm_report,
    )
    result: SupplyChainState = build_supply_chain_graph().invoke(initial_state)
    return result


def print_result(result: dict[str, Any]) -> None:
    part = result["selected_part"]
    metrics = result["inventory_metrics"]
    risk = result["supplier_risk"]
    decision = result["replenishment_decision"]

    print("\n" + "=" * 72)
    print(f"SCENARIO: {result['scenario']} | PART: {part['part_code']} {part['part_name']}")
    print("=" * 72)
    print("Inventory Metrics:")
    for key, value in metrics.items():
        print(f"  {key}: {value}")
    print(f"Risk Level: {risk['risk_level']}")
    print("Risk Reasons:")
    for reason in risk["reasons"]:
        print(f"  - {reason}")
    print(f"Recommended Action: {decision['recommended_action']}")
    print(f"Supporting Actions: {decision['supporting_actions']}")
    print(f"Recommended Order Quantity: {decision['recommended_order_qty']}")
    print("Execution Trace:")
    for trace in result["execution_trace"]:
        print(
            f"  - {trace['node_name']} [{trace['execution_status']}]\n"
            f"      input: {trace['input_summary']}\n"
            f"      output: {trace['output_summary']}"
        )
    print(f"Report Source: {result['report_source']}")
    if result.get("llm_error"):
        print(f"LLM Fallback Reason: {result['llm_error']}")
    print("Management Report:")
    print(result["management_report"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--llm-report",
        action="store_true",
        help="Request a CPU-only Ollama report; falls back to the template.",
    )
    args = parser.parse_args()

    for scenario in SCENARIO_NAMES:
        print_result(run_scenario(scenario, use_llm_report=args.llm_report))


if __name__ == "__main__":
    main()
