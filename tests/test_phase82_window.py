"""Phase 8.2 backfill window tests: ten year lookbacks and computed fetch starts.

The backfill command asks Valet and FRED for history starting at the asof
minus a lookback constant. Phase 8.2 raised both constants to 3653 days,
about ten calendar years including leap days, and passes the Valet start
into fetch_valet_group as start_date. These tests pin the constants and the
exact start dates handed to the fetchers, so a future edit that shortens
the window fails here instead of silently truncating the sealed ten year
history. No network runs: both fetchers are monkeypatched.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from goc_rates.backfill import FRED_LOOKBACK_DAYS, VALET_LOOKBACK_DAYS, run_backfill
from goc_rates.clients.valet import ValetObservation
from goc_rates.config import load_benchmark_map
from goc_rates.limits import MAX_HISTORY_OBS
from goc_rates.models import make_quantity

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "config" / "benchmark_map.yaml"
ASOF = "2026-11-04"
EXPECTED_START = "2016-11-03"
WINDOW_DAYS = 3653  # unit: days, pinned ten calendar years including leap days
MIN_WINDOW_DAYS = 3469  # unit: days, 9.5 calendar years floor for the sealed span
VALET_SERIES = (
    "BD.CDN.2YR.DQ.YLD",
    "BD.CDN.5YR.DQ.YLD",
    "BD.CDN.10YR.DQ.YLD",
    "BD.CDN.LONG.DQ.YLD",
)


def _dates(count: int) -> list[str]:
    """Return count consecutive calendar dates ending at the pinned asof."""
    end = dt.date.fromisoformat(ASOF)
    return [(end - dt.timedelta(days=offset)).isoformat() for offset in reversed(range(count))]


def _valet_group(dates: list[str]) -> dict[str, list[Any]]:
    """Build a joint complete Valet group with one observed print per date."""
    grouped: dict[str, list[Any]] = {}
    for position, series_id in enumerate(VALET_SERIES):
        grouped[series_id] = [
            ValetObservation(
                observation_date=day,
                series_id=series_id,
                label="phase 8.2 window test",
                quantity=make_quantity(
                    3.0 + position * 0.3,
                    "percent",
                    "observed",
                    f"valet:{series_id}",
                ),
            )
            for day in dates
        ]
    return grouped


def test_lookback_constants_pin_the_ten_year_window() -> None:
    """Both lookbacks pin 3653 days and agree with each other."""
    assert FRED_LOOKBACK_DAYS == WINDOW_DAYS
    assert VALET_LOOKBACK_DAYS == WINDOW_DAYS
    assert FRED_LOOKBACK_DAYS == VALET_LOOKBACK_DAYS
    assert FRED_LOOKBACK_DAYS >= MIN_WINDOW_DAYS, "window must span at least 9.5 calendar years"


def test_lookback_arithmetic_lands_on_the_pinned_start() -> None:
    """The asof minus either lookback lands on the pinned re-seal start date."""
    asof_day = dt.date.fromisoformat(ASOF)
    assert (asof_day - dt.timedelta(days=FRED_LOOKBACK_DAYS)).isoformat() == EXPECTED_START
    assert (asof_day - dt.timedelta(days=VALET_LOOKBACK_DAYS)).isoformat() == EXPECTED_START
    start_day = dt.date.fromisoformat(EXPECTED_START)
    assert (asof_day - start_day).days == WINDOW_DAYS
    assert (asof_day - start_day).days >= MIN_WINDOW_DAYS


def test_fred_fetch_window_hands_the_pinned_start_to_the_client(
    monkeypatch: Any,
) -> None:
    """_fetch_fred_histories requests the pinned ten year window per tenor."""
    import goc_rates.backfill as backfill_mod

    captured: list[dict[str, Any]] = []

    def fake_fred(series_id: str, client: Any, **kwargs: Any) -> list[Any]:
        captured.append({"series_id": series_id, **kwargs})
        return []

    monkeypatch.setattr(backfill_mod, "fetch_fred_series", fake_fred)
    benchmark_map = load_benchmark_map(CONFIG)
    asof_day = dt.date.fromisoformat(ASOF)

    histories, warnings, exclusions = backfill_mod._fetch_fred_histories(
        None, benchmark_map, "test-key", asof_day
    )
    assert warnings == []
    assert exclusions == []
    assert set(histories) == set(benchmark_map.benchmarks)
    assert len(captured) == len(benchmark_map.benchmarks)
    for call in captured:
        assert call["observation_start"] == EXPECTED_START
        assert call["observation_end"] == ASOF
        assert call["limit"] == MAX_HISTORY_OBS
        assert call["sort_order"] == "asc"
        start_day = dt.date.fromisoformat(call["observation_start"])
        end_day = dt.date.fromisoformat(call["observation_end"])
        assert (end_day - start_day).days == WINDOW_DAYS


def test_valet_fetch_window_hands_the_pinned_start_to_run_backfill(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """run_backfill fetches Valet from the pinned ten year start with the obs cap."""
    import goc_rates.backfill as backfill_mod

    captured: list[dict[str, Any]] = []

    def fake_fetch(group: str, client: Any, **kwargs: Any) -> dict[str, list[Any]]:
        captured.append({"group": group, **kwargs})
        return _valet_group(_dates(300))

    monkeypatch.setattr(backfill_mod, "fetch_valet_group", fake_fetch)
    monkeypatch.setattr(backfill_mod, "read_api_key", lambda: None)

    def no_bulk(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("bulk down")

    monkeypatch.setattr(backfill_mod, "fetch_bulk_table", no_bulk)
    out = tmp_path / "backfill.json"
    assert run_backfill(ASOF, str(out), str(CONFIG)) == 0
    assert captured, "run_backfill must call the Valet fetcher exactly once"
    call = captured[0]
    assert call["start_date"] == EXPECTED_START
    assert call["recent_limit"] == MAX_HISTORY_OBS
    start_day = dt.date.fromisoformat(call["start_date"])
    assert (dt.date.fromisoformat(ASOF) - start_day).days == WINDOW_DAYS
    artifact = json.loads(out.read_text(encoding="utf-8"))
    assert artifact["metadata"]["daily_count"] == 300
    assert artifact["daily"][0]["date"] == _dates(300)[0]
