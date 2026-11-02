"""Phase 5 breaks tests: gate truth table, feed negatives, and V23 tampers."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from goc_rates.breaks import (
    BREAKS_METHOD,
    SwitchEvent,
    SwitchFeed,
    SwitchIssue,
    build_breaks_section,
    classify_gate,
    effective_joint_date,
    load_switch_feed,
    normalize_tenor,
    switch_in_window,
)
from goc_rates.calendar import is_business_day
from goc_rates.verify import verify_snapshot

CONFIG = Path(__file__).resolve().parent.parent / "config" / "benchmark_switches.yaml"


def _demo_feed() -> SwitchFeed:
    """Load the pinned feed for gate and section tests."""
    return load_switch_feed(CONFIG)


def _issue(maturity: str | None = None, coupon: float | None = None) -> SwitchIssue:
    """Build a switch issue leg with optional maturity and coupon."""
    return SwitchIssue(maturity=maturity, coupon_percent=coupon)


def _feed_with(event: SwitchEvent) -> SwitchFeed:
    """Wrap one event in a feed with a stable vintage and digest."""
    return SwitchFeed(
        source="bench_CDN.pdf",
        feed_vintage=dt.date(2026, 11, 1),
        events=(event,),
        feed_sha256="ab" * 32,
    )


def test_normalize_long_maps_to_30y() -> None:
    """The LONG bench label maps to the 30Y curve tenor."""
    assert normalize_tenor("LONG") == "30Y"
    assert normalize_tenor("5Y") == "5Y"


def test_effective_joint_holiday_shifted() -> None:
    """A Saturday effective date shifts forward to the next joint day."""
    saturday = dt.date(2026, 10, 24)
    assert saturday.weekday() == 5
    joint = effective_joint_date(saturday)
    assert joint > saturday
    assert is_business_day(joint, "joint") is True
    assert joint == dt.date(2026, 10, 26)


def test_classify_gate_truth_table() -> None:
    """Each gate classifies from its closed flag and history inputs."""
    assert classify_gate(3.0, 3.05, False, False, 5) == "comparable"
    assert classify_gate(3.0, 3.05, True, False, 5) == "switch_break"
    assert classify_gate(3.0, 3.05, False, True, 5) == "calendar_gap"
    assert classify_gate(None, 3.05, False, False, 5) == "missing_prev"
    assert classify_gate(3.0, None, False, False, 5) == "missing_prev"
    assert classify_gate(3.0, 3.05, False, False, 1) == "insufficient_history"
    assert classify_gate(None, None, True, True, 0) == "insufficient_history"


def test_classify_gate_switch_takes_precedence_over_gap() -> None:
    """A switch day with a calendar gap is switch_break with null suppression."""
    assert classify_gate(3.0, 3.05, True, True, 5) == "switch_break"
    assert classify_gate(3.0, 3.05, True, True, 2) == "switch_break"
    assert classify_gate(None, 3.05, True, True, 5) == "missing_prev"
    assert classify_gate(3.0, 3.05, True, True, 1) == "insufficient_history"


def test_switch_with_gap_suppresses_null_delta() -> None:
    """A switch plus a skipped joint day stays switch_break with a null delta."""
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
    by_tenor = {row["tenor"]: row for row in section["records"]}
    row = by_tenor["2Y"]
    assert row["switch_in_window"] is True
    assert row["calendar_gap"] is True
    assert row["gate"] == "switch_break"
    assert row["dod_bp"] is None
    assert row["dod_quantity"]["quality"] == "missing"


def test_phase5_verify_breaks_gap_mislabeled_as_switch_fails() -> None:
    """A both true day labeled calendar_gap with a numeric delta fails V23."""
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
    breaks = build_breaks_section("2026-10-30", "2026-10-30", histories, feed)
    snapshot = _passing_snapshot_with_breaks()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    provenance = snapshot["provenance"]
    assert isinstance(provenance, dict)
    observations["breaks"] = breaks
    switch_prov = provenance["benchmark_switches"]
    assert isinstance(switch_prov, dict)
    switch_prov["vintage"] = feed.feed_vintage.isoformat()
    switch_prov["sha256"] = feed.feed_sha256
    report = verify_snapshot(snapshot)
    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["V23"]["passed"] is True
    records = breaks["records"]
    assert isinstance(records, list)
    first = records[0]
    assert isinstance(first, dict)
    assert first["gate"] == "switch_break"
    first["gate"] = "calendar_gap"
    first["dod_bp"] = 6.0
    quantity = first["dod_quantity"]
    assert isinstance(quantity, dict)
    quantity["value"] = 6.0
    quantity["quality"] = "observed"
    report = verify_snapshot(snapshot)
    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["V23"]["passed"] is False


def test_switch_in_window_bounds() -> None:
    """The window is (prev, current] and LONG counts for 30Y."""
    event = SwitchEvent(
        tenor="LONG",
        effective_date=dt.date(2026, 3, 6),
        effective_joint_date=effective_joint_date(dt.date(2026, 3, 6)),
        incoming=_issue("2057-12-01", 3.5),
        outgoing=_issue(),
    )
    feed = _feed_with(event)
    joint = event.effective_joint_date
    prev = joint - dt.timedelta(days=1)
    assert switch_in_window("30Y", prev, joint, feed) is True
    assert switch_in_window("30Y", prev - dt.timedelta(days=5), prev, feed) is False
    assert switch_in_window("30Y", joint, joint + dt.timedelta(days=1), feed) is False
    assert switch_in_window("5Y", prev, joint + dt.timedelta(days=30), feed) is False


def test_switch_suppresses_null_delta() -> None:
    """A switch in the window suppresses the delta to null."""
    feed = _demo_feed()
    histories = {
        "2Y": {"2026-10-22": 3.0, "2026-10-23": 3.2},
        "5Y": {"2026-10-22": 3.5, "2026-10-23": 3.55},
        "10Y": {"2026-10-22": 3.85, "2026-10-23": 3.9},
        "30Y": {"2026-10-22": 4.1, "2026-10-23": 4.15},
    }
    section = build_breaks_section("2026-10-23", "2026-10-23", histories, feed)
    assert section["method"] == BREAKS_METHOD
    by_tenor = {row["tenor"]: row for row in section["records"]}
    assert by_tenor["2Y"]["gate"] == "switch_break"
    assert by_tenor["2Y"]["dod_bp"] is None
    assert by_tenor["2Y"]["switch_in_window"] is True


def test_calendar_gap_keeps_delta_with_flag() -> None:
    """A skipped joint day keeps the delta but flags the gap."""
    feed = _demo_feed()
    histories = {
        "2Y": {"2026-10-28": 3.3, "2026-10-30": 3.36},
        "5Y": {"2026-10-28": 3.55, "2026-10-30": 3.58},
        "10Y": {"2026-10-28": 3.85, "2026-10-30": 3.9},
        "30Y": {"2026-10-28": 4.1, "2026-10-30": 4.13},
    }
    section = build_breaks_section("2026-10-30", "2026-10-30", histories, feed)
    by_tenor = {row["tenor"]: row for row in section["records"]}
    assert by_tenor["2Y"]["gate"] == "calendar_gap"
    assert by_tenor["2Y"]["calendar_gap"] is True
    assert by_tenor["2Y"]["dod_bp"] == pytest.approx(6.0)


def test_load_feed_rejects_bad_schema_version(tmp_path: Path) -> None:
    """A wrong schema version fails closed."""
    text = CONFIG.read_text(encoding="utf-8").replace("schema_version: 1", "schema_version: 9")
    target = tmp_path / "benchmark_switches.yaml"
    target.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        load_switch_feed(target)


def test_load_feed_rejects_duplicate_event(tmp_path: Path) -> None:
    """A duplicated tenor plus effective date fails closed."""
    import yaml as _yaml

    raw: Any = _yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    events = raw["events"]
    assert isinstance(events, list)
    events.append(dict(events[0]))
    target = tmp_path / "benchmark_switches.yaml"
    target.write_text(_yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_switch_feed(target)


def test_load_feed_rejects_bad_tenor(tmp_path: Path) -> None:
    """A tenor outside the closed set fails closed."""
    import yaml as _yaml

    raw: Any = _yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    events = raw["events"]
    assert isinstance(events, list)
    first = events[0]
    assert isinstance(first, dict)
    first["tenor"] = "9Y"
    target = tmp_path / "benchmark_switches.yaml"
    target.write_text(_yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="tenor"):
        load_switch_feed(target)


def test_load_feed_rejects_bad_iso(tmp_path: Path) -> None:
    """A non strict effective date fails closed."""
    import yaml as _yaml

    raw: Any = _yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    events = raw["events"]
    assert isinstance(events, list)
    first = events[0]
    assert isinstance(first, dict)
    first["effective_date"] = "2026/08/06"
    target = tmp_path / "benchmark_switches.yaml"
    target.write_text(_yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="strict ISO"):
        load_switch_feed(target)


def _passing_snapshot_with_breaks() -> dict[str, Any]:
    """Build a minimal snapshot that passes V23 alongside V13."""
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


def test_phase5_verify_breaks_passes() -> None:
    """A complete breaks section passes V23."""
    report = verify_snapshot(_passing_snapshot_with_breaks())
    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["V23"]["passed"] is True
    assert report["passed"] is True


def test_phase5_verify_breaks_flipped_gate_fails() -> None:
    """A flipped gate fails V23 recompute."""
    snapshot = _passing_snapshot_with_breaks()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    breaks = observations["breaks"]
    assert isinstance(breaks, dict)
    records = breaks["records"]
    assert isinstance(records, list)
    first = records[0]
    assert isinstance(first, dict)
    first["gate"] = "switch_break" if first["gate"] != "switch_break" else "comparable"
    report = verify_snapshot(snapshot)
    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["V23"]["passed"] is False


def test_phase5_verify_breaks_moved_delta_fails() -> None:
    """A moved delta beyond tolerance fails V23."""
    snapshot = _passing_snapshot_with_breaks()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    breaks = observations["breaks"]
    assert isinstance(breaks, dict)
    records = breaks["records"]
    assert isinstance(records, list)
    first = records[0]
    assert isinstance(first, dict)
    assert isinstance(first["dod_bp"], (int, float))
    first["dod_bp"] = float(first["dod_bp"]) + 5.0
    quantity = first["dod_quantity"]
    assert isinstance(quantity, dict)
    quantity["value"] = first["dod_bp"]
    report = verify_snapshot(snapshot)
    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["V23"]["passed"] is False


def test_phase5_verify_breaks_wrong_joint_fails() -> None:
    """A wrong joint date fails V23 effective recompute."""
    snapshot = _passing_snapshot_with_breaks()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    breaks = observations["breaks"]
    assert isinstance(breaks, dict)
    events = breaks["events"]
    assert isinstance(events, list)
    first = events[0]
    assert isinstance(first, dict)
    first["effective_joint_date"] = "2026-10-30"
    report = verify_snapshot(snapshot)
    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["V23"]["passed"] is False


def test_phase5_verify_breaks_bad_digest_fails() -> None:
    """A bad feed digest fails V23 grammar and provenance pins."""
    snapshot = _passing_snapshot_with_breaks()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    breaks = observations["breaks"]
    assert isinstance(breaks, dict)
    breaks["feed_sha256"] = "not-a-hex-digest"
    report = verify_snapshot(snapshot)
    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["V23"]["passed"] is False


def test_phase5_verify_breaks_missing_beside_curve_fails() -> None:
    """A missing breaks section beside a present curve fails V23."""
    snapshot = _passing_snapshot_with_breaks()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    del observations["breaks"]
    report = verify_snapshot(snapshot)
    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["V23"]["passed"] is False
