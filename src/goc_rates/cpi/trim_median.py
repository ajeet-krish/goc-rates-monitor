"""Weighted CPI trim and median over the monthly SA distribution.

Method cpi_trim_median_weighted_sa_v1: rank the 55 seasonally adjusted
tax adjusted monthly rates with basket link month weights, exclude the
bottom 20 percent and top 20 percent of cumulative weight (40 percent
total, with partial weight splits on straddling components), and average
the kept 60 percent for trim. The median is the first component whose
cumulative weight exceeds 50 percent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from goc_rates.limits import MAX_CPI_COMPONENTS

TRIM_METHOD = "cpi_trim_median_weighted_sa_v1"

LOWER_CUMULATIVE = 0.20
UPPER_CUMULATIVE = 0.80

WEIGHT_SUM_TOLERANCE = 1e-6


@dataclass(frozen=True)
class ComponentRate:
    """One component monthly rate with its normalized basket weight."""

    component_id: str
    monthly_rate_percent: float
    weight_fraction: float


@dataclass(frozen=True)
class TrimMedianResult:
    """Trimmed mean plus weighted median for one month."""

    trim_mom_percent: float
    median_mom_percent: float
    median_component_id: str
    lower_excluded: tuple[str, ...]
    upper_excluded: tuple[str, ...]
    kept_weight_fraction: float
    excluded_weight_fraction: float


def _check_rate(rate: ComponentRate) -> ComponentRate:
    """Validate one component rate and return it."""
    if not isinstance(rate.component_id, str) or not rate.component_id.strip():
        raise ValueError("component_id must be a non empty string")
    monthly = rate.monthly_rate_percent
    if isinstance(monthly, bool) or not isinstance(monthly, (int, float)):
        raise ValueError(f"monthly rate for {rate.component_id!r} must be numeric")
    monthly_value = float(monthly)
    if monthly_value != monthly_value or monthly_value in (float("inf"), float("-inf")):
        raise ValueError(f"monthly rate for {rate.component_id!r} must be finite")
    weight = rate.weight_fraction
    if isinstance(weight, bool) or not isinstance(weight, (int, float)):
        raise ValueError(f"weight for {rate.component_id!r} must be numeric")
    weight_value = float(weight)
    if weight_value != weight_value or weight_value in (float("inf"), float("-inf")):
        raise ValueError(f"weight for {rate.component_id!r} must be finite")
    if weight_value <= 0.0:
        raise ValueError(f"weight for {rate.component_id!r} must be positive")
    return rate


def compute_trim_median(rates: Sequence[ComponentRate]) -> TrimMedianResult:
    """Rank by rate and return the trimmed mean plus weighted median."""
    items = [_check_rate(rate) for rate in rates]
    if not items:
        raise ValueError("need at least one component rate")
    if len(items) > MAX_CPI_COMPONENTS:
        raise ValueError(f"component count {len(items)} exceeds the {MAX_CPI_COMPONENTS} cap")
    seen: set[str] = set()
    for rate in items:
        if rate.component_id in seen:
            raise ValueError(f"duplicate component_id: {rate.component_id!r}")
        seen.add(rate.component_id)
    weight_total = sum(rate.weight_fraction for rate in items)
    if abs(weight_total - 1.0) > WEIGHT_SUM_TOLERANCE:
        raise ValueError(
            f"weight fractions sum to {weight_total:.9f}, expected 1.0 "
            f"within {WEIGHT_SUM_TOLERANCE}"
        )
    ordered = sorted(items, key=lambda rate: (rate.monthly_rate_percent, rate.component_id))
    cumulative = 0.0
    median_rate = 0.0
    median_id = ""
    lower_excluded: list[str] = []
    upper_excluded: list[str] = []
    trim_numerator = 0.0
    kept_total = 0.0
    for rate in ordered:
        previous = cumulative
        cumulative += rate.weight_fraction
        if not median_id and cumulative > 0.50:
            median_rate = float(rate.monthly_rate_percent)
            median_id = rate.component_id
        if previous < LOWER_CUMULATIVE:
            lower_excluded.append(rate.component_id)
        if cumulative > UPPER_CUMULATIVE:
            upper_excluded.append(rate.component_id)
        kept = max(0.0, min(cumulative, UPPER_CUMULATIVE) - max(previous, LOWER_CUMULATIVE))
        trim_numerator += float(rate.monthly_rate_percent) * kept
        kept_total += kept
    if not median_id:
        raise ValueError("median lookup failed: weights must sum to one")
    expected_kept = UPPER_CUMULATIVE - LOWER_CUMULATIVE
    if abs(kept_total - expected_kept) > 1e-9:
        raise ValueError(f"kept weight {kept_total:.12f} must renormalize to {expected_kept:.2f}")
    trim = trim_numerator / kept_total
    if trim != trim or trim in (float("inf"), float("-inf")):
        raise ValueError("trim computation overflowed")
    return TrimMedianResult(
        trim_mom_percent=trim,
        median_mom_percent=median_rate,
        median_component_id=median_id,
        lower_excluded=tuple(lower_excluded),
        upper_excluded=tuple(upper_excluded),
        kept_weight_fraction=kept_total,
        excluded_weight_fraction=1.0 - kept_total,
    )
