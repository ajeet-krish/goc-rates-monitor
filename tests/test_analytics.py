"""Phase 2 analytics tests: slopes, z, carry, spreads, joins."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from goc_rates.analytics import (
    CARRY_HORIZON_YEARS,
    SLOPE_PAIRS,
    butterfly_bp,
    canada_us_spread_bp,
    carry_roll_bp,
    inner_join_dates,
    slope_bp,
    z_score,
)


def _goldens() -> dict[str, object]:
    path = Path(__file__).parent / "fixtures" / "phase2_curve_golden.json"
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_slope_pairs_are_pinned() -> None:
    """Slope pairs stay pinned to the four Phase 2 tenors."""
    assert SLOPE_PAIRS == (("2Y", "5Y"), ("2Y", "10Y"), ("5Y", "30Y"), ("10Y", "30Y"))
    assert CARRY_HORIZON_YEARS == 0.25


def test_slope_and_butterfly_match_golden() -> None:
    """Slope and butterfly match hand computed values."""
    goldens = _goldens()
    entry = goldens["slope_butterfly"]
    assert isinstance(entry, dict)
    assert slope_bp(1.0, 2.0) == pytest.approx(float(str(entry["slope_bp"])))
    assert butterfly_bp(1.0, 2.0, 2.5) == pytest.approx(float(str(entry["butterfly_bp"])))


def test_z_score_known_value_and_gates() -> None:
    """Known z matches the golden; short history and zero stdev miss."""
    goldens = _goldens()
    entry = goldens["z_known"]
    assert isinstance(entry, dict)
    history = [50.0 + float(i) * 0.1 for i in range(252)]
    assert z_score(100.0, history) == pytest.approx(float(str(entry["z"])), abs=1e-9)
    assert z_score(100.0, history[:100]) is None
    assert z_score(100.0, [100.0] * 252) is None


def test_carry_flat_equals_yield_times_horizon() -> None:
    """Flat curve carry equals yield times horizon with zero roll."""
    goldens = _goldens()
    entry = goldens["carry_flat_3pct"]
    assert isinstance(entry, dict)
    assert carry_roll_bp(3.0, 3.0, 0.25) == pytest.approx(float(str(entry["carry_roll_bp"])))
    roll = goldens["carry_roll_example"]
    assert isinstance(roll, dict)
    assert carry_roll_bp(3.0, 2.9, 0.25) == pytest.approx(float(str(roll["carry_roll_bp"])))


def test_spread_same_date_and_holiday_drop() -> None:
    """Same date spreads recompute and one sided holidays drop."""
    goldens = _goldens()
    entry = goldens["spread_same_date"]
    assert isinstance(entry, dict)
    assert canada_us_spread_bp(3.5, 4.0) == pytest.approx(float(str(entry["spread_bp"])))
    join = goldens["spread_join"]
    assert isinstance(join, dict)
    ca_dates = join["ca_dates"]
    us_dates = join["us_dates"]
    assert isinstance(ca_dates, list) and isinstance(us_dates, list)
    ca_map = {str(date): 3.5 for date in ca_dates}
    us_map = {str(date): 4.0 for date in us_dates}
    assert inner_join_dates(ca_map, us_map) == list(join["joint_dates"])
