"""True semiannual bootstrap on a log discount curve.

Method true_bootstrap_semiannual_log_discount_v1 prices each benchmark
bond from its quoted par yield, then solves sequentially for the
discount anchor at each maturity with bisection. Between anchors the log
discount is linear in ACT/365 years, with D equal to one at settlement.
Beyond the last anchor the zero rate is held flat for extrapolation.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from goc_rates.cashflows import (
    CashFlow,
    dirty_price_from_yield,
    generate_cashflows,
)
from goc_rates.config import BenchmarkIssue, BenchmarkMap
from goc_rates.limits import (
    BOOTSTRAP_PRICE_TOLERANCE_BP,
    MAX_BOOTSTRAP_ANCHORS,
    MAX_TENOR_YEARS,
    MAX_YIELD,
    MIN_YIELD,
)
from goc_rates.models import Quantity, make_quantity

BOOTSTRAP_METHOD = "true_bootstrap_semiannual_log_discount_v1"

DERIVED_SOURCE = "derived:curve"

_MAX_BISECTION_ITERS = 200

_MIN_DISCOUNT = 1e-12


@dataclass(frozen=True)
class Instrument:
    """One benchmark bond entering the bootstrap with its par yield.

    The yield uses percent and is treated as the dirty price target
    through dirty_price_from_yield.
    """

    tenor_label: str
    issue: BenchmarkIssue
    yield_percent: float


@dataclass(frozen=True)
class DiscountAnchor:
    """One solved discount point: payment date and unitless ratio."""

    payment_date: dt.date
    years_from_settlement: float
    discount: float


@dataclass(frozen=True)
class BootstrappedCurve:
    """A bootstrapped curve with settlement dating and solved anchors."""

    settlement: dt.date
    method: str
    anchors: tuple[DiscountAnchor, ...]
    instruments: tuple[Instrument, ...]


def _check_finite(value: object, name: str) -> float:
    """Return a finite float, else fail closed."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be finite")
    return result


def _check_yield(value: object) -> float:
    """Return a yield in percent within the supported range."""
    result = _check_finite(value, "yield_percent")
    if not MIN_YIELD <= result <= MAX_YIELD:
        raise ValueError("yield_percent is outside the supported range (unit: percent)")
    return result


def _check_years(value: object) -> float:
    """Return a positive tenor within the tenor cap in duration_years."""
    result = _check_finite(value, "years_from_settlement")
    if result <= 0.0:
        raise ValueError("years_from_settlement must be positive (unit: duration_years)")
    if result > MAX_TENOR_YEARS:
        raise ValueError("years_from_settlement exceeds the tenor cap (unit: duration_years)")
    return result


def _check_settlement(value: object) -> dt.date:
    """Return a validated settlement date, rejecting datetimes."""
    if isinstance(value, dt.datetime):
        raise ValueError("settlement must be a date, not a datetime")
    if not isinstance(value, dt.date):
        raise ValueError("settlement must be a date")
    return value


def _anchor_grids(curve: BootstrappedCurve) -> tuple[list[float], list[float]]:
    """Return anchor times and discounts with the settlement origin prepended."""
    if not isinstance(curve, BootstrappedCurve):
        raise ValueError("curve must be a BootstrappedCurve")
    if not curve.anchors:
        raise ValueError("curve holds no anchors")
    if len(curve.anchors) > MAX_BOOTSTRAP_ANCHORS:
        raise ValueError("curve holds more than the anchor cap")
    times = [0.0]
    discounts = [1.0]
    for anchor in curve.anchors:
        if not isinstance(anchor, DiscountAnchor):
            raise ValueError("anchors must be DiscountAnchor records")
        time = _check_years(anchor.years_from_settlement)
        discount = _check_finite(anchor.discount, "discount")
        if not 0.0 < discount <= 1.0:
            raise ValueError("anchor discount must be in (0, 1] (unit: unitless_ratio)")
        if not time > times[-1]:
            raise ValueError("anchor times must be strictly increasing")
        if not discount < discounts[-1]:
            raise ValueError("anchor discounts must be strictly decreasing")
        times.append(time)
        discounts.append(discount)
    return times, discounts


def _interpolate_discount(times: list[float], discounts: list[float], tenor: float) -> float:
    """Return D(T) with log linear interpolation and a flat zero tail.

    Between anchors ln D is linear in T. Beyond the last anchor the zero
    rate is held flat, so D(T) equals the last discount raised to T over
    the last anchor time. Units: unitless ratio in (0, 1].
    """
    moment = _check_years(tenor)
    if moment <= times[-1]:
        for lower_time, upper_time, lower_d, upper_d in zip(
            times, times[1:], discounts, discounts[1:], strict=True
        ):
            if lower_time <= moment <= upper_time:
                if upper_time == lower_time:
                    raise ValueError("anchor times must be distinct")
                weight = (moment - lower_time) / (upper_time - lower_time)
                try:
                    result = float(
                        math.exp(
                            math.log(lower_d) + weight * (math.log(upper_d) - math.log(lower_d))
                        )
                    )
                except (OverflowError, ValueError):
                    raise ValueError("discount interpolation overflowed") from None
                if not math.isfinite(result) or not 0.0 < result <= 1.0:
                    raise ValueError("interpolated discount must be in (0, 1]")
                return result
        raise ValueError("tenor fell outside the anchor range")
    last_time = times[-1]
    last_discount = discounts[-1]
    try:
        result = float(last_discount ** (moment / last_time))
    except (OverflowError, ZeroDivisionError):
        raise ValueError("discount extrapolation overflowed") from None
    if not math.isfinite(result) or not 0.0 < result <= 1.0:
        raise ValueError("extrapolated discount must be in (0, 1]")
    return result


def discount_factor(curve: BootstrappedCurve, years_from_settlement: float) -> float:
    """Return the discount factor D(T) at ACT/365 years from settlement.

    Units: unitless ratio in (0, 1].
    """
    times, discounts = _anchor_grids(curve)
    return _interpolate_discount(times, discounts, years_from_settlement)


def zero_yield_percent(curve: BootstrappedCurve, years_from_settlement: float) -> float:
    """Return the semiannual zero yield in percent at years from settlement."""
    tenor = _check_years(years_from_settlement)
    discount = discount_factor(curve, tenor)
    try:
        result = float(2.0 * (discount ** (-1.0 / (2.0 * tenor)) - 1.0) * 100.0)
    except (OverflowError, ZeroDivisionError):
        raise ValueError("zero yield computation overflowed") from None
    if not math.isfinite(result):
        raise ValueError("zero yield must be finite")
    if not MIN_YIELD <= result <= MAX_YIELD:
        raise ValueError("zero yield is outside the supported range (unit: percent)")
    return result


def price_from_curve(curve: BootstrappedCurve, settlement: dt.date, issue: BenchmarkIssue) -> float:
    """Return the model dirty price per 100 face from curve discounts.

    Every cashflow amount is multiplied by D at its ACT/365 years from
    settlement. The settlement must equal the curve settlement so the
    cashflow times align. Units: price_units_per_100_face.
    """
    if not isinstance(curve, BootstrappedCurve):
        raise ValueError("curve must be a BootstrappedCurve")
    settlement_date = _check_settlement(settlement)
    if settlement_date != curve.settlement:
        raise ValueError("settlement must equal the curve settlement date")
    flows = generate_cashflows(settlement_date, issue)
    total = 0.0
    for flow in flows:
        total += flow.amount_per_100_face * discount_factor(curve, flow.years_from_settlement)
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("model price must be finite and positive")
    return total


def _model_price_with_candidate(
    flows: Sequence[CashFlow],
    times: list[float],
    discounts: list[float],
    maturity_years: float,
    candidate: float,
) -> float:
    """Return the dirty price with a candidate discount at maturity."""
    candidate_value = _check_finite(candidate, "candidate discount")
    if not 0.0 < candidate_value <= 1.0:
        raise ValueError("candidate discount must be in (0, 1]")
    extended_times = [*times, maturity_years]
    extended_discounts = [*discounts, candidate_value]
    total = 0.0
    for flow in flows:
        tenor = _check_years(flow.years_from_settlement)
        if tenor > maturity_years + 1e-12:
            raise ValueError("cashflow falls beyond the candidate maturity")
        total += flow.amount_per_100_face * _interpolate_discount(
            extended_times, extended_discounts, tenor
        )
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("model price must be finite and positive")
    return total


def _solve_anchor_discount(
    flows: Sequence[CashFlow],
    times: list[float],
    discounts: list[float],
    maturity_years: float,
    target_price: float,
) -> float:
    """Solve the maturity discount by bisection within the price tolerance.

    The model price rises monotonically in the candidate discount, so the
    bracket from near zero to the previous anchor discount holds at most
    one root. At most _MAX_BISECTION_ITERS iterations run before failing
    closed. Tolerance uses BOOTSTRAP_PRICE_TOLERANCE_BP in bp.
    """
    previous = discounts[-1]
    low = _MIN_DISCOUNT
    high = previous
    price_high = _model_price_with_candidate(flows, times, discounts, maturity_years, high)
    if price_high < target_price:
        raise ValueError("target price exceeds the attainable discount range")
    price_low = _model_price_with_candidate(flows, times, discounts, maturity_years, low)
    if price_low > target_price:
        raise ValueError("target price falls below the attainable discount range")
    midpoint = (low + high) / 2.0
    for _ in range(_MAX_BISECTION_ITERS):
        midpoint = (low + high) / 2.0
        price = _model_price_with_candidate(flows, times, discounts, maturity_years, midpoint)
        error_bp = abs(price - target_price) * 100.0
        if error_bp <= BOOTSTRAP_PRICE_TOLERANCE_BP:
            break
        if price < target_price:
            low = midpoint
        else:
            high = midpoint
    else:
        midpoint = (low + high) / 2.0
    final_price = _model_price_with_candidate(flows, times, discounts, maturity_years, midpoint)
    if abs(final_price - target_price) * 100.0 > BOOTSTRAP_PRICE_TOLERANCE_BP:
        raise ValueError("bisection did not converge within the price tolerance (unit: bp)")
    if not midpoint < previous:
        raise ValueError("solved discount must sit below the previous anchor")
    return midpoint


def bootstrap_curve(settlement: dt.date, instruments: Sequence[Instrument]) -> BootstrappedCurve:
    """Bootstrap discount anchors sequentially in maturity order.

    Each instrument contributes a dirty price target from its quoted par
    yield. Anchors solve in ascending maturity with earlier anchors held
    fixed and log linear interpolation between them. Maturities must be
    strictly increasing and every solved price must land within
    BOOTSTRAP_PRICE_TOLERANCE_BP.
    """
    settlement_date = _check_settlement(settlement)
    if not isinstance(instruments, (list, tuple)) or not instruments:
        raise ValueError("instruments must be a non empty sequence")
    if len(instruments) > MAX_BOOTSTRAP_ANCHORS:
        raise ValueError("instrument count exceeds the anchor cap")
    ordered: list[Instrument] = []
    seen_labels: set[str] = set()
    for instrument in instruments:
        if not isinstance(instrument, Instrument):
            raise ValueError("instruments must be Instrument records")
        if not isinstance(instrument.tenor_label, str) or not instrument.tenor_label.strip():
            raise ValueError("tenor_label must be a non empty string")
        label = instrument.tenor_label.strip()
        if label in seen_labels:
            raise ValueError(f"duplicate tenor label: {label!r}")
        seen_labels.add(label)
        if not isinstance(instrument.issue, BenchmarkIssue):
            raise ValueError("instrument issue must be a BenchmarkIssue")
        _check_yield(instrument.yield_percent)
        ordered.append(
            Instrument(
                tenor_label=label,
                issue=instrument.issue,
                yield_percent=float(instrument.yield_percent),
            )
        )
    ordered.sort(key=lambda item: (item.issue.maturity_date, item.tenor_label))
    maturities = [item.issue.maturity_date for item in ordered]
    for first, second in zip(maturities, maturities[1:], strict=False):
        if not second > first:
            raise ValueError("instrument maturities must be strictly increasing")
    for maturity in maturities:
        if not maturity > settlement_date:
            raise ValueError("instrument maturities must fall after settlement")
        residual = (maturity - settlement_date).days / 365.0
        if residual > MAX_TENOR_YEARS:
            raise ValueError("residual tenor exceeds the tenor cap (unit: duration_years)")
    times = [0.0]
    discounts = [1.0]
    anchors: list[DiscountAnchor] = []
    for instrument in ordered:
        maturity_date = instrument.issue.maturity_date
        maturity_years = (maturity_date - settlement_date).days / 365.0
        if not maturity_years > times[-1]:
            raise ValueError("maturity years must be strictly increasing")
        flows = generate_cashflows(settlement_date, instrument.issue)
        target = dirty_price_from_yield(settlement_date, instrument.issue, instrument.yield_percent)
        solved = _solve_anchor_discount(flows, times, discounts, maturity_years, target)
        times.append(maturity_years)
        discounts.append(solved)
        anchors.append(
            DiscountAnchor(
                payment_date=maturity_date,
                years_from_settlement=maturity_years,
                discount=solved,
            )
        )
    return BootstrappedCurve(
        settlement=settlement_date,
        method=BOOTSTRAP_METHOD,
        anchors=tuple(anchors),
        instruments=tuple(ordered),
    )


def _quantity_yield_percent(entry: Any, tenor: str) -> float:
    """Extract a percent yield value from a Quantity, failing closed."""
    if not isinstance(entry, dict):
        raise ValueError(f"benchmark {tenor!r} must be a Quantity mapping")
    unit = entry.get("unit")
    if unit not in ("percent", "percent_yield"):
        raise ValueError(f"benchmark {tenor!r} unit must be percent or percent_yield")
    value = entry.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
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


def build_bootstrap_curve_section(
    benchmark_yields: Mapping[str, Quantity],
    benchmark_map: BenchmarkMap,
    settlement_date: dt.date,
    source_id: str = DERIVED_SOURCE,
) -> dict[str, Any]:
    """Build a snapshot curve section from true bootstrap, failing closed.

    Par yields arrive as Quantity mappings keyed by tenor, with LONG
    accepted as an alias for the 30Y benchmark issue. Knot tenors are
    residual ACT/365 years from settlement to each maturity in
    duration_years. The section records the method, zero curve flag,
    per instrument cashflow counts with dirty prices and reprice errors
    in bp, and the solved anchors. Solved discounts and zero yields use
    quality observed (solved present value) with the derived source_id
    to mark provenance.
    """
    if not isinstance(benchmark_yields, Mapping) or not benchmark_yields:
        raise ValueError("benchmark_yields must be a non empty mapping")
    if not isinstance(benchmark_map, BenchmarkMap):
        raise ValueError("benchmark_map must be a BenchmarkMap")
    settlement = _check_settlement(settlement_date)
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("source_id must be a non empty string")
    normalized: dict[str, float] = {}
    long_proxy = False
    for tenor in ("2Y", "5Y", "10Y", "30Y", "LONG"):
        if tenor in benchmark_yields:
            target = "30Y" if tenor == "LONG" else tenor
            if target in normalized:
                raise ValueError("duplicate long tenor: supply 30Y or LONG, not both")
            normalized[target] = _quantity_yield_percent(benchmark_yields[tenor], tenor)
            if tenor == "LONG":
                long_proxy = True
    ordered_labels = ["2Y", "5Y", "10Y", "30Y"]
    missing = [label for label in ordered_labels if label not in normalized]
    if missing:
        raise ValueError(f"missing benchmark tenors: {missing}")
    instruments = [
        Instrument(
            tenor_label=label,
            issue=benchmark_map.benchmarks[label].issue,
            yield_percent=normalized[label],
        )
        for label in ordered_labels
    ]
    curve = bootstrap_curve(settlement, instruments)
    anchor_by_label = {anchor.payment_date: anchor for anchor in curve.anchors}
    knot_rows: list[dict[str, Any]] = []
    discounts: dict[str, Quantity] = {}
    zero_yields: dict[str, Quantity] = {}
    instrument_rows: list[dict[str, Any]] = []
    # Solved discounts and zero yields carry quality observed (meaning a
    # successfully solved present value, as opposed to missing) with a
    # derived source_id (derived:curve) marking provenance. Quality tracks
    # availability while source_id tracks derivation, matching the breaks
    # dod_quantity convention where computed values use observed quality
    # with a derived source.
    for instrument in curve.instruments:
        label = instrument.tenor_label
        maturity = instrument.issue.maturity_date
        anchor = anchor_by_label.get(maturity)
        if anchor is None:
            raise ValueError(f"missing solved anchor for {label!r}")
        residual_years = (maturity - settlement).days / 365.0
        zero = zero_yield_percent(curve, anchor.years_from_settlement)
        discounts[label] = make_quantity(anchor.discount, "unitless_ratio", "observed", source_id)
        zero_yields[label] = make_quantity(zero, "percent_yield", "observed", source_id)
        knot_rows.append(
            {
                "tenor": label,
                "tenor_years": residual_years,
                "tenor_unit": "duration_years",
                "yield_percent": instrument.yield_percent,
                "yield_unit": "percent_yield",
                "discount": anchor.discount,
                "discount_unit": "unitless_ratio",
                "source_id": source_id,
            }
        )
        flows = generate_cashflows(settlement, instrument.issue)
        target_price = dirty_price_from_yield(
            settlement, instrument.issue, instrument.yield_percent
        )
        model_price = price_from_curve(curve, settlement, instrument.issue)
        reprice_error_bp = abs(model_price - target_price) * 100.0
        instrument_rows.append(
            {
                "tenor": label,
                "maturity_date": maturity.isoformat(),
                "coupon_percent": instrument.issue.coupon_percent,
                "coupon_unit": "percent",
                "yield_percent": instrument.yield_percent,
                "yield_unit": "percent_yield",
                "cashflow_count": len(flows),
                "dirty_price": {
                    "value": target_price,
                    "unit": "price_units_per_100_face",
                },
                "reprice_error_bp": {
                    "value": reprice_error_bp,
                    "unit": "bp",
                },
                "source_id": source_id,
            }
        )
    anchor_rows = [
        {
            "payment_date": anchor.payment_date.isoformat(),
            "years_from_settlement": anchor.years_from_settlement,
            "years_unit": "duration_years",
            "discount": anchor.discount,
            "discount_unit": "unitless_ratio",
        }
        for anchor in curve.anchors
    ]
    section: dict[str, Any] = {
        "method": BOOTSTRAP_METHOD,
        "is_par_approx": False,
        "is_zero": True,
        "settlement_date": settlement.isoformat(),
        "knots": knot_rows,
        "discounts": discounts,
        "zero_yields": zero_yields,
        "instruments": instrument_rows,
        "anchors": anchor_rows,
        "curve_source_id": source_id,
    }
    if long_proxy:
        section["long_proxy_note"] = "LONG treated as 30Y proxy"
    else:
        section["long_proxy_note"] = "30Y tenor used directly"
    return section
