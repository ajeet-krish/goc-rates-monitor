"""Live snapshot tests: full pass with mocked histories plus degraded FRED path."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from goc_rates.clients.fred import FredObservation
from goc_rates.clients.valet import ValetObservation
from goc_rates.config import load_benchmark_map
from goc_rates.live_snapshot import build_live_observations, resolve_target_date
from goc_rates.models import make_quantity
from goc_rates.snapshot import build_snapshot, write_snapshot
from goc_rates.verify import verify_file

CONFIG = Path(__file__).resolve().parent.parent / "config" / "benchmark_map.yaml"


def _histories(days: int = 260) -> tuple[dict[str, list[Any]], dict[str, list[Any]], str]:
    base = dt.date(2025, 1, 6)
    dates = [(base + dt.timedelta(days=i)).isoformat() for i in range(days)]
    valet_map = {
        "BD.CDN.2YR.DQ.YLD": 3.0,
        "BD.CDN.5YR.DQ.YLD": 3.5,
        "BD.CDN.10YR.DQ.YLD": 3.9,
        "BD.CDN.LONG.DQ.YLD": 4.2,
    }
    fred_map = {"DGS2": 2.9, "DGS5": 3.4, "DGS10": 3.8, "DGS30": 4.1}
    valet_by_series: dict[str, list[Any]] = {}
    for series_id, value in valet_map.items():
        valet_by_series[series_id] = [
            ValetObservation(
                observation_date=day,
                series_id=series_id,
                label="live test",
                quantity=make_quantity(value, "percent", "observed", f"valet:{series_id}"),
            )
            for day in dates
        ]
    fred_by_series: dict[str, list[Any]] = {}
    for series_id, value in fred_map.items():
        fred_by_series[series_id] = [
            FredObservation(
                observation_date=day,
                series_id=series_id,
                quantity=make_quantity(value, "percent", "observed", f"fred:{series_id}"),
            )
            for day in dates
        ]
    return valet_by_series, fred_by_series, dates[-1]


def _write_and_verify(
    tmp_path: Path,
    snapshot_date: str,
    observations: dict[str, Any],
    provenance: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    snapshot = build_snapshot(snapshot_date, observations, provenance, warnings)
    directory = tmp_path / snapshot_date
    write_snapshot(directory, snapshot)
    assert (directory / "snapshot.json").is_file()
    assert (directory / "manifest.json").is_file()
    assert directory.name == snapshot["metadata"]["snapshot_date"]
    code = verify_file(directory / "snapshot.json", benchmark_map_path=CONFIG)
    assert code == 0
    report = json.loads((directory / "verify.json").read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["passed_count"] == 18
    assert report["failed_count"] == 0
    return report


def test_live_full_pass_v01_to_v18(tmp_path: Path) -> None:
    """Mocked Valet plus FRED histories yield a snapshot that passes V01-V18."""
    benchmark_map = load_benchmark_map(CONFIG)
    valet_by_series, fred_by_series, last = _histories()
    snapshot_date = dt.date.fromisoformat(last)
    observations, provenance, warnings = build_live_observations(
        snapshot_date, benchmark_map, valet_by_series, fred_by_series, True, None
    )
    report = _write_and_verify(tmp_path, last, observations, provenance, warnings)
    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["V16"]["passed"] is True
    assert by_id["V18"]["passed"] is True
    assert "mock" not in json.dumps(observations).lower()


def test_live_degraded_fred_passes_v01_to_v18(tmp_path: Path) -> None:
    """A missing FRED key marks spreads and backtest missing but still passes."""
    benchmark_map = load_benchmark_map(CONFIG)
    valet_by_series, _, last = _histories()
    snapshot_date = dt.date.fromisoformat(last)
    observations, provenance, warnings = build_live_observations(
        snapshot_date, benchmark_map, valet_by_series, {}, False, None
    )
    assert any("FRED degraded" in item for item in warnings)
    report = _write_and_verify(tmp_path, last, observations, provenance, warnings)
    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["V16"]["passed"] is True
    assert "degraded" in by_id["V16"]["detail"].lower()
    assert by_id["V18"]["passed"] is True
    assert "degraded" in by_id["V18"]["detail"].lower()


def test_resolve_target_date_strict_and_previous_joint() -> None:
    """Explicit dates are strict ISO and missing dates map to the prior joint day."""
    assert resolve_target_date("2026-10-30") == dt.date(2026, 10, 30)
    saturday = dt.datetime(2026, 11, 1, 12, 0)
    resolved = resolve_target_date(None, now=saturday)
    assert resolved < dt.date(2026, 11, 1)
    from goc_rates.calendar import is_business_day

    assert is_business_day(resolved, "joint")
