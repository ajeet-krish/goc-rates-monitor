"""Basket weight vintage with link month pinning and renormalization."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from goc_rates.config import CpiConfig
from goc_rates.cpi.components import ComponentSpec
from goc_rates.limits import MAX_CPI_COMPONENTS

EXPECTED_EXPENDITURE_YEAR = 2024
EXPECTED_LINK_MONTH = "2025-05"

WEIGHT_TOTAL_PERCENT = 100.0
WEIGHT_SUM_TOLERANCE = 1e-6


@dataclass(frozen=True)
class WeightVintage:
    """Pinned basket vintage: expenditure year, link month, provisional flag."""

    expenditure_year: int
    link_month: str
    provisional: bool


def vintage_from_config(config: CpiConfig) -> WeightVintage:
    """Return the pinned weight vintage, failing closed on format drift."""
    vintage = config.weight_vintage
    if vintage.expenditure_year != EXPECTED_EXPENDITURE_YEAR:
        raise ValueError(
            f"weight vintage expenditure year {vintage.expenditure_year} "
            f"must pin {EXPECTED_EXPENDITURE_YEAR}"
        )
    if vintage.link_month != EXPECTED_LINK_MONTH:
        raise ValueError(
            f"weight vintage link month {vintage.link_month!r} must pin {EXPECTED_LINK_MONTH!r}"
        )
    return WeightVintage(
        expenditure_year=vintage.expenditure_year,
        link_month=vintage.link_month,
        provisional=vintage.provisional,
    )


def normalize_weights(specs: Sequence[ComponentSpec]) -> dict[str, float]:
    """Renormalize registry weights to fractions summing to one.

    The registry weights must sum to 100 percent within 1e-6; any drift
    fails closed instead of silently rescaling a tampered basket.
    """
    items = list(specs)
    if not items:
        raise ValueError("need at least one component spec")
    if len(items) > MAX_CPI_COMPONENTS:
        raise ValueError(f"component count {len(items)} exceeds the {MAX_CPI_COMPONENTS} cap")
    total = 0.0
    for spec in items:
        weight = spec.weight_percent
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise ValueError(f"weight for {spec.component_id!r} must be numeric")
        value = float(weight)
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"weight for {spec.component_id!r} must be finite")
        if value <= 0.0:
            raise ValueError(f"weight for {spec.component_id!r} must be positive")
        total += value
    if abs(total - WEIGHT_TOTAL_PERCENT) > WEIGHT_SUM_TOLERANCE:
        raise ValueError(
            f"registry weights sum to {total:.6f}, "
            f"expected {WEIGHT_TOTAL_PERCENT:.6f} within {WEIGHT_SUM_TOLERANCE}"
        )
    return {spec.component_id: float(spec.weight_percent) / total for spec in items}
