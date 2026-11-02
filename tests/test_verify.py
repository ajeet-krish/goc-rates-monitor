"""Verification tests: V01 to V23 checks with a 1.0 basis point tolerance."""

import datetime as dt
import json
from pathlib import Path
from typing import Any

from goc_rates.backtest import BACKTEST_RULE, run_backtest
from goc_rates.curve import build_curve_section
from goc_rates.models import make_quantity
from goc_rates.risk import dv01_per_million, modified_duration, par_bond_price
from goc_rates.verify import (
    TOLERANCE_BP,
    tbill_price_from_yield,
    verify_file,
    verify_snapshot,
)
from tests.cpi_fixtures import attach_demo_inflation


def _passing_snapshot() -> dict[str, Any]:
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
    observations = snapshot["observations"]
    provenance = snapshot["provenance"]
    assert isinstance(observations, dict) and isinstance(provenance, dict)
    attach_demo_inflation(observations, provenance)
    _attach_demo_breaks(observations, provenance)
    return snapshot


def _attach_demo_breaks(observations: dict[str, Any], provenance: dict[str, Any]) -> None:
    """Attach a passing breaks section plus provenance for V23."""
    from pathlib import Path as _Path

    from goc_rates.breaks import build_breaks_section, load_switch_feed

    feed_path = _Path(__file__).resolve().parent.parent / "config" / "benchmark_switches.yaml"
    feed = load_switch_feed(feed_path)
    histories = {
        "2Y": {"2026-10-29": 3.27, "2026-10-30": 3.32},
        "5Y": {"2026-10-29": 3.57, "2026-10-30": 3.62},
        "10Y": {"2026-10-29": 3.85, "2026-10-30": 3.9},
        "30Y": {"2026-10-29": 4.14, "2026-10-30": 4.19},
    }
    observations["breaks"] = build_breaks_section("2026-10-30", "2026-10-30", histories, feed)
    provenance["benchmark_switches"] = {
        "source_url": "https://www.bankofcanada.ca/stats/assets/pdf/bench_CDN.pdf",
        "retrieved_utc": "2026-10-31T00:00:00Z",
        "vintage": feed.feed_vintage.isoformat(),
        "sha256": feed.feed_sha256,
    }


def test_tolerance_is_one_basis_point() -> None:
    """Tolerance constant stays pinned at 1.0 bp."""
    assert TOLERANCE_BP == 1.0


def test_tbill_price_inversion_matches_formula() -> None:
    """T-bill price recovery matches the ACT/365 add-on formula."""
    assert tbill_price_from_yield(4.0, 365) == 100.0 / 1.04


def test_passing_snapshot_passes_all_checks() -> None:
    """A complete snapshot passes V01 to V23."""
    report = verify_snapshot(_passing_snapshot())
    assert report["passed"] is True
    assert len(report["checks"]) == 23
    assert report["failed_count"] == 0
    assert report["tolerance_unit"] == "basis_points"


def test_failing_snapshot_reports_failures() -> None:
    """A snapshot with drift fails the tolerance and label checks."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    cross = observations["cross_source_diff_bp"]
    assert isinstance(cross, dict)
    cross["value_bp"] = 5.0
    report = verify_snapshot(snapshot)
    assert report["passed"] is False
    failed_ids = [item["id"] for item in report["checks"] if not item["passed"]]
    assert "V11" in failed_ids


def test_v13_fails_on_reprice_drift() -> None:
    """A curve knot edited after pricing fails V13."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    curve = observations["curve"]
    assert isinstance(curve, dict)
    knots = curve["knots"]
    assert isinstance(knots, list)
    first = knots[0]
    assert isinstance(first, dict)
    first["yield_percent"] = float(first["yield_percent"]) + 0.05
    report = verify_snapshot(snapshot)
    failed_ids = [item["id"] for item in report["checks"] if not item["passed"]]
    assert "V13" in failed_ids


def test_v18_fails_on_short_backtest() -> None:
    """A backtest with fewer than 253 observations fails V18."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    backtest = observations["backtest"]
    assert isinstance(backtest, dict)
    dates = backtest["dates"]
    slopes = backtest["slopes_bp"]
    assert isinstance(dates, list) and isinstance(slopes, list)
    backtest["dates"] = dates[:100]
    backtest["slopes_bp"] = slopes[:100]
    report = verify_snapshot(snapshot)
    failed_ids = [item["id"] for item in report["checks"] if not item["passed"]]
    assert "V18" in failed_ids


def test_verify_file_writes_verify_json_with_exit_code(tmp_path: Path) -> None:
    """verify_file writes verify.json and returns 0 for a passing snapshot."""
    import hashlib

    from goc_rates.snapshot import canonical_dumps

    snapshot = _passing_snapshot()
    snapshot.pop("manifest", None)
    snapshot_text = canonical_dumps(snapshot)
    directory = tmp_path / "2026-10-30"
    directory.mkdir(parents=True, exist_ok=True)
    snapshot_path = directory / "snapshot.json"
    snapshot_path.write_text(snapshot_text, encoding="utf-8")
    raw_digest = hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest()
    manifest = {"files": {"snapshot.json": {"sha256": raw_digest}}}
    (directory / "manifest.json").write_text(canonical_dumps(manifest), encoding="utf-8")
    code = verify_file(snapshot_path)
    assert code == 0
    report = json.loads((directory / "verify.json").read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert "snapshot_sha256" in report
