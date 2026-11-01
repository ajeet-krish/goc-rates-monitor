"""Phase 2 curve tests against hand computed goldens."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from goc_rates.curve import (
    CURVE_METHOD,
    MIN_KNOTS,
    CurveKnot,
    bill_discount_factor,
    bill_price_from_yield,
    bill_zero_yield_semiannual,
    build_curve_section,
    build_par_curve,
    discount_factor,
    forward_yield,
    reprice_par_yield_bp,
    zero_yield,
)
from goc_rates.models import make_quantity


def _goldens() -> dict[str, object]:
    path = Path(__file__).parent / "fixtures" / "phase2_curve_golden.json"
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_curve_method_and_min_knots() -> None:
    """Method id and minimum knot count stay pinned."""
    assert CURVE_METHOD == "par_approx_semiannual_log_discount_v1"
    assert MIN_KNOTS == 3


def test_bill_4pct_90d_matches_golden() -> None:
    """Bill price, discount, and zero match the hand computed golden."""
    goldens = _goldens()
    bill = goldens["bill_4pct_90d"]
    assert isinstance(bill, dict)
    price = bill_price_from_yield(4.0, 90)
    assert price == pytest.approx(float(str(bill["price"])), abs=1e-9)
    discount = bill_discount_factor(price)
    assert discount == pytest.approx(float(str(bill["discount"])), abs=1e-12)
    zero = bill_zero_yield_semiannual(discount, 90.0 / 365.0)
    assert zero == pytest.approx(float(str(bill["zero_semiannual_percent"])), abs=1e-9)


def test_flat_3pct_curve_matches_golden() -> None:
    """Flat 3 percent curve discounts and zeros match goldens."""
    goldens = _goldens()
    flat = goldens["flat_3pct"]
    assert isinstance(flat, dict)
    knots = [
        CurveKnot("2Y", 2.0, 3.0),
        CurveKnot("5Y", 5.0, 3.0),
        CurveKnot("10Y", 10.0, 3.0),
        CurveKnot("30Y", 30.0, 3.0),
    ]
    curve = build_par_curve(knots)
    assert curve.method == CURVE_METHOD
    discounts = flat["discounts"]
    assert isinstance(discounts, dict)
    for label, tenor in (("2Y", 2.0), ("5Y", 5.0), ("10Y", 10.0), ("30Y", 30.0)):
        assert discount_factor(curve, tenor) == pytest.approx(
            float(str(discounts[label])), abs=1e-12
        )
        assert zero_yield(curve, tenor) == pytest.approx(3.0, abs=1e-9)
    for tenor in (2.0, 5.0, 10.0, 30.0):
        assert reprice_par_yield_bp(curve, tenor) == pytest.approx(0.0, abs=1e-9)


def test_steep_curve_and_midpoint_geometric_mean() -> None:
    """Steep knots match goldens and 3.5Y is the log discount midpoint."""
    goldens = _goldens()
    steep = goldens["steep_curve"]
    assert isinstance(steep, dict)
    knots = [
        CurveKnot("2Y", 2.0, 1.0),
        CurveKnot("5Y", 5.0, 2.0),
        CurveKnot("10Y", 10.0, 3.0),
        CurveKnot("30Y", 30.0, 3.5),
    ]
    curve = build_par_curve(knots)
    discounts = steep["discounts"]
    assert isinstance(discounts, dict)
    assert discount_factor(curve, 2.0) == pytest.approx(float(str(discounts["2Y"])), abs=1e-12)
    mid = goldens["zero_midpoint_3_5y"]
    assert isinstance(mid, dict)
    assert discount_factor(curve, 3.5) == pytest.approx(float(str(mid["discount"])), abs=1e-12)
    assert zero_yield(curve, 3.5) == pytest.approx(float(str(mid["zero_percent"])), abs=1e-9)
    fwd = forward_yield(curve, 2.0, 5.0)
    assert fwd > 2.0


def test_flat_ends_hold_end_yield() -> None:
    """Discount ends extrapolate flat in yield."""
    curve = build_par_curve(
        [
            CurveKnot("2Y", 2.0, 1.0),
            CurveKnot("5Y", 5.0, 2.0),
            CurveKnot("10Y", 10.0, 3.0),
            CurveKnot("30Y", 30.0, 3.5),
        ]
    )
    assert zero_yield(curve, 1.0) == pytest.approx(1.0, abs=1e-9)
    assert zero_yield(curve, 40.0) == pytest.approx(3.5, abs=1e-9)


def test_build_curve_section_quantities_and_long_proxy() -> None:
    """Section adapter uses Quantity inputs and labels the long proxy."""
    section = build_curve_section(
        {
            "2Y": make_quantity(3.0, "percent", "observed", "valet:2Y"),
            "5Y": make_quantity(3.1, "percent", "observed", "valet:5Y"),
            "10Y": make_quantity(3.4, "percent", "observed", "valet:10Y"),
            "LONG": make_quantity(4.0, "percent_yield", "observed", "valet:LONG"),
        }
    )
    assert section["method"] == CURVE_METHOD
    assert section["long_proxy_note"] == "LONG treated as 30Y proxy"
    assert len(section["knots"]) == 4
    discounts = section["discounts"]
    assert isinstance(discounts, dict)
    assert discounts["30Y"]["unit"] == "unitless_ratio"
    assert discounts["30Y"]["source_id"] == "derived:curve"


def test_build_curve_section_fails_closed() -> None:
    """Missing knots, non monotone tenors, and short history fail."""
    good = {
        "2Y": make_quantity(3.0, "percent", "observed", "valet:2Y"),
        "5Y": make_quantity(3.1, "percent", "observed", "valet:5Y"),
        "10Y": make_quantity(3.4, "percent", "observed", "valet:10Y"),
        "30Y": make_quantity(4.0, "percent", "observed", "valet:30Y"),
    }
    short = {key: good[key] for key in ("2Y", "5Y")}
    with pytest.raises(ValueError, match="missing benchmark"):
        build_curve_section(short)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        build_par_curve([CurveKnot("2Y", 2.0, 1.0), CurveKnot("5Y", 5.0, 2.0)])
    with pytest.raises(ValueError, match="strictly increasing"):
        build_par_curve(
            [
                CurveKnot("2Y", 2.0, 1.0),
                CurveKnot("5Y", 5.0, 2.0),
                CurveKnot("10Y", 5.0, 3.0),
            ]
        )
    with pytest.raises(ValueError, match="non empty mapping"):
        build_curve_section({})
