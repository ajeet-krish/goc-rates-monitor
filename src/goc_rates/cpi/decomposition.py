"""Decomposition: component contributions in percentage points."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


def _check_weight(weight_percent: float, component_id: str) -> float:
    """Return a finite non negative weight in percent, else raise."""
    if isinstance(weight_percent, bool) or not isinstance(weight_percent, (int, float)):
        raise ValueError(f"weight for {component_id!r} must be numeric")
    result = float(weight_percent)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"weight for {component_id!r} must be finite")
    if result < 0.0 or result > 100.0:
        raise ValueError(f"weight for {component_id!r} must sit within [0, 100]")
    return result


def _check_rate(monthly_rate_percent: float, component_id: str) -> float:
    """Return a finite monthly rate in percent, else raise."""
    if isinstance(monthly_rate_percent, bool) or not isinstance(monthly_rate_percent, (int, float)):
        raise ValueError(f"monthly rate for {component_id!r} must be numeric")
    result = float(monthly_rate_percent)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"monthly rate for {component_id!r} must be finite")
    return result


@dataclass(frozen=True)
class Contribution:
    """One component contribution: weight times rate over 100, in pp."""

    component_id: str
    monthly_rate_percent: float
    weight_percent: float
    contribution_pp: float


def contribution_pp(weight_percent: float, monthly_rate_percent: float) -> float:
    """Return the contribution in percentage points: w * r / 100."""
    weight = _check_weight(weight_percent, "component")
    rate = _check_rate(monthly_rate_percent, "component")
    result = weight * rate / 100.0
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("contribution computation overflowed")
    return result


def decompose_month(
    monthly_rates: Mapping[str, float],
    weights_percent: Mapping[str, float],
) -> tuple[Contribution, ...]:
    """Decompose one month into per component contributions in pp.

    The rate and weight key sets must match exactly, else fail closed.
    """
    if set(monthly_rates.keys()) != set(weights_percent.keys()):
        raise ValueError("monthly rates and weights must cover the same components")
    if not monthly_rates:
        raise ValueError("need at least one component to decompose")
    contributions: list[Contribution] = []
    for component_id in sorted(monthly_rates.keys()):
        rate = _check_rate(monthly_rates[component_id], component_id)
        weight = _check_weight(weights_percent[component_id], component_id)
        contributions.append(
            Contribution(
                component_id=component_id,
                monthly_rate_percent=rate,
                weight_percent=weight,
                contribution_pp=contribution_pp(weight, rate),
            )
        )
    return tuple(contributions)


def total_contribution_pp(contributions: tuple[Contribution, ...]) -> float:
    """Return the summed contributions in percentage points."""
    if not contributions:
        raise ValueError("need at least one contribution to total")
    total = 0.0
    for contribution in contributions:
        value = contribution.contribution_pp
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("contribution_pp must be numeric")
        total += float(value)
    if total != total or total in (float("inf"), float("-inf")):
        raise ValueError("contribution total overflowed")
    return total
