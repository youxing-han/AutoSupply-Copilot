"""Deterministic inventory calculations for AutoSupply Copilot.

Business assumptions for the Stage A model:

* Daily usage is stable over the short planning horizon.
* Current stock is used as the inventory position because in-transit stock,
  open purchase orders, reservations, and backorders are not yet available.
* ``safety_days`` is a fictional policy setting for the demonstration data; it
  is not estimated from historical demand or supplier variability.
* By default, target stock covers lead time plus safety days.
* A stockout gap is a potential uncovered period before replenishment arrives.
  It is not evidence that production has already stopped for that many days.
"""

from __future__ import annotations

import math
from numbers import Real
from typing import TypedDict


class InventoryMetrics(TypedDict):
    days_of_stock: float
    stockout_gap: float
    safety_stock: float
    reorder_point: float
    target_coverage_days: float
    target_stock: float
    recommended_order_qty: int


def _validate_non_negative(value: Real, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise ValueError(f"{name} must be finite")
    if numeric_value < 0:
        raise ValueError(f"{name} must be non-negative")
    return numeric_value


def calculate_days_of_stock(current_stock: Real, daily_usage: Real) -> float:
    """Calculate ``current stock / daily usage``.

    Zero daily usage returns positive infinity because the supplied stock is
    not being consumed under the current planning assumption. This avoids a
    division error while making the exceptional condition explicit.
    """

    stock = _validate_non_negative(current_stock, "current_stock")
    usage = _validate_non_negative(daily_usage, "daily_usage")
    if usage == 0:
        return math.inf
    return stock / usage


def calculate_stockout_gap(days_of_stock: Real, lead_time_days: Real) -> float:
    """Calculate ``max(0, lead time - days of stock)`` in potential days."""

    lead_time = _validate_non_negative(lead_time_days, "lead_time_days")
    if isinstance(days_of_stock, bool) or not isinstance(days_of_stock, Real):
        raise TypeError("days_of_stock must be a real number")

    coverage = float(days_of_stock)
    if math.isnan(coverage) or coverage < 0:
        raise ValueError("days_of_stock must be non-negative")
    if math.isinf(coverage):
        return 0.0
    return max(0.0, lead_time - coverage)


def calculate_safety_stock(daily_usage: Real, safety_days: Real) -> float:
    """Calculate ``daily usage * safety days``."""

    usage = _validate_non_negative(daily_usage, "daily_usage")
    policy_days = _validate_non_negative(safety_days, "safety_days")
    return usage * policy_days


def calculate_reorder_point(
    daily_usage: Real, lead_time_days: Real, safety_days: Real
) -> float:
    """Calculate ``daily usage * lead time + safety stock``."""

    usage = _validate_non_negative(daily_usage, "daily_usage")
    lead_time = _validate_non_negative(lead_time_days, "lead_time_days")
    safety_stock = calculate_safety_stock(usage, safety_days)
    return usage * lead_time + safety_stock


def calculate_recommended_order_quantity(
    current_stock: Real,
    daily_usage: Real,
    target_coverage_days: Real,
) -> int:
    """Return whole units needed to reach the target-stock policy.

    Formula: ``ceil(max(0, daily usage * target coverage - current stock))``.
    Current stock is the simplified inventory position in Stage A because no
    in-transit or open-order quantity has been supplied.
    """

    stock = _validate_non_negative(current_stock, "current_stock")
    usage = _validate_non_negative(daily_usage, "daily_usage")
    target_days = _validate_non_negative(target_coverage_days, "target_coverage_days")
    target_stock = usage * target_days
    return math.ceil(max(0.0, target_stock - stock))


def calculate_inventory_metrics(
    current_stock: Real,
    daily_usage: Real,
    lead_time_days: Real,
    safety_days: Real,
    target_coverage_days: Real | None = None,
) -> InventoryMetrics:
    """Calculate the complete deterministic metric set for one part.

    If no target is supplied, the simulated policy targets enough inventory
    for ``lead_time_days + safety_days``.
    """

    stock = _validate_non_negative(current_stock, "current_stock")
    usage = _validate_non_negative(daily_usage, "daily_usage")
    lead_time = _validate_non_negative(lead_time_days, "lead_time_days")
    policy_days = _validate_non_negative(safety_days, "safety_days")

    if target_coverage_days is None:
        target_days = lead_time + policy_days
    else:
        target_days = _validate_non_negative(
            target_coverage_days, "target_coverage_days"
        )

    days_of_stock = calculate_days_of_stock(stock, usage)
    safety_stock = calculate_safety_stock(usage, policy_days)
    target_stock = usage * target_days

    return {
        "days_of_stock": days_of_stock,
        "stockout_gap": calculate_stockout_gap(days_of_stock, lead_time),
        "safety_stock": safety_stock,
        "reorder_point": calculate_reorder_point(usage, lead_time, policy_days),
        "target_coverage_days": target_days,
        "target_stock": target_stock,
        "recommended_order_qty": calculate_recommended_order_quantity(
            stock, usage, target_days
        ),
    }
