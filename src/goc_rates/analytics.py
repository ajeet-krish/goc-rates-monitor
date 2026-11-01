"""Phase 2 analytics: slopes, butterfly, z scores, carry roll, spreads."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from goc_rates.dates import parse_strict_iso_date
from goc_rates.limits import (
    MAX_ABS_SLOPE_BP,
    MAX_CARRY_HORIZON,
    MAX_HISTORY_OBS,
    MAX_SPREAD_RECORDS,
    MAX_YIELD,
    MIN_YIELD,
)

SLOPE_PAIRS: tuple[tuple[str, str], ...] = (
    ("2Y", "5Y"),
    ("2Y", "10Y"),
    ("5Y", "30Y"),
    ("10Y", "30Y"),
)

Z_LOOKBACK = 252
CARRY_HORIZON_YEARS = 0.25


def _check_finite(value: float, name: str) -> float:
    """Validate a finite numeric input and return it as float."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be finite")
    return result


def _check_yield(value: float, name: str) -> float:
    """Validate a yield in percent and return it as float."""
    result = _check_finite(value, name)
    if not MIN_YIELD <= result <= MAX_YIELD:
        raise ValueError(f"{name} must be within [{MIN_YIELD}, {MAX_YIELD}] percent")
    return result


def _check_slope_bp(value: float, name: str) -> float:
    """Validate a slope in bp against the absolute cap, else raise."""
    result = _check_finite(value, name)
    if abs(result) > MAX_ABS_SLOPE_BP:
        raise ValueError(f"{name} exceeds the {MAX_ABS_SLOPE_BP} bp cap")
    return result


def slope_bp(short_yield_percent: float, long_yield_percent: float) -> float:
    """Return the slope in bp: (long minus short) times 100."""
    short = _check_yield(short_yield_percent, "short_yield_percent")
    long = _check_yield(long_yield_percent, "long_yield_percent")
    result = (long - short) * 100.0
    return _check_slope_bp(result, "slope_bp")


def butterfly_bp(
    short_yield_percent: float, belly_yield_percent: float, long_yield_percent: float
) -> float:
    """Return the butterfly in bp: belly minus the average of the wings."""
    short = _check_yield(short_yield_percent, "short_yield_percent")
    belly = _check_yield(belly_yield_percent, "belly_yield_percent")
    long = _check_yield(long_yield_percent, "long_yield_percent")
    result = (belly - (short + long) / 2.0) * 100.0
    return _check_slope_bp(result, "butterfly_bp")


def z_score(current_value: float, history: Sequence[float]) -> float | None:
    """Return the trailing z score excluding the current observation.

    History must hold at least Z_LOOKBACK values. Returns None when the
    history is short or the sample standard deviation is zero.
    """
    current = _check_finite(current_value, "current_value")
    if len(history) < Z_LOOKBACK:
        return None
    if len(history) > MAX_HISTORY_OBS:
        raise ValueError(f"history exceeds the {MAX_HISTORY_OBS} observation cap")
    raw_window = list(history[-Z_LOOKBACK:])
    window = [_check_finite(item, "history value") for item in raw_window]
    mean = sum(window) / float(len(window))
    variance = sum((item - mean) ** 2.0 for item in window) / float(len(window) - 1)
    if variance <= 0.0:
        return None
    stdev = math.sqrt(variance)
    if stdev == 0.0:
        return None
    result = (current - mean) / stdev
    if not math.isfinite(result):
        raise ValueError("z score must be finite")
    return result


def carry_roll_bp(
    yield_at_maturity_percent: float,
    yield_at_rolled_tenor_percent: float,
    horizon_years: float = CARRY_HORIZON_YEARS,
) -> float:
    """Return simplified carry plus roll in bp, ex coupon and ex funding.

    carry = y * h plus roll where roll = y_rolled minus y, both read off
    the unchanged curve. Yields are in percent, horizon in years.
    """
    long_yield = _check_yield(yield_at_maturity_percent, "yield_at_maturity_percent")
    rolled = _check_yield(yield_at_rolled_tenor_percent, "yield_at_rolled_tenor_percent")
    horizon = _check_finite(horizon_years, "horizon_years")
    if horizon <= 0.0:
        raise ValueError("horizon_years must be positive")
    if horizon > MAX_CARRY_HORIZON:
        raise ValueError(f"horizon_years exceeds the {MAX_CARRY_HORIZON} year cap")
    carry_percent = long_yield * horizon + (rolled - long_yield)
    result = carry_percent * 100.0
    if not math.isfinite(result):
        raise ValueError("carry_roll_bp must be finite")
    return result


def canada_us_spread_bp(ca_yield_percent: float, us_yield_percent: float) -> float:
    """Return the Canada minus US spread in bp from same date yields."""
    ca_yield = _check_yield(ca_yield_percent, "ca_yield_percent")
    us_yield = _check_yield(us_yield_percent, "us_yield_percent")
    result = (ca_yield - us_yield) * 100.0
    return _check_slope_bp(result, "spread_bp")


def inner_join_dates(ca_by_date: Mapping[str, float], us_by_date: Mapping[str, float]) -> list[str]:
    """Return sorted joint dates present in both legs, with no filling.

    Values are validated as finite numerics. A date missing from either
    leg (for example a one sided holiday) is dropped.
    """
    if not isinstance(ca_by_date, Mapping) or not isinstance(us_by_date, Mapping):
        raise ValueError("histories must be mappings")
    if len(ca_by_date) > MAX_HISTORY_OBS or len(us_by_date) > MAX_HISTORY_OBS:
        raise ValueError(f"histories exceed the {MAX_HISTORY_OBS} observation cap")
    joint: list[str] = []
    for date in ca_by_date:
        if date in us_by_date:
            if not isinstance(date, str):
                raise ValueError("history dates must be strict ISO strings")
            parse_strict_iso_date(date)
            ca_value = ca_by_date[date]
            us_value = us_by_date[date]
            _check_yield(ca_value, "ca value")
            _check_yield(us_value, "us value")
            joint.append(date)
    if len(joint) > MAX_SPREAD_RECORDS:
        raise ValueError(f"joint dates exceed the {MAX_SPREAD_RECORDS} record cap")
    joint.sort()
    return joint
