"""Phase 2 backtest: fixed DV01 neutral 2s10s mean reversion illustration."""

from __future__ import annotations

import math
from collections.abc import Sequence

from goc_rates.analytics import Z_LOOKBACK, z_score
from goc_rates.dates import validate_strictly_increasing_dates
from goc_rates.limits import MAX_ABS_SLOPE_BP, MAX_BACKTEST_OBS, MIN_BACKTEST

BACKTEST_RULE = "2s10s_z252_meanrev_v1"
Z_ENTRY = 1.0


def run_backtest(dates: Sequence[str], slopes_bp: Sequence[float]) -> dict[str, object]:
    """Run the fixed next day DV01 neutral 2s10s mean reversion sketch.

    Signal uses the trailing 252 slope prints excluding the current day
    (no lookahead). When |z| exceeds Z_ENTRY the position is opposite the
    sign of z, entered the next day. PnL for day i is position_i times the
    next day slope change. Requires 252 history plus current plus next day,
    which is 254 joined observations, so one z plus one forward change
    exist, else raises.
    """
    raw_dates = list(dates)
    raw_slopes = list(slopes_bp)
    if len(raw_dates) != len(raw_slopes):
        raise ValueError("dates and slopes_bp must have equal length")
    if len(raw_dates) < MIN_BACKTEST:
        raise ValueError(f"backtest needs at least {MIN_BACKTEST} joined observations")
    if len(raw_dates) > MAX_BACKTEST_OBS:
        raise ValueError(f"backtest exceeds the {MAX_BACKTEST_OBS} observation cap")
    for date in raw_dates:
        if not isinstance(date, str):
            raise ValueError("dates must be non empty strings")
    validate_strictly_increasing_dates(raw_dates)
    for slope in raw_slopes:
        if not isinstance(slope, (int, float)) or isinstance(slope, bool):
            raise ValueError("slopes_bp must be numeric")
        value = float(slope)
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("slopes_bp must be finite")
        if abs(value) > MAX_ABS_SLOPE_BP:
            raise ValueError(f"slopes_bp exceeds the {MAX_ABS_SLOPE_BP} bp cap")
    date_list = raw_dates
    slope_list = [float(item) for item in raw_slopes]
    positions: list[float] = []
    daily_pnl_bp: list[float] = []
    signal_dates: list[str] = []
    for index in range(Z_LOOKBACK, len(slope_list) - 1):
        history = slope_list[index - Z_LOOKBACK : index]
        current = slope_list[index]
        score = z_score(current, history)
        position = 0.0
        if score is not None:
            if not math.isfinite(score):
                raise ValueError("z score must be finite")
            if score > Z_ENTRY:
                position = -1.0
            elif score < -Z_ENTRY:
                position = 1.0
        change = slope_list[index + 1] - current
        if abs(change) > 2.0 * MAX_ABS_SLOPE_BP:
            raise ValueError("slope change exceeds the supported range")
        pnl = position * change
        if not math.isfinite(pnl):
            raise ValueError("daily pnl must be finite")
        positions.append(position)
        daily_pnl_bp.append(pnl)
        signal_dates.append(date_list[index])
    total = sum(daily_pnl_bp)
    if not math.isfinite(total):
        raise ValueError("total pnl must be finite")
    return {
        "rule": BACKTEST_RULE,
        "entry_z": Z_ENTRY,
        "obs_count": len(date_list),
        "signal_dates": signal_dates,
        "positions": positions,
        "daily_pnl_bp": daily_pnl_bp,
        "total_pnl_bp": total,
        "pnl_unit": "bp",
        "dv01_note": "DV01 neutral sizing assumed, gross moves only",
    }
