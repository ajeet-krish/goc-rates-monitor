"""Phase 2 curve engine: par approx on a semiannual log discount curve.

Method: par_approx_semiannual_log_discount_v1. Benchmark YTM inputs are
treated as par approximations. Each knot maps to a discount proxy
D = 1 / (1 + y / 2) ^ (2 * T). Between knots the log discount is linear.
Ends are flat in yield. Long is a 30Y proxy and is labelled as such.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from goc_rates.limits import (
    MAX_BILL_DAYS,
    MAX_KNOTS,
    MAX_TENOR_YEARS,
    MAX_YIELD,
    MIN_YIELD,
)
from goc_rates.models import Quantity, make_quantity

CURVE_METHOD = "par_approx_semiannual_log_discount_v1"
MIN_KNOTS = 3

TENOR_YEARS: dict[str, float] = {
    "2Y": 2.0,
    "5Y": 5.0,
    "10Y": 10.0,
    "30Y": 30.0,
    "LONG": 30.0,
}

DERIVED_SOURCE = "derived:curve"


@dataclass(frozen=True)
class CurveKnot:
    """One par approx knot: tenor label, years, and yield in percent."""

    tenor_label: str
    tenor_years: float
    yield_percent: float


@dataclass(frozen=True)
class Curve:
    """A par approx curve with frozen knots and a method id."""

    knots: tuple[CurveKnot, ...]
    method: str = CURVE_METHOD
    is_par_approx: bool = True
    is_zero: bool = False


def _check_finite(value: float, name: str) -> float:
    """Return value when finite, else raise."""
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


def bill_price_from_yield(
    yield_percent: float, days_to_maturity: int, face: float = 100.0
) -> float:
    """Return bill price in price units per face from ACT/365 add on yield.

    P = F / (1 + Y * t / 365). Units: yield in percent, price in
    price_units_per_100_face when face is 100.
    """
    rate = _check_yield(yield_percent, "yield_percent") / 100.0
    if not isinstance(days_to_maturity, int) or isinstance(days_to_maturity, bool):
        raise ValueError("days_to_maturity must be an int")
    if days_to_maturity <= 0:
        raise ValueError("days_to_maturity must be positive")
    if days_to_maturity > MAX_BILL_DAYS:
        raise ValueError(f"days_to_maturity exceeds the {MAX_BILL_DAYS} day cap")
    face_value = _check_finite(face, "face")
    if face_value <= 0.0:
        raise ValueError("face must be positive")
    try:
        result = face_value / (1.0 + rate * float(days_to_maturity) / 365.0)
    except (OverflowError, ZeroDivisionError):
        raise ValueError("bill price computation overflowed") from None
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError("bill price must be finite and positive")
    return result


def bill_discount_factor(price: float, face: float = 100.0) -> float:
    """Return the discount factor D = P / F (unitless ratio)."""
    price_value = _check_finite(price, "price")
    face_value = _check_finite(face, "face")
    if face_value <= 0.0:
        raise ValueError("face must be positive")
    if price_value <= 0.0 or price_value > face_value:
        raise ValueError("price must be in (0, face]")
    result = price_value / face_value
    if not math.isfinite(result) or not 0.0 < result <= 1.0:
        raise ValueError("discount factor must be finite and in (0, 1]")
    return result


def bill_zero_yield_semiannual(discount_factor: float, years: float) -> float:
    """Return the semiannual zero yield in percent from D and T.

    y = 2 * (D ^ (-1 / (2 * T)) - 1) * 100. Units: percent.
    """
    discount = _check_finite(discount_factor, "discount_factor")
    tenor = _check_tenor(years, "years")
    if discount <= 0.0 or discount > 1.0:
        raise ValueError("discount_factor must be in (0, 1]")
    try:
        result = float(2.0 * (discount ** (-1.0 / (2.0 * tenor)) - 1.0) * 100.0)
    except (OverflowError, ZeroDivisionError):
        raise ValueError("bill zero yield computation overflowed") from None
    if not math.isfinite(result):
        raise ValueError("bill zero yield must be finite")
    if not MIN_YIELD <= result <= MAX_YIELD:
        raise ValueError("bill zero yield is outside the supported range")
    return result


def _knot_discount(yield_percent: float, tenor_years: float) -> float:
    """Return the discount proxy for one knot."""
    rate = _check_yield(yield_percent, "yield_percent") / 100.0
    tenor = _check_tenor(tenor_years, "tenor_years")
    if 1.0 + rate / 2.0 <= 0.0:
        raise ValueError("yield_percent implies a non positive semiannual base")
    try:
        result = float(1.0 / ((1.0 + rate / 2.0) ** (2.0 * tenor)))
    except (OverflowError, ZeroDivisionError):
        raise ValueError("knot discount computation overflowed") from None
    if not math.isfinite(result) or not 0.0 < result <= 1.0:
        raise ValueError("knot discount must be finite and in (0, 1]")
    return result


def _check_half_year_grid(tenor_years: float) -> None:
    """Require tenors on a half year grid, else fail closed."""
    periods = tenor_years * 2.0
    if abs(periods - round(periods)) > 1e-9:
        raise ValueError(f"tenor_years must sit on a half year grid: {tenor_years!r}")


def build_par_curve(knots: Sequence[CurveKnot]) -> Curve:
    """Build a par approx curve from at least MIN_KNOTS knots.

    Knots must arrive sorted by strictly increasing tenor_years, each on
    the half year grid, with finite yields. Long must already be mapped
    to 30.0 years by the caller.
    """
    if not isinstance(knots, (list, tuple)) or len(knots) < MIN_KNOTS:
        raise ValueError(f"need at least {MIN_KNOTS} knots")
    if len(knots) > MAX_KNOTS:
        raise ValueError(f"curve holds more than the {MAX_KNOTS} knot cap")
    ordered: list[CurveKnot] = list(knots)
    for knot in ordered:
        if not isinstance(knot, CurveKnot):
            raise ValueError("knots must be CurveKnot records")
        _check_tenor(knot.tenor_years, "tenor_years")
        _check_yield(knot.yield_percent, "yield_percent")
        if not isinstance(knot.tenor_label, str) or not knot.tenor_label.strip():
            raise ValueError("tenor_label must be a non empty string")
        _check_half_year_grid(knot.tenor_years)
    tenors = [knot.tenor_years for knot in ordered]
    for first, second in zip(tenors, tenors[1:], strict=False):
        if not second > first:
            raise ValueError("knot tenors must be strictly increasing")
    discounts = [_knot_discount(knot.yield_percent, knot.tenor_years) for knot in ordered]
    for first, second in zip(discounts, discounts[1:], strict=False):
        if not first > second:
            raise ValueError("knot discounts must be strictly decreasing")
    return Curve(knots=tuple(ordered))


def discount_factor(curve: Curve, tenor_years: float) -> float:
    """Return D(T) with log linear interpolation and flat yield ends.

    Between knots ln D is linear in T. At or outside the ends the nearest
    knot yield is held flat, so D(T) = 1 / (1 + y_end / 2) ^ (2 * T).
    Units: unitless ratio in (0, 1].
    """
    if not isinstance(curve, Curve):
        raise ValueError("curve must be a Curve")
    tenor = _check_tenor(tenor_years, "tenor_years")
    knots = curve.knots
    if len(knots) < MIN_KNOTS:
        raise ValueError("curve holds too few knots")
    if len(knots) > MAX_KNOTS:
        raise ValueError("curve holds too many knots")
    if tenor <= knots[0].tenor_years:
        return _knot_discount(knots[0].yield_percent, tenor)
    if tenor >= knots[-1].tenor_years:
        return _knot_discount(knots[-1].yield_percent, tenor)
    for lower, upper in zip(knots, knots[1:], strict=False):
        if lower.tenor_years <= tenor <= upper.tenor_years:
            discount_lower = _knot_discount(lower.yield_percent, lower.tenor_years)
            discount_upper = _knot_discount(upper.yield_percent, upper.tenor_years)
            log_lower = math.log(discount_lower)
            log_upper = math.log(discount_upper)
            weight = (tenor - lower.tenor_years) / (upper.tenor_years - lower.tenor_years)
            try:
                result = float(math.exp(log_lower + weight * (log_upper - log_lower)))
            except (OverflowError, ValueError):
                raise ValueError("discount interpolation overflowed") from None
            if not math.isfinite(result) or not 0.0 < result <= 1.0:
                raise ValueError("interpolated discount must be in (0, 1]")
            return result
    raise ValueError("tenor fell outside the knot range")


def zero_yield(curve: Curve, tenor_years: float) -> float:
    """Return the semiannual zero yield in percent at tenor T."""
    discount = discount_factor(curve, tenor_years)
    tenor = _check_tenor(tenor_years, "tenor_years")
    try:
        result = float(2.0 * (discount ** (-1.0 / (2.0 * tenor)) - 1.0) * 100.0)
    except (OverflowError, ZeroDivisionError):
        raise ValueError("zero yield computation overflowed") from None
    if not math.isfinite(result):
        raise ValueError("zero yield must be finite")
    if not MIN_YIELD <= result <= MAX_YIELD:
        raise ValueError("zero yield is outside the supported range")
    return result


def forward_yield(curve: Curve, start_years: float, end_years: float) -> float:
    """Return the semiannual forward yield in percent between two tenors."""
    start = _check_tenor(start_years, "start_years")
    end = _check_tenor(end_years, "end_years")
    if not end > start:
        raise ValueError("end_years must exceed start_years")
    discount_start = discount_factor(curve, start)
    discount_end = discount_factor(curve, end)
    years = end - start
    try:
        result = float(
            2.0 * ((discount_start / discount_end) ** (1.0 / (2.0 * years)) - 1.0) * 100.0
        )
    except (OverflowError, ZeroDivisionError):
        raise ValueError("forward yield computation overflowed") from None
    if not math.isfinite(result):
        raise ValueError("forward yield must be finite")
    if not MIN_YIELD <= result <= MAX_YIELD:
        raise ValueError("forward yield is outside the supported range")
    return result


def reprice_par_yield_bp(curve: Curve, tenor_years: float) -> float:
    """Return the reprice error in bp at a knot tenor.

    The curve zero yield at the knot minus the input knot yield, times
    100. Only defined at knot tenors, else raises.
    """
    tenor = _check_tenor(tenor_years, "tenor_years")
    match: CurveKnot | None = None
    for knot in curve.knots:
        if abs(knot.tenor_years - tenor) < 1e-9:
            match = knot
            break
    if match is None:
        raise ValueError("reprice is only defined at knot tenors")
    repriced = zero_yield(curve, match.tenor_years)
    result = (repriced - match.yield_percent) * 100.0
    if not math.isfinite(result):
        raise ValueError("reprice error must be finite")
    return result


def _quantity_yield_percent(entry: Any, tenor: str) -> float:
    """Extract a percent yield value from a Quantity, failing closed."""
    if not isinstance(entry, dict):
        raise ValueError(f"benchmark {tenor!r} must be a Quantity mapping")
    unit = entry.get("unit")
    if unit not in ("percent", "percent_yield"):
        raise ValueError(f"benchmark {tenor!r} unit must be percent or percent_yield")
    value = entry.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"benchmark {tenor!r} value must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"benchmark {tenor!r} value must be finite")
    if not MIN_YIELD <= result <= MAX_YIELD:
        raise ValueError(f"benchmark {tenor!r} yield is outside the supported range")
    quality = entry.get("quality")
    if quality != "observed":
        raise ValueError(f"benchmark {tenor!r} quality must be observed")
    source = entry.get("source_id")
    if not isinstance(source, str) or not source.strip():
        raise ValueError(f"benchmark {tenor!r} source_id must be non empty")
    return result


def build_curve_section(
    benchmark_yields: Mapping[str, Quantity],
    source_id: str = DERIVED_SOURCE,
) -> dict[str, Any]:
    """Adapt Quantity inputs to snapshot curve sections, failing closed.

    Accepts tenor keys 2Y, 5Y, 10Y, and 30Y or LONG (LONG is stored as a
    30Y proxy with a label note). Returns knots, discounts, and zero
    yields with explicit units and a derived source.
    """
    if not isinstance(benchmark_yields, Mapping) or not benchmark_yields:
        raise ValueError("benchmark_yields must be a non empty mapping")
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id must be a non empty string")
    normalized: dict[str, float] = {}
    long_proxy = False
    for tenor in ("2Y", "5Y", "10Y", "30Y", "LONG"):
        if tenor in benchmark_yields:
            raw_key = tenor
            target = "30Y" if tenor == "LONG" else tenor
            if target in normalized:
                raise ValueError("duplicate long tenor: supply 30Y or LONG, not both")
            normalized[target] = _quantity_yield_percent(benchmark_yields[raw_key], raw_key)
            if tenor == "LONG":
                long_proxy = True
    ordered_labels = ["2Y", "5Y", "10Y", "30Y"]
    missing = [label for label in ordered_labels if label not in normalized]
    if missing:
        raise ValueError(f"missing benchmark tenors: {missing}")
    knots = [
        CurveKnot(
            tenor_label=label,
            tenor_years=TENOR_YEARS[label],
            yield_percent=normalized[label],
        )
        for label in ordered_labels
    ]
    curve = build_par_curve(knots)
    knot_rows: list[dict[str, Any]] = []
    discounts: dict[str, Quantity] = {}
    zero_yields: dict[str, Quantity] = {}
    for knot in curve.knots:
        discount = _knot_discount(knot.yield_percent, knot.tenor_years)
        discounts[knot.tenor_label] = make_quantity(
            discount, "unitless_ratio", "observed", source_id
        )
        zero = zero_yield(curve, knot.tenor_years)
        zero_yields[knot.tenor_label] = make_quantity(zero, "percent_yield", "observed", source_id)
        knot_rows.append(
            {
                "tenor": knot.tenor_label,
                "tenor_years": knot.tenor_years,
                "tenor_unit": "duration_years",
                "yield_percent": knot.yield_percent,
                "yield_unit": "percent_yield",
                "discount": discount,
                "discount_unit": "unitless_ratio",
                "source_id": source_id,
            }
        )
    section: dict[str, Any] = {
        "method": CURVE_METHOD,
        "is_par_approx": True,
        "is_zero": False,
        "knots": knot_rows,
        "discounts": discounts,
        "zero_yields": zero_yields,
        "curve_source_id": source_id,
    }
    if long_proxy:
        section["long_proxy_note"] = "LONG treated as 30Y proxy"
    else:
        section["long_proxy_note"] = "30Y tenor used directly"
    return section
