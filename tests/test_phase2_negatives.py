"""Phase 2 boundary plus negative tests (review follow up).

Covers backtest 253 versus 254, semiannual base and discount
monotonicity, V13 tamper and stored mismatch, V16 record modes,
V18 date grammar, tenor and count caps, source id grammar, yield
range edges, OverflowError containment, and CLI wiring.
"""

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path
from typing import Any

import pytest

from goc_rates.__main__ import _observed_benchmark_yields, run_snapshot
from goc_rates.analytics import slope_bp
from goc_rates.backtest import run_backtest
from goc_rates.curve import (
    CurveKnot,
    _knot_discount,
    bill_price_from_yield,
    build_curve_section,
    build_par_curve,
    discount_factor,
)
from goc_rates.models import make_quantity, validate_source_id
from goc_rates.risk import par_bond_price
from goc_rates.verify import run_checks, verify_snapshot


def _passing_snapshot() -> dict[str, Any]:
    """Build a snapshot that passes V01 to V18 before mutation."""
    from goc_rates.backtest import BACKTEST_RULE
    from goc_rates.risk import dv01_per_million, modified_duration
    from goc_rates.verify import tbill_price_from_yield

    price = tbill_price_from_yield(4.0, 90)
    curve = build_curve_section(
        {
            "2Y": make_quantity(3.32, "percent", "observed", "valet:BD.CDN.2YR.DQ.YLD"),
            "5Y": make_quantity(3.62, "percent", "observed", "valet:BD.CDN.5YR.DQ.YLD"),
            "10Y": make_quantity(3.90, "percent", "observed", "valet:BD.CDN.10YR.DQ.YLD"),
            "30Y": make_quantity(4.19, "percent", "observed", "valet:BD.CDN.LONG.DQ.YLD"),
        }
    )
    risk_price = par_bond_price(3.0, 5.0)
    risk_duration = modified_duration(3.0, 5.0)
    risk_dv01 = dv01_per_million(risk_price, risk_duration)
    base = dt.date(2025, 1, 6)
    dates = [(base + dt.timedelta(days=i)).isoformat() for i in range(260)]
    slopes = [100.0 + float(i % 5) for i in range(260)]
    backtest = run_backtest(dates, slopes)
    return {
        "metadata": {"snapshot_date": "2026-10-30", "schema_version": 1},
        "observations": {
            "tbill_check": {"yield_percent": 4.0, "price": price, "days_to_maturity": 90},
            "benchmarks": {
                "10Y": {
                    "valet_label": "10-year benchmark bond yield",
                    "valet": {
                        "value": 3.85,
                        "unit": "percent",
                        "quality": "observed",
                        "source_id": "valet:BD.CDN.10YR.DQ.YLD",
                    },
                }
            },
            "corra": {
                "value_date": "2026-10-29",
                "pub_date": "2026-10-30",
                "date_role": "value_date_lags_pub_date",
            },
            "fred_lag": {
                "observation_date": "2026-10-29",
                "expected_lag_note": "DGS prints land T+1",
            },
            "statcan": {"seasonally_adjusted_reused_as_is": True, "vectors": {}},
            "cross_source_diff_bp": {"value_bp": 0.5, "unit": "basis_points"},
            "staleness": {"max_age_business_days": 1, "unit": "business_days"},
            "curve": curve,
            "spreads": {
                "status": "ok",
                "reason": None,
                "records": [
                    {
                        "date": "2026-10-30",
                        "tenor": "2Y",
                        "ca_date": "2026-10-30",
                        "us_date": "2026-10-30",
                        "ca_yield_percent": 3.5,
                        "us_yield_percent": 3.0,
                        "spread_bp": 50.0,
                    },
                    {
                        "date": "2026-10-30",
                        "tenor": "5Y",
                        "ca_date": "2026-10-30",
                        "us_date": "2026-10-30",
                        "ca_yield_percent": 3.5,
                        "us_yield_percent": 3.0,
                        "spread_bp": 50.0,
                    },
                    {
                        "date": "2026-10-30",
                        "tenor": "10Y",
                        "ca_date": "2026-10-30",
                        "us_date": "2026-10-30",
                        "ca_yield_percent": 3.5,
                        "us_yield_percent": 3.0,
                        "spread_bp": 50.0,
                    },
                    {
                        "date": "2026-10-30",
                        "tenor": "30Y",
                        "ca_date": "2026-10-30",
                        "us_date": "2026-10-30",
                        "ca_yield_percent": 3.5,
                        "us_yield_percent": 3.0,
                        "spread_bp": 50.0,
                    },
                ],
            },
            "carry": {
                "yield_at_maturity_percent": 3.0,
                "yield_at_rolled_tenor_percent": 3.0,
                "horizon_years": 0.25,
                "carry_roll_bp": 75.0,
            },
            "risk": {
                "yield_percent": 3.0,
                "tenor_years": 5.0,
                "price": risk_price,
                "modified_duration_years": risk_duration,
                "dv01_per_million": risk_dv01,
            },
            "backtest": {
                "rule": BACKTEST_RULE,
                "dates": dates,
                "slopes_bp": slopes,
                "total_pnl_bp": float(str(backtest["total_pnl_bp"])),
            },
        },
        "provenance": {
            "valet": {
                "source_url": "https://www.bankofcanada.ca/valet/",
                "retrieved_utc": "2026-10-31T00:00:00Z",
                "vintage": "2026-10-30",
            }
        },
        "manifest": {"snapshot.json": {"sha256": "test-fixture-digest"}},
    }


def _check(snapshot: dict[str, Any], check_id: str) -> Any:
    report = verify_snapshot(snapshot)
    for item in report["checks"]:
        assert isinstance(item, dict)
        if item["id"] == check_id:
            return item
    raise AssertionError(f"missing check {check_id}")


def _dates(count: int) -> list[str]:
    base = dt.date(2025, 1, 6)
    return [(base + dt.timedelta(days=i)).isoformat() for i in range(count)]


def test_backtest_exactly_253_raises() -> None:
    """Exactly 253 joined observations raise instead of signaling."""
    dates = _dates(253)
    slopes = [100.0] * 253
    with pytest.raises(ValueError, match="at least 254"):
        run_backtest(dates, slopes)


def test_backtest_254_yields_one_signal() -> None:
    """254 joined observations yield exactly one signal row."""
    dates = _dates(254)
    slopes = [100.0] * 254
    result = run_backtest(dates, slopes)
    assert result["obs_count"] == 254
    assert isinstance(result["signal_dates"], list)
    assert len(result["signal_dates"]) == 1
    assert isinstance(result["positions"], list)
    assert len(result["positions"]) == 1
    assert isinstance(result["daily_pnl_bp"], list)
    assert len(result["daily_pnl_bp"]) == 1


def test_non_positive_semiannual_base_raises() -> None:
    """A yield of negative 250 percent raises on the semiannual base."""
    with pytest.raises(ValueError):
        _knot_discount(-250.0, 2.0)
    with pytest.raises(ValueError):
        build_par_curve(
            [
                CurveKnot("2Y", 2.0, -250.0),
                CurveKnot("5Y", 5.0, 3.0),
                CurveKnot("10Y", 10.0, 3.5),
            ]
        )


def test_non_decreasing_discounts_raise() -> None:
    """Knots whose discounts do not strictly decrease raise."""
    with pytest.raises(ValueError, match="strictly decreasing"):
        build_par_curve(
            [
                CurveKnot("2Y", 2.0, 30.0),
                CurveKnot("5Y", 5.0, 0.0),
                CurveKnot("10Y", 10.0, 0.0),
            ]
        )


def test_v13_method_flag_tamper_fails() -> None:
    """A tampered curve method flag fails V13."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    curve = observations["curve"]
    assert isinstance(curve, dict)
    curve["method"] = "tampered_method_v9"
    item = _check(snapshot, "V13")
    assert item["passed"] is False


def test_v13_tenor_set_tamper_fails() -> None:
    """A tampered tenor label set fails V13."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    curve = observations["curve"]
    assert isinstance(curve, dict)
    knots = curve["knots"]
    assert isinstance(knots, list)
    last = knots[-1]
    assert isinstance(last, dict)
    last["tenor"] = "20Y"
    item = _check(snapshot, "V13")
    assert item["passed"] is False


def test_v13_stored_discount_mismatch_fails() -> None:
    """A stored discount moved beyond 1.0 bp fails V13."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    curve = observations["curve"]
    assert isinstance(curve, dict)
    knots = curve["knots"]
    assert isinstance(knots, list)
    first = knots[0]
    assert isinstance(first, dict)
    stored = float(str(first["discount"]))
    first["discount"] = stored * 1.01
    item = _check(snapshot, "V13")
    assert item["passed"] is False
    assert "bp" in str(item["detail"])


def test_v13_stored_zero_mismatch_fails() -> None:
    """A stored zero moved beyond 1.0 bp fails V13."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    curve = observations["curve"]
    assert isinstance(curve, dict)
    zeros = curve["zero_yields"]
    assert isinstance(zeros, dict)
    entry = zeros["10Y"]
    assert isinstance(entry, dict)
    entry["value"] = float(str(entry["value"])) + 0.05
    item = _check(snapshot, "V13")
    assert item["passed"] is False


def test_v16_missing_leg_dates_fail() -> None:
    """A spread record without leg dates fails V16."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    spreads = observations["spreads"]
    assert isinstance(spreads, dict)
    records = spreads["records"]
    assert isinstance(records, list)
    record = records[0]
    assert isinstance(record, dict)
    del record["ca_date"]
    item = _check(snapshot, "V16")
    assert item["passed"] is False


def test_v16_non_dict_record_fails() -> None:
    """A non mapping spread record fails V16 instead of being skipped."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    observations["spreads"] = {"status": "ok", "reason": None, "records": [42]}
    item = _check(snapshot, "V16")
    assert item["passed"] is False


def test_v16_empty_set_fails() -> None:
    """An empty spread set fails V16 instead of passing vacuously."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    observations["spreads"] = {"status": "ok", "reason": None, "records": []}
    item = _check(snapshot, "V16")
    assert item["passed"] is False


def test_v18_non_iso_dates_fail() -> None:
    """Backtest dates outside strict ISO grammar fail V18."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    backtest = observations["backtest"]
    assert isinstance(backtest, dict)
    dates = backtest["dates"]
    assert isinstance(dates, list)
    dates[10] = "2026/01/15"
    item = _check(snapshot, "V18")
    assert item["passed"] is False


def test_v18_duplicate_dates_fail() -> None:
    """Duplicate backtest dates fail V18 on strict increase."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    backtest = observations["backtest"]
    assert isinstance(backtest, dict)
    dates = backtest["dates"]
    assert isinstance(dates, list)
    dates[11] = dates[10]
    item = _check(snapshot, "V18")
    assert item["passed"] is False


def test_v18_out_of_order_dates_fail() -> None:
    """Out of order backtest dates fail V18."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    backtest = observations["backtest"]
    assert isinstance(backtest, dict)
    dates = backtest["dates"]
    assert isinstance(dates, list)
    dates[10], dates[11] = dates[11], dates[10]
    item = _check(snapshot, "V18")
    assert item["passed"] is False


def test_max_tenor_1e9_raises_fast() -> None:
    """A tenor of 1e9 raises through the cap without a slow loop."""
    curve = build_par_curve(
        [
            CurveKnot("2Y", 2.0, 3.0),
            CurveKnot("5Y", 5.0, 3.0),
            CurveKnot("10Y", 10.0, 3.0),
        ]
    )
    start = time.perf_counter()
    with pytest.raises(ValueError, match="cap"):
        discount_factor(curve, 1e9)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0


def test_tenor_60_5_raises() -> None:
    """A tenor just above the 60 year cap raises."""
    curve = build_par_curve(
        [
            CurveKnot("2Y", 2.0, 3.0),
            CurveKnot("5Y", 5.0, 3.0),
            CurveKnot("10Y", 10.0, 3.0),
        ]
    )
    with pytest.raises(ValueError, match="cap"):
        discount_factor(curve, 60.5)
    with pytest.raises(ValueError, match="cap"):
        par_bond_price(3.0, 60.5)


def test_tenor_60_succeeds_with_120_periods() -> None:
    """The 60 year cap prices with exactly 120 semiannual periods."""
    price = par_bond_price(3.0, 60.0)
    assert price == pytest.approx(100.0, abs=1e-6)
    curve = build_par_curve(
        [
            CurveKnot("2Y", 2.0, 3.0),
            CurveKnot("5Y", 5.0, 3.0),
            CurveKnot("10Y", 10.0, 3.0),
        ]
    )
    discount = discount_factor(curve, 60.0)
    assert 0.0 < discount <= 1.0


def test_11_knots_reject() -> None:
    """Eleven knots exceed the knot cap and raise."""
    knots = [CurveKnot(f"T{i}", 1.0 + float(i) * 0.5, 3.0) for i in range(11)]
    with pytest.raises(ValueError, match="knot cap"):
        build_par_curve(knots)


def test_2001_obs_reject() -> None:
    """2001 backtest observations exceed the observation cap."""
    dates = _dates(2001)
    slopes = [100.0] * 2001
    with pytest.raises(ValueError, match="cap"):
        run_backtest(dates, slopes)


def test_bill_days_400_reject() -> None:
    """A 400 day bill tenor exceeds the day cap and raises."""
    with pytest.raises(ValueError, match="cap"):
        bill_price_from_yield(4.0, 400)


def test_source_id_api_key_fragment_reject() -> None:
    """A source id carrying an api_key fragment is rejected by grammar."""
    with pytest.raises(ValueError):
        validate_source_id("derived:foo?api_key=secret")
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    curve = observations["curve"]
    assert isinstance(curve, dict)
    curve["curve_source_id"] = "derived:foo?api_key=secret"
    discounts = curve["discounts"]
    assert isinstance(discounts, dict)
    entry = discounts["2Y"]
    assert isinstance(entry, dict)
    entry["source_id"] = "derived:foo?api_key=secret"
    item = _check(snapshot, "V15")
    assert item["passed"] is False


def test_source_id_81_char_reject() -> None:
    """An 81 character source id exceeds the 80 character cap."""
    long_id = "derived:" + "a" * 73
    assert len(long_id) == 81
    with pytest.raises(ValueError, match="80"):
        validate_source_id(long_id)


def test_yield_edges_accept() -> None:
    """Yields at negative 20 and positive 30 percent are accepted."""
    assert slope_bp(-20.0, 30.0) == pytest.approx(5000.0)
    assert par_bond_price(-20.0, 2.0) > 0.0
    assert par_bond_price(30.0, 2.0) > 0.0


def test_yield_edges_reject() -> None:
    """Yields just outside the range plus NaN and inf all raise."""
    for bad in (-20.01, 30.01):
        with pytest.raises(ValueError):
            slope_bp(float(bad), 3.0)
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            slope_bp(bad, 3.0)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            build_curve_section(
                {
                    "2Y": make_quantity(3.0, "percent", "observed", "valet:A"),
                    "5Y": make_quantity(3.0, "percent", "observed", "valet:B"),
                    "10Y": make_quantity(3.0, "percent", "observed", "valet:C"),
                    "30Y": {
                        "value": bad,
                        "unit": "percent",
                        "quality": "observed",
                        "source_id": "valet:D",
                    },
                }
            )


def test_v13_overflow_becomes_fail_not_crash(monkeypatch: Any) -> None:
    """An OverflowError during V13 recompute fails the check cleanly."""
    import goc_rates.verify as verify_mod

    def boom(*args: Any, **kwargs: Any) -> float:
        raise OverflowError("boom")

    monkeypatch.setattr(verify_mod, "discount_factor", boom)
    snapshot = _passing_snapshot()
    results = run_checks(snapshot)
    v13 = next(item for item in results if item.check_id == "V13")
    assert v13.passed is False


def test_v18_overflow_becomes_fail_not_crash(monkeypatch: Any) -> None:
    """An OverflowError during V18 recompute fails the check cleanly."""
    import goc_rates.backtest as backtest_mod

    def boom(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise OverflowError("boom")

    monkeypatch.setattr(backtest_mod, "run_backtest", boom)
    snapshot = _passing_snapshot()
    results = run_checks(snapshot)
    v18 = next(item for item in results if item.check_id == "V18")
    assert v18.passed is False


def test_cli_wired_real_quantities() -> None:
    """Observed benchmark quantities wire into a real curve section."""
    from goc_rates.curve import CURVE_METHOD

    observed = {
        "2Y": make_quantity(3.0, "percent", "observed", "valet:BD.CDN.2YR.DQ.YLD"),
        "5Y": make_quantity(3.1, "percent", "observed", "valet:BD.CDN.5YR.DQ.YLD"),
        "10Y": make_quantity(3.4, "percent", "observed", "valet:BD.CDN.10YR.DQ.YLD"),
        "30Y": make_quantity(4.0, "percent", "observed", "valet:BD.CDN.LONG.DQ.YLD"),
    }
    picked = _observed_benchmark_yields({key: {"valet": value} for key, value in observed.items()})
    assert set(picked.keys()) == {"2Y", "5Y", "10Y", "30Y"}
    section = build_curve_section(picked)  # type: ignore[arg-type]
    assert section["method"] == CURVE_METHOD
    assert section["curve_source_id"] == "derived:curve"
    assert len(section["knots"]) == 4


def test_v16_three_tenor_subset_fails() -> None:
    """An ok envelope with only 2Y 5Y 10Y fails V16 on the tenor set."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    spreads = observations["spreads"]
    assert isinstance(spreads, dict)
    records = spreads["records"]
    assert isinstance(records, list)
    spreads["records"] = [records[0], records[1], records[2]]
    item = _check(snapshot, "V16")
    assert item["passed"] is False
    assert "complete tenor set" in str(item["detail"])


def test_v16_duplicate_tenor_fails() -> None:
    """An ok envelope with two 2Y records and no 30Y fails V16."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    spreads = observations["spreads"]
    assert isinstance(spreads, dict)
    records = spreads["records"]
    assert isinstance(records, list)
    first = records[0]
    assert isinstance(first, dict)
    spreads["records"] = [records[0], dict(first), records[1], records[2]]
    item = _check(snapshot, "V16")
    assert item["passed"] is False
    assert "complete tenor set" in str(item["detail"])


def test_cli_skeleton_still_returns_1(tmp_path: Path, capsys: Any) -> None:
    """The live CLI writes the triple, printing the marker only on verify pass."""
    config = Path(__file__).resolve().parent.parent / "config" / "benchmark_map.yaml"
    out_dir = tmp_path / "2026-10-30"
    code = run_snapshot("2026-10-30", str(out_dir), str(config))
    assert code in (0, 1)
    assert (out_dir / "snapshot.json").is_file()
    assert (out_dir / "manifest.json").is_file()
    captured = capsys.readouterr()
    if code == 0:
        assert "SNAPSHOT_DATE=2026-10-30" in captured.out
    else:
        assert "SNAPSHOT_DATE=2026-10-30" not in captured.out
    assert "mock" not in (out_dir / "snapshot.json").read_text(encoding="utf-8").lower()
