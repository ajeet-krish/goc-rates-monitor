"""Phase 5 lows: caps, overflow, pre-read, gate precedence, V23 tampers."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from goc_rates.breaks import (
    SwitchEvent,
    SwitchFeed,
    SwitchIssue,
    build_breaks_section,
    classify_gate,
    effective_joint_date,
    load_switch_feed,
)
from goc_rates.limits import MAX_HISTORY_OBS, MAX_SWITCH_FEED_BYTES
from goc_rates.verify import TOLERANCE_BP, verify_snapshot

CONFIG = Path(__file__).resolve().parent.parent / "config" / "benchmark_switches.yaml"


def _demo_feed() -> SwitchFeed:
    return load_switch_feed(CONFIG)


def _issue(maturity: str | None = None, coupon: float | None = None) -> SwitchIssue:
    return SwitchIssue(maturity=maturity, coupon_percent=coupon)


def _feed_with(event: SwitchEvent) -> SwitchFeed:
    return SwitchFeed(
        source="bench_CDN.pdf",
        feed_vintage=dt.date(2026, 11, 1),
        events=(event,),
        feed_sha256="ab" * 32,
    )


def _passing_snapshot_with_breaks() -> dict[str, Any]:
    from goc_rates.backtest import BACKTEST_RULE, run_backtest
    from goc_rates.curve import build_curve_section
    from goc_rates.models import make_quantity
    from goc_rates.risk import dv01_per_million, modified_duration, par_bond_price
    from goc_rates.verify import tbill_price_from_yield
    from tests.cpi_fixtures import attach_demo_inflation

    price = tbill_price_from_yield(4.0, 90)
    curve = build_curve_section(
        {
            "2Y": make_quantity(3.32, "percent", "observed", "valet:BD.CDN.2YR.DQ.YLD"),
            "5Y": make_quantity(3.62, "percent", "observed", "valet:BD.CDN.5YR.DQ.YLD"),
            "10Y": make_quantity(3.9, "percent", "observed", "valet:BD.CDN.10YR.DQ.YLD"),
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
    feed = _demo_feed()
    histories = {
        "2Y": {"2026-10-29": 3.27, "2026-10-30": 3.32},
        "5Y": {"2026-10-29": 3.57, "2026-10-30": 3.62},
        "10Y": {"2026-10-29": 3.85, "2026-10-30": 3.9},
        "30Y": {"2026-10-29": 4.14, "2026-10-30": 4.19},
    }
    breaks = build_breaks_section("2026-10-30", "2026-10-30", histories, feed)
    snapshot: dict[str, Any] = {
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
            "spreads": [
                {
                    "date": "2026-10-30",
                    "ca_date": "2026-10-30",
                    "us_date": "2026-10-30",
                    "ca_yield_percent": 3.5,
                    "us_yield_percent": 3.0,
                    "spread_bp": 50.0,
                }
            ],
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
            "breaks": breaks,
        },
        "provenance": {
            "valet": {
                "source_url": "https://www.bankofcanada.ca/valet/",
                "retrieved_utc": "2026-10-31T00:00:00Z",
                "vintage": "2026-10-30",
            },
            "benchmark_switches": {
                "source_url": "https://www.bankofcanada.ca/stats/assets/pdf/bench_CDN.pdf",
                "retrieved_utc": "2026-10-31T00:00:00Z",
                "vintage": feed.feed_vintage.isoformat(),
                "sha256": feed.feed_sha256,
            },
        },
        "manifest": {"snapshot.json": {"sha256": "test-fixture-digest"}},
    }
    observations = snapshot["observations"]
    provenance = snapshot["provenance"]
    assert isinstance(observations, dict) and isinstance(provenance, dict)
    attach_demo_inflation(observations, provenance)
    return snapshot


def _v23(snapshot: dict[str, Any]) -> Any:
    report = verify_snapshot(snapshot)
    by_id = {item["id"]: item for item in report["checks"]}
    return by_id["V23"]


def test_classify_gate_history_count_over_cap_rejects() -> None:
    with pytest.raises(ValueError, match="bounded range"):
        classify_gate(3.0, 3.05, False, False, MAX_HISTORY_OBS + 1)


def test_classify_gate_history_count_at_cap_accepts() -> None:
    assert classify_gate(3.0, 3.05, False, False, MAX_HISTORY_OBS) == "comparable"


def test_classify_gate_history_count_bool_rejects() -> None:
    with pytest.raises(ValueError, match="without coercion"):
        classify_gate(3.0, 3.05, False, False, True)  # type: ignore[arg-type]


def test_build_breaks_history_over_cap_rejects() -> None:
    feed = _demo_feed()
    big = {f"2020-01-{(i % 28) + 1:02d}": 3.0 for i in range(10)}
    assert len(big) <= 10
    oversized = {
        f"{2000 + (i // 12):04d}-{(i % 12) + 1:02d}-15": 3.0
        for i in range(MAX_HISTORY_OBS + 1)
    }
    histories = {
        "2Y": oversized,
        "5Y": {"2026-10-29": 3.57, "2026-10-30": 3.62},
        "10Y": {"2026-10-29": 3.85, "2026-10-30": 3.9},
        "30Y": {"2026-10-29": 4.14, "2026-10-30": 4.19},
    }
    with pytest.raises(ValueError, match="observation cap"):
        build_breaks_section("2026-10-30", "2026-10-30", histories, feed)


def test_effective_joint_max_date_raises_value_error() -> None:
    with pytest.raises(ValueError, match="outside range|overflows|no joint"):
        effective_joint_date(dt.date(9999, 12, 31))


def test_effective_joint_non_date_rejects() -> None:
    with pytest.raises(ValueError, match="must be a date"):
        effective_joint_date("2026-10-30")  # type: ignore[arg-type]


def test_load_feed_oversize_rejects_with_byte_cap(tmp_path: Path) -> None:
    target = tmp_path / "benchmark_switches.yaml"
    target.write_bytes(b"x" * (MAX_SWITCH_FEED_BYTES + 1))
    with pytest.raises(ValueError, match="byte cap"):
        load_switch_feed(target)


def test_load_feed_oversize_precheck_reports_declared_size(tmp_path: Path) -> None:
    target = tmp_path / "benchmark_switches.yaml"
    target.write_bytes(b"\xff\xfe" * ((MAX_SWITCH_FEED_BYTES // 2) + 10))
    with pytest.raises(ValueError, match="byte cap"):
        load_switch_feed(target)


def test_both_true_gate_is_switch_break_with_null() -> None:
    assert classify_gate(3.0, 3.05, True, True, 5) == "switch_break"
    event = SwitchEvent(
        tenor="2Y",
        effective_date=dt.date(2026, 10, 30),
        effective_joint_date=effective_joint_date(dt.date(2026, 10, 30)),
        incoming=_issue("2028-11-01", 3.0),
        outgoing=_issue(),
    )
    feed = _feed_with(event)
    histories = {
        "2Y": {"2026-10-28": 3.3, "2026-10-30": 3.36},
        "5Y": {"2026-10-28": 3.55, "2026-10-30": 3.58},
        "10Y": {"2026-10-28": 3.85, "2026-10-30": 3.9},
        "30Y": {"2026-10-28": 4.1, "2026-10-30": 4.13},
    }
    section = build_breaks_section("2026-10-30", "2026-10-30", histories, feed)
    row = {r["tenor"]: r for r in section["records"]}["2Y"]
    assert row["switch_in_window"] is True
    assert row["calendar_gap"] is True
    assert row["gate"] == "switch_break"
    assert row["dod_bp"] is None
    assert row["dod_quantity"]["quality"] == "missing"


def test_v23_calendar_gap_null_fails() -> None:
    snapshot = _passing_snapshot_with_breaks()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    breaks = observations["breaks"]
    assert isinstance(breaks, dict)
    records = breaks["records"]
    assert isinstance(records, list)
    target = None
    for row in records:
        assert isinstance(row, dict)
        if row["gate"] == "comparable":
            target = row
            break
    assert target is not None
    target["gate"] = "calendar_gap"
    target["calendar_gap"] = True
    target["dod_bp"] = None
    quantity = target["dod_quantity"]
    assert isinstance(quantity, dict)
    quantity["value"] = None
    quantity["quality"] = "missing"
    assert _v23(snapshot)["passed"] is False


def test_v23_9y_record_tenor_fails() -> None:
    snapshot = _passing_snapshot_with_breaks()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    breaks = observations["breaks"]
    assert isinstance(breaks, dict)
    records = breaks["records"]
    assert isinstance(records, list)
    first = records[0]
    assert isinstance(first, dict)
    first["tenor"] = "9Y"
    assert _v23(snapshot)["passed"] is False


def test_v23_provenance_vintage_drift_fails() -> None:
    snapshot = _passing_snapshot_with_breaks()
    provenance = snapshot["provenance"]
    assert isinstance(provenance, dict)
    switch_prov = provenance["benchmark_switches"]
    assert isinstance(switch_prov, dict)
    switch_prov["vintage"] = "2026-10-01"
    assert _v23(snapshot)["passed"] is False


def test_v23_provenance_sha_mismatch_fails() -> None:
    snapshot = _passing_snapshot_with_breaks()
    provenance = snapshot["provenance"]
    assert isinstance(provenance, dict)
    switch_prov = provenance["benchmark_switches"]
    assert isinstance(switch_prov, dict)
    switch_prov["sha256"] = "0" * 64
    result = _v23(snapshot)
    assert result["passed"] is False
    assert "sha256" in result["detail"]


def test_verify_reports_23_checks_at_1bp() -> None:
    snapshot = _passing_snapshot_with_breaks()
    report = verify_snapshot(snapshot)
    assert len(report["checks"]) == 23
    assert report["checks"][-1]["id"] == "V23"
    assert TOLERANCE_BP == 1.0
    assert report["passed"] is True
