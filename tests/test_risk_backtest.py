"""Phase 2 risk and backtest tests with golden recomputation."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from goc_rates.backtest import BACKTEST_RULE, Z_ENTRY, run_backtest
from goc_rates.risk import dv01_per_million, modified_duration, par_bond_price


def _goldens() -> dict[str, object]:
    path = Path(__file__).parent / "fixtures" / "phase2_curve_golden.json"
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_backtest_rule_and_entry_pinned() -> None:
    """Backtest rule id and entry threshold stay pinned."""
    assert BACKTEST_RULE == "2s10s_z252_meanrev_v1"
    assert Z_ENTRY == 1.0


def test_par_price_duration_dv01_match_golden() -> None:
    """Par bond price, duration, and DV01 match the hand computed golden."""
    goldens = _goldens()
    entry = goldens["risk_5y_3pct_par"]
    assert isinstance(entry, dict)
    price = par_bond_price(3.0, 5.0)
    assert price == pytest.approx(float(str(entry["price_per_100"])), abs=1e-9)
    duration = modified_duration(3.0, 5.0)
    assert duration == pytest.approx(float(str(entry["modified_duration_years"])), abs=1e-9)
    dv01 = dv01_per_million(price, duration)
    assert dv01 == pytest.approx(float(str(entry["dv01_per_million"])), abs=1e-6)


def test_z_300d_and_mutation_changes_pnl() -> None:
    """300 day slopes give a known z and same day mutation moves PnL."""
    history = [50.0 + float(i) * 0.1 for i in range(252)]
    goldens = _goldens()
    entry = goldens["z_known"]
    assert isinstance(entry, dict)
    from goc_rates.analytics import z_score

    assert z_score(100.0, history) == pytest.approx(float(str(entry["z"])), abs=1e-9)
    base = dt.date(2025, 1, 6)
    dates = [(base + dt.timedelta(days=i)).isoformat() for i in range(260)]
    slopes = [100.0 + float(i % 5) for i in range(260)]
    first = run_backtest(dates, slopes)
    assert first["rule"] == BACKTEST_RULE
    assert first["obs_count"] == 260
    mutated = list(slopes)
    mutated[253] += 10.0
    second = run_backtest(dates, mutated)
    assert second["total_pnl_bp"] != pytest.approx(first["total_pnl_bp"])


def test_backtest_requires_253_joined_obs() -> None:
    """Short histories raise instead of returning partial results."""
    dates = ["2026-01-01", "2026-01-02"]
    slopes = [100.0, 101.0]
    with pytest.raises(ValueError, match="at least 254"):
        run_backtest(dates, slopes)
