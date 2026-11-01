"""Phase 5 breaks engine: benchmark switch day over day gate.

Method benchmark_switch_dod_gate_v1 flags benchmark rotations from the
pinned bench_CDN.pdf feed. A switch inside the (prev, current] window
suppresses the day over day delta to null with a switch_break gate. A
calendar gap keeps the delta but flags calendar_gap. A switch takes
precedence over a calendar gap, so a day with both flags is switch_break
with a null delta. Missing legs use
missing_prev or insufficient_history with null deltas. Threshold 15 bp
in basis points marks a break entry requiring explanation.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from goc_rates.calendar import is_business_day, previous_business_day
from goc_rates.dates import parse_strict_iso_date
from goc_rates.limits import (
    MAX_DOD_RECORDS,
    MAX_HISTORY_OBS,
    MAX_SWITCH_EVENTS,
    MAX_SWITCH_FEED_BYTES,
    MAX_YIELD,
    MIN_YIELD,
)

BREAKS_METHOD = "benchmark_switch_dod_gate_v1"
BREAKS_THRESHOLD_BP = 15.0
BREAKS_TENORS: tuple[str, ...] = ("2Y", "5Y", "10Y", "30Y")
FEED_ALLOWED_TENORS: tuple[str, ...] = ("2Y", "3Y", "5Y", "7Y", "10Y", "30Y", "LONG")
FEED_SCHEMA_VERSION = 1
FEED_SOURCE = "bench_CDN.pdf"
BENCH_CDN_URL = "https://www.bankofcanada.ca/stats/assets/pdf/bench_CDN.pdf"
BREAKS_GATES: tuple[str, ...] = (
    "comparable",
    "switch_break",
    "calendar_gap",
    "missing_prev",
    "insufficient_history",
)
BREAKS_SOURCE_ID = "derived:dod_gate"

__all__ = [
    "BENCH_CDN_URL",
    "BREAKS_GATES",
    "BREAKS_METHOD",
    "BREAKS_SOURCE_ID",
    "BREAKS_TENORS",
    "BREAKS_THRESHOLD_BP",
    "FEED_ALLOWED_TENORS",
    "FEED_SCHEMA_VERSION",
    "FEED_SOURCE",
    "SwitchEvent",
    "SwitchFeed",
    "SwitchIssue",
    "build_breaks_section",
    "classify_gate",
    "effective_joint_date",
    "load_switch_feed",
    "normalize_tenor",
    "switch_in_window",
]


@dataclass(frozen=True)
class SwitchIssue:
    """One benchmark issue leg: maturity date or null plus coupon or null."""

    maturity: str | None
    coupon_percent: float | None


@dataclass(frozen=True)
class SwitchEvent:
    """One benchmark switch with effective and joint effective dates."""

    tenor: str
    effective_date: dt.date
    effective_joint_date: dt.date
    incoming: SwitchIssue
    outgoing: SwitchIssue


@dataclass(frozen=True)
class SwitchFeed:
    """Pinned switch feed with vintage and file digest."""

    source: str
    feed_vintage: dt.date
    events: tuple[SwitchEvent, ...]
    feed_sha256: str


def normalize_tenor(tenor: str) -> str:
    """Map the LONG bench label to the 30Y curve tenor."""
    if tenor == "LONG":
        return "30Y"
    return tenor


def effective_joint_date(day: dt.date) -> dt.date:
    """Return the first joint business day on or after the given date."""
    if not isinstance(day, dt.date):
        raise ValueError("effective date must be a date")
    candidate = day
    try:
        for _ in range(16):
            if is_business_day(candidate, "joint"):
                return candidate
            candidate += dt.timedelta(days=1)
    except OverflowError:
        raise ValueError(f"effective {day.isoformat()} overflows") from None
    except ValueError:
        raise ValueError(f"effective {day.isoformat()} outside range") from None
    raise ValueError(f"no joint business day within 16 days of {day.isoformat()}")


def _require_tenor(value: Any) -> str:
    """Require a tenor from the closed feed set."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("switch tenor must be a non empty string")
    cleaned = value.strip()
    if cleaned not in FEED_ALLOWED_TENORS:
        raise ValueError(f"switch tenor must be one of {list(FEED_ALLOWED_TENORS)}")
    return cleaned


def _optional_iso_date(value: Any, name: str) -> str | None:
    """Return a strict ISO date string or None, failing closed on bad input."""
    if value is None:
        return None
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value.isoformat()
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a strict ISO string or null")
    return parse_strict_iso_date(value).isoformat()


def _require_iso_date(value: Any, name: str) -> dt.date:
    """Require a strict ISO date from a string or date object."""
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a strict ISO string")
    return parse_strict_iso_date(value)


def _optional_coupon(value: Any, name: str) -> float | None:
    """Return a finite coupon in percent or None."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric or null")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be finite")
    if not MIN_YIELD <= result <= MAX_YIELD:
        raise ValueError(f"{name} must be within [{MIN_YIELD}, {MAX_YIELD}] percent")
    return result


def load_switch_feed(path: str | Path) -> SwitchFeed:
    """Load and validate the pinned switch feed, failing closed on drift."""
    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError(f"switch feed not found: {file_path}")
    try:
        declared = file_path.stat().st_size
    except OSError:
        raise ValueError(f"switch feed not found: {file_path}") from None
    if declared > MAX_SWITCH_FEED_BYTES:
        raise ValueError(
            f"switch feed of {declared} bytes exceeds the {MAX_SWITCH_FEED_BYTES} byte cap"
        )
    raw_bytes = file_path.read_bytes()
    if len(raw_bytes) > MAX_SWITCH_FEED_BYTES:
        raise ValueError(
            f"switch feed of {len(raw_bytes)} bytes exceeds the {MAX_SWITCH_FEED_BYTES} byte cap"
        )
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("switch feed must be UTF-8 text") from None
    raw: Any = yaml.safe_load(raw_text)
    if not isinstance(raw, dict):
        raise ValueError("switch feed root must be a mapping")
    if raw.get("schema_version") != FEED_SCHEMA_VERSION:
        raise ValueError(f"unsupported switch schema_version: {raw.get('schema_version')!r}")
    source = raw.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("switch feed source must be a non empty string")
    if source.strip() != FEED_SOURCE:
        raise ValueError(f"switch feed source must pin {FEED_SOURCE}")
    vintage_raw = raw.get("feed_vintage")
    try:
        vintage = _require_iso_date(vintage_raw, "feed_vintage")
    except ValueError:
        raise ValueError("switch feed_vintage must be a strict ISO string") from None
    events_raw = raw.get("events")
    if not isinstance(events_raw, list) or not events_raw:
        raise ValueError("switch feed needs a non empty events list")
    if len(events_raw) > MAX_SWITCH_EVENTS:
        raise ValueError("switch event count exceeds the cap before recompute")
    events: list[SwitchEvent] = []
    seen: set[tuple[str, str]] = set()
    for row in events_raw:
        if not isinstance(row, dict):
            raise ValueError("switch event rows must be mappings")
        tenor = _require_tenor(row.get("tenor"))
        effective_raw = row.get("effective_date")
        try:
            effective = _require_iso_date(effective_raw, "effective_date")
        except ValueError:
            raise ValueError("switch effective_date must be a strict ISO string") from None
        key = (tenor, effective.isoformat())
        if key in seen:
            raise ValueError(f"duplicate switch event: {key}")
        seen.add(key)
        incoming_maturity = _optional_iso_date(row.get("incoming_maturity"), "incoming_maturity")
        incoming_coupon = _optional_coupon(
            row.get("incoming_coupon_percent"), "incoming_coupon_percent"
        )
        outgoing_maturity = _optional_iso_date(row.get("outgoing_maturity"), "outgoing_maturity")
        outgoing_coupon = _optional_coupon(
            row.get("outgoing_coupon_percent"), "outgoing_coupon_percent"
        )
        joint = effective_joint_date(effective)
        events.append(
            SwitchEvent(
                tenor=tenor,
                effective_date=effective,
                effective_joint_date=joint,
                incoming=SwitchIssue(maturity=incoming_maturity, coupon_percent=incoming_coupon),
                outgoing=SwitchIssue(maturity=outgoing_maturity, coupon_percent=outgoing_coupon),
            )
        )
    events.sort(key=lambda item: (item.effective_joint_date, item.tenor))
    digest = hashlib.sha256(raw_bytes).hexdigest()
    return SwitchFeed(
        source=source.strip(),
        feed_vintage=vintage,
        events=tuple(events),
        feed_sha256=digest,
    )


def switch_in_window(
    tenor: str,
    prev_date: dt.date,
    current_date: dt.date,
    feed: SwitchFeed,
) -> bool:
    """Return True when a switch joint date lands in (prev, current]."""
    if normalize_tenor(tenor) not in BREAKS_TENORS:
        raise ValueError(f"breaks tenor must be one of {list(BREAKS_TENORS)}")
    if not isinstance(prev_date, dt.date) or not isinstance(current_date, dt.date):
        raise ValueError("window bounds must be dates")
    if not current_date > prev_date:
        raise ValueError("current date must exceed prev date for a switch window")
    target = normalize_tenor(tenor)
    for event in feed.events:
        if normalize_tenor(event.tenor) != target:
            continue
        joint = event.effective_joint_date
        if joint > prev_date and joint <= current_date:
            return True
    return False


def classify_gate(
    prev_yield: float | None,
    current_yield: float | None,
    switch_flag: bool,
    calendar_gap_flag: bool,
    history_count: int,
) -> str:
    """Classify one tenor day over day move into a closed gate set.

    Precedence is insufficient_history, then missing_prev, then switch_break,
    then calendar_gap, then comparable, so a switch day with a calendar gap
    is switch_break with a null delta.
    """
    if not isinstance(switch_flag, bool) or not isinstance(calendar_gap_flag, bool):
        raise ValueError("gate flags must be bools without coercion")
    if isinstance(history_count, bool) or not isinstance(history_count, int):
        raise ValueError("history_count must be an int without coercion")
    if history_count < 0 or history_count > MAX_HISTORY_OBS:
        raise ValueError("history_count is outside the bounded range")
    if history_count < 2:
        return "insufficient_history"
    if prev_yield is None or current_yield is None:
        return "missing_prev"
    for value in (prev_yield, current_yield):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("gate yields must be numeric or null")
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError("gate yields must be finite")
    if switch_flag:
        return "switch_break"
    if calendar_gap_flag:
        return "calendar_gap"
    return "comparable"


def _yield_or_none(history: dict[str, float], date_text: str) -> float | None:
    """Read a finite yield from a history mapping, returning None when absent."""
    value = history.get(date_text)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("ca history yields must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("ca history yields must be finite")
    if not MIN_YIELD <= result <= MAX_YIELD:
        raise ValueError("ca history yield is outside the supported range")
    return result


def build_breaks_section(
    snapshot_date: dt.date | str,
    print_date: dt.date | str,
    ca_histories: dict[str, dict[str, float]],
    feed: SwitchFeed,
) -> dict[str, Any]:
    """Build the breaks observations section from histories and the feed."""
    if isinstance(snapshot_date, str):
        snapshot_day = parse_strict_iso_date(snapshot_date)
    elif isinstance(snapshot_date, dt.date):
        snapshot_day = snapshot_date
    else:
        raise ValueError("snapshot_date must be a strict ISO string or date")
    if isinstance(print_date, str):
        print_day = parse_strict_iso_date(print_date)
    elif isinstance(print_date, dt.date):
        print_day = print_date
    else:
        raise ValueError("print_date must be a strict ISO string or date")
    if not isinstance(ca_histories, dict):
        raise ValueError("ca_histories must be a mapping")
    if not isinstance(feed, SwitchFeed):
        raise ValueError("feed must be a SwitchFeed")
    if len(feed.events) > MAX_SWITCH_EVENTS:
        raise ValueError("switch event count exceeds the cap before recompute")
    print_text = print_day.isoformat()
    records: list[dict[str, Any]] = []
    for tenor in BREAKS_TENORS:
        raw_history = ca_histories.get(tenor, {})
        if not isinstance(raw_history, dict):
            raise ValueError(f"ca history for {tenor} must be a mapping")
        if len(raw_history) > MAX_HISTORY_OBS:
            raise ValueError("ca history exceeds the observation cap")
        history: dict[str, float] = {}
        for date_text, value in raw_history.items():
            if not isinstance(date_text, str):
                raise ValueError("ca history dates must be strict ISO strings")
            parse_strict_iso_date(date_text)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("ca history yields must be numeric")
            number = float(value)
            if number != number or number in (float("inf"), float("-inf")):
                raise ValueError("ca history yields must be finite")
            history[date_text] = number
        history_count = len(history)
        current_yield = _yield_or_none(history, print_text)
        immediate_prev = previous_business_day(print_day, "joint")
        prev_day: dt.date | None = None
        calendar_gap = False
        if not is_business_day(print_day, "joint"):
            calendar_gap = True
        candidate = immediate_prev
        for _ in range(10):
            if history.get(candidate.isoformat()) is not None:
                prev_day = candidate
                break
            candidate = previous_business_day(candidate, "joint")
        if prev_day is None:
            prev_text = immediate_prev.isoformat()
            prev_yield: float | None = None
        else:
            prev_text = prev_day.isoformat()
            prev_yield = _yield_or_none(history, prev_text)
            if prev_day != immediate_prev:
                calendar_gap = True
        if prev_day is not None and prev_day >= print_day:
            raise ValueError("prev date must precede the print date")
        switch_flag = False
        if prev_day is not None:
            switch_flag = switch_in_window(tenor, prev_day, print_day, feed)
        gate = classify_gate(prev_yield, current_yield, switch_flag, calendar_gap, history_count)
        if gate in ("switch_break", "missing_prev", "insufficient_history"):
            dod: float | None = None
        else:
            assert prev_yield is not None and current_yield is not None
            dod = (current_yield - prev_yield) * 100.0
            if dod != dod or dod in (float("inf"), float("-inf")):
                raise ValueError("dod recomputation overflowed")
        quality = "observed" if dod is not None else "missing"
        record: dict[str, Any] = {
            "tenor": tenor,
            "prev_date": prev_text,
            "current_date": print_text,
            "prev_yield_percent": prev_yield,
            "current_yield_percent": current_yield,
            "prev_yield_unit": "percent",
            "current_yield_unit": "percent",
            "dod_bp": dod,
            "dod_unit": "basis_points",
            "gate": gate,
            "switch_in_window": switch_flag,
            "calendar_gap": calendar_gap,
            "history_count": history_count,
            "history_count_unit": "count",
            "dod_quantity": {
                "value": dod,
                "unit": "basis_points",
                "quality": quality,
                "source_id": BREAKS_SOURCE_ID,
            },
            "source_id": BREAKS_SOURCE_ID,
        }
        records.append(record)
    if len(records) > MAX_DOD_RECORDS:
        raise ValueError("dod record count exceeds the cap")
    events_out: list[dict[str, Any]] = []
    for event in feed.events:
        events_out.append(
            {
                "tenor": event.tenor,
                "effective_date": event.effective_date.isoformat(),
                "effective_joint_date": event.effective_joint_date.isoformat(),
                "incoming_maturity": event.incoming.maturity,
                "incoming_coupon_percent": event.incoming.coupon_percent,
                "incoming_coupon_unit": "percent",
                "outgoing_maturity": event.outgoing.maturity,
                "outgoing_coupon_percent": event.outgoing.coupon_percent,
                "outgoing_coupon_unit": "percent",
            }
        )
    return {
        "method": BREAKS_METHOD,
        "snapshot_date": snapshot_day.isoformat(),
        "print_date": print_text,
        "feed_source": feed.source,
        "feed_vintage": feed.feed_vintage.isoformat(),
        "feed_sha256": feed.feed_sha256,
        "threshold_bp": BREAKS_THRESHOLD_BP,
        "threshold_unit": "basis_points",
        "events": events_out,
        "records": records,
    }
