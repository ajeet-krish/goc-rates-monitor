"""Minimal coverage for cashflow schedules and true bootstrap."""

from __future__ import annotations

import datetime as dt

from goc_rates.bootstrap import (
    BOOTSTRAP_METHOD,
    Instrument,
    bootstrap_curve,
    build_bootstrap_curve_section,
    discount_factor,
    price_from_curve,
    zero_yield_percent,
)
from goc_rates.cashflows import (
    accrued_interest,
    dirty_price_from_yield,
    generate_cashflows,
)
from goc_rates.config import BenchmarkIssue, load_benchmark_map
from goc_rates.models import make_quantity


def _ten_year_issue() -> BenchmarkIssue:
    """Return the 10Y benchmark issue from the map."""
    return BenchmarkIssue(
        maturity_date=dt.date(2036, 6, 1),
        coupon_percent=3.25,
        payments_per_year=2,
    )


def test_cashflows_par_on_coupon_date() -> None:
    """Settlement on a coupon date prices at par when yield equals coupon."""
    settlement = dt.date(2026, 12, 1)
    issue = _ten_year_issue()
    flows = generate_cashflows(settlement, issue)
    assert len(flows) == 19
    assert flows[0].payment_date == dt.date(2027, 6, 1)
    assert flows[-1].payment_date == dt.date(2036, 6, 1)
    assert flows[-1].amount_per_100_face == 101.625
    assert accrued_interest(settlement, issue) == 0.0
    price = dirty_price_from_yield(settlement, issue, 3.25)
    assert abs(price - 100.0) < 0.05


def test_cashflows_strictly_after_settlement() -> None:
    """Cashflows exclude the settlement date itself when it is a coupon date."""
    settlement = dt.date(2026, 12, 1)
    flows = generate_cashflows(settlement, _ten_year_issue())
    assert all(flow.payment_date > settlement for flow in flows)
    assert all(flow.years_from_settlement > 0.0 for flow in flows)


def test_bootstrap_reprices_inputs() -> None:
    """Bootstrapped discounts reprice every benchmark bond within tolerance."""
    benchmark_map = load_benchmark_map("config/benchmark_map.yaml")
    settlement = dt.date(2026, 12, 1)
    yields = {"2Y": 3.0, "5Y": 3.1, "10Y": 3.25, "30Y": 3.5}
    instruments = [
        Instrument(
            tenor_label=label,
            issue=benchmark_map.benchmarks[label].issue,
            yield_percent=yields[label],
        )
        for label in ("2Y", "5Y", "10Y", "30Y")
    ]
    curve = bootstrap_curve(settlement, instruments)
    assert curve.method == BOOTSTRAP_METHOD
    assert len(curve.anchors) == 4
    discounts = [discount_factor(curve, anchor.years_from_settlement) for anchor in curve.anchors]
    assert all(first > second for first, second in zip(discounts, discounts[1:], strict=False))
    for instrument in instruments:
        target = dirty_price_from_yield(settlement, instrument.issue, instrument.yield_percent)
        model = price_from_curve(curve, settlement, instrument.issue)
        assert abs(model - target) * 100.0 <= 1.0
        residual_years = (instrument.issue.maturity_date - settlement).days / 365.0
        assert -20.0 <= zero_yield_percent(curve, residual_years) <= 30.0


def test_bootstrap_section_shape() -> None:
    """The snapshot section carries zero flags, residual knots, and reprice errors."""
    benchmark_map = load_benchmark_map("config/benchmark_map.yaml")
    settlement = dt.date(2026, 12, 1)
    benchmark_yields = {
        label: make_quantity(value, "percent", "observed", f"valet:{label}")
        for label, value in (
            ("2Y", 3.0),
            ("5Y", 3.1),
            ("10Y", 3.25),
            ("30Y", 3.5),
        )
    }
    section = build_bootstrap_curve_section(
        benchmark_yields, benchmark_map, settlement, "derived:curve"
    )
    assert section["method"] == BOOTSTRAP_METHOD
    assert section["is_par_approx"] is False
    assert section["is_zero"] is True
    assert section["settlement_date"] == "2026-12-01"
    assert len(section["knots"]) == 4
    assert len(section["anchors"]) == 4
    for row in section["instruments"]:
        assert row["cashflow_count"] > 0
        assert row["reprice_error_bp"]["value"] <= 1.0
        assert row["dirty_price"]["unit"] == "price_units_per_100_face"
    assert section["long_proxy_note"] == "30Y tenor used directly"


def test_coupon_dates_anchor_to_maturity_without_drift() -> None:
    """August 31 maturities keep month ends across leap years without decay."""
    from goc_rates.cashflows import _previous_coupon_date, generate_cashflows
    from goc_rates.config import BenchmarkIssue

    issue = BenchmarkIssue(
        maturity_date=dt.date(2028, 8, 31),
        coupon_percent=3.0,
        payments_per_year=2,
    )
    settlement = dt.date(2027, 8, 30)
    flows = generate_cashflows(settlement, issue)
    dates = [flow.payment_date for flow in flows]
    assert dates[-1] == dt.date(2028, 8, 31)
    assert dt.date(2028, 2, 29) in dates
    assert dt.date(2027, 8, 31) in dates
    assert dt.date(2027, 8, 29) not in dates
    assert all(day > settlement for day in dates)
    previous = _previous_coupon_date(dt.date(2028, 2, 29), issue.maturity_date)
    assert previous == dt.date(2028, 2, 29)
    previous_before = _previous_coupon_date(dt.date(2028, 2, 28), issue.maturity_date)
    assert previous_before == dt.date(2027, 8, 31)


def test_negative_coupon_rejected_at_load(tmp_path: object) -> None:
    """A negative coupon percent fails closed at benchmark map load."""
    from pathlib import Path as _Path

    import pytest

    from goc_rates.config import load_benchmark_map

    fixture = _Path("config/benchmark_map.yaml").read_text(encoding="utf-8")
    assert isinstance(tmp_path, _Path)
    bad = fixture.replace("coupon_percent: 3.0", "coupon_percent: -1.0", 1)
    candidate = tmp_path / "benchmark_map.yaml"
    candidate.write_text(bad, encoding="utf-8")
    with pytest.raises(ValueError, match="coupon_percent"):
        load_benchmark_map(candidate)
