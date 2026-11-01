"""Phase 2 risk: par bond price, modified duration, DV01 per million."""

from __future__ import annotations

import math

from goc_rates.limits import MAX_PERIODS, MAX_TENOR_YEARS, MAX_YIELD, MIN_YIELD

__all__ = [
    "MAX_PERIODS",
    "MAX_TENOR_YEARS",
    "MAX_YIELD",
    "MIN_YIELD",
    "dv01_per_million",
    "modified_duration",
    "par_bond_price",
]


def _check_finite(value: float, name: str) -> float:
    """Return value when numeric and finite, else raise."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be finite")
    return result


def _check_yield(value: float, name: str) -> float:
    """Return a yield in percent within the supported range, else raise."""
    result = _check_finite(value, name)
    if not MIN_YIELD <= result <= MAX_YIELD:
        raise ValueError(f"{name} must be within [{MIN_YIELD}, {MAX_YIELD}] percent")
    return result


def _check_tenor(value: float, name: str) -> float:
    """Return a tenor in years within the supported cap, else raise."""
    result = _check_finite(value, name)
    if result <= 0.0:
        raise ValueError(f"{name} must be positive")
    if result > MAX_TENOR_YEARS:
        raise ValueError(f"{name} exceeds the {MAX_TENOR_YEARS} year cap")
    return result


def par_bond_price(
    yield_percent: float, tenor_years: float, coupon_percent: float | None = None
) -> float:
    """Return the clean price per 100 with semiannual discounting.

    P = sum CF_n / (1 + y / 2) ^ n. Coupon defaults to the yield so a par
    bond prices at 100. Units: price_units_per_100_face.
    """
    rate = _check_yield(yield_percent, "yield_percent")
    tenor = _check_tenor(tenor_years, "tenor_years")
    periods = tenor * 2.0
    if abs(periods - round(periods)) > 1e-9:
        raise ValueError("tenor_years must sit on a half year grid")
    count = int(round(periods))
    if count > MAX_PERIODS:
        raise ValueError(f"tenor implies {count} periods above the {MAX_PERIODS} cap")
    coupon = rate if coupon_percent is None else _check_yield(coupon_percent, "coupon_percent")
    per_period = (1.0 + rate / 200.0) if abs(rate) > 0.0 else 1.0
    if per_period <= 0.0:
        raise ValueError("yield implies a non positive discount base")
    cash = coupon / 2.0
    price = 0.0
    for period in range(1, count + 1):
        flow = cash + (100.0 if period == count else 0.0)
        try:
            price += flow / (per_period**period)
        except OverflowError:
            raise ValueError("par bond price overflowed") from None
        except ZeroDivisionError:
            raise ValueError("par bond price divided by zero") from None
    if not math.isfinite(price) or price <= 0.0:
        raise ValueError("par bond price must be finite and positive")
    return price


def modified_duration(
    yield_percent: float, tenor_years: float, coupon_percent: float | None = None
) -> float:
    """Return modified duration in years for semiannual compounding.

    Macaulay duration over discounted cash flows divided by (1 + y / 2).
    Units: duration_years.
    """
    rate = _check_yield(yield_percent, "yield_percent")
    price = par_bond_price(rate, tenor_years, coupon_percent)
    if price <= 0.0:
        raise ValueError("price must be positive")
    tenor = _check_tenor(tenor_years, "tenor_years")
    count = int(round(tenor * 2.0))
    if count > MAX_PERIODS:
        raise ValueError(f"tenor implies {count} periods above the {MAX_PERIODS} cap")
    coupon = rate if coupon_percent is None else _check_yield(coupon_percent, "coupon_percent")
    cash = coupon / 2.0
    per_period = 1.0 + rate / 200.0
    if per_period <= 0.0:
        raise ValueError("yield implies a non positive discount base")
    weighted = 0.0
    for period in range(1, count + 1):
        flow = cash + (100.0 if period == count else 0.0)
        try:
            present = flow / (per_period**period)
        except OverflowError:
            raise ValueError("modified duration overflowed") from None
        except ZeroDivisionError:
            raise ValueError("modified duration divided by zero") from None
        weighted += (float(period) / 2.0) * present
    macaulay = weighted / price
    result = macaulay / per_period
    if not math.isfinite(result) or result < 0.0:
        raise ValueError("modified duration must be finite and non negative")
    return result


def dv01_per_million(price_per_100: float, modified_duration_years: float) -> float:
    """Return DV01 per one million notional in currency units.

    DV01 per 100 is ModDur * P * 0.0001. Scaling to one million gives
    ModDur * P. Units: dv01_per_million.
    """
    price = _check_finite(price_per_100, "price_per_100")
    duration = _check_finite(modified_duration_years, "modified_duration_years")
    if price <= 0.0:
        raise ValueError("price_per_100 must be positive")
    if duration < 0.0:
        raise ValueError("modified_duration_years must be non negative")
    result = duration * price
    if not math.isfinite(result):
        raise ValueError("dv01_per_million must be finite")
    return result
