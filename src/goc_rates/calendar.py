"""Business day calendar: joint CA (BoC Schedule I) plus US (SIFMA bond) legs.

Each date carries per leg flags. The joint calendar treats a day as a
business day only when both legs are open. All datetimes resolve in the
America/Toronto zone for snapshot dating.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo

TORONTO_TZ = ZoneInfo("America/Toronto")

MAX_ADD_BUSINESS_DAYS = 1250
MAX_LOOKBACK_BUSINESS_DAYS = 250


def easter_sunday(year: int) -> dt.date:
    """Compute Easter Sunday with the Anonymous Gregorian computus."""
    if year < 1583:
        raise ValueError(f"year out of range for Gregorian computus: {year}")
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month = (h + ell - 7 * m + 114) // 31
    day = ((h + ell - 7 * m + 114) % 31) + 1
    return dt.date(year, month, day)


def good_friday(year: int) -> dt.date:
    """Return Good Friday for the given year."""
    return easter_sunday(year) - dt.timedelta(days=2)


def easter_monday(year: int) -> dt.date:
    """Return Easter Monday for the given year."""
    return easter_sunday(year) + dt.timedelta(days=1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """Return the nth weekday (Monday is 0) of a month."""
    first = dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + dt.timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
    """Return the last weekday (Monday is 0) of a month."""
    if month == 12:
        first_next = dt.date(year + 1, 1, 1)
    else:
        first_next = dt.date(year, month + 1, 1)
    last = first_next - dt.timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - dt.timedelta(days=offset)


def _observed_ca(day: dt.date) -> dt.date:
    """Shift a CA fixed holiday that falls on a weekend to the next Monday."""
    if day.weekday() == 5:
        return day + dt.timedelta(days=2)
    if day.weekday() == 6:
        return day + dt.timedelta(days=1)
    return day


def _observed_us(day: dt.date) -> dt.date:
    """Shift a US fixed holiday: Saturday to Friday, Sunday to Monday."""
    if day.weekday() == 5:
        return day - dt.timedelta(days=1)
    if day.weekday() == 6:
        return day + dt.timedelta(days=1)
    return day


def _add_observed_ca(days: set[dt.date], actual: dt.date) -> None:
    """Add a CA observed holiday, bumping forward on collisions or weekends."""
    candidate = _observed_ca(actual)
    while candidate in days or candidate.weekday() >= 5:
        candidate += dt.timedelta(days=1)
    days.add(candidate)


@lru_cache(maxsize=8)
def ca_holidays(year: int) -> set[dt.date]:
    """Return federal holidays observed by Schedule I banks in Toronto."""
    days: set[dt.date] = set()
    _add_observed_ca(days, dt.date(year, 1, 1))
    days.add(good_friday(year))
    days.add(easter_monday(year))
    days.add(_nth_weekday(year, 2, 0, 3))
    days.add(_victoria_day(year))
    _add_observed_ca(days, dt.date(year, 7, 1))
    days.add(_nth_weekday(year, 8, 0, 1))
    days.add(_nth_weekday(year, 9, 0, 1))
    _add_observed_ca(days, dt.date(year, 9, 30))
    days.add(_nth_weekday(year, 10, 0, 2))
    _add_observed_ca(days, dt.date(year, 11, 11))
    _add_observed_ca(days, dt.date(year, 12, 25))
    _add_observed_ca(days, dt.date(year, 12, 26))
    return set(days)


def _victoria_day(year: int) -> dt.date:
    """Return Victoria Day (Monday before May 25)."""
    candidate = dt.date(year, 5, 25)
    offset = (candidate.weekday() - 0) % 7
    monday = candidate - dt.timedelta(days=offset)
    if monday == candidate:
        monday -= dt.timedelta(days=7)
    return monday


@lru_cache(maxsize=8)
def us_bond_holidays(year: int) -> set[dt.date]:
    """Return SIFMA bond market holidays for the given year."""
    days: set[dt.date] = {
        _observed_us(dt.date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        good_friday(year),
        _last_weekday(year, 5, 0),
        _observed_us(dt.date(year, 6, 19)),
        _observed_us(dt.date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 10, 0, 2),
        _observed_us(dt.date(year, 11, 11)),
        _nth_weekday(year, 11, 3, 4),
        _observed_us(dt.date(year, 12, 25)),
    }
    return set(days)


def leg_status(day: dt.date) -> dict[str, bool]:
    """Return per leg open flags for a date.

    Holiday sets are consulted for the previous, current, and next year
    because observed dates can cross a year boundary (for example the US
    bond market observes a Saturday January 1 on Friday December 31 of
    the prior year).
    """
    is_weekend = day.weekday() >= 5
    ca_days = ca_holidays(day.year - 1) | ca_holidays(day.year) | ca_holidays(day.year + 1)
    us_days = (
        us_bond_holidays(day.year - 1) | us_bond_holidays(day.year) | us_bond_holidays(day.year + 1)
    )
    ca_open = (day not in ca_days) and not is_weekend
    us_open = (day not in us_days) and not is_weekend
    return {"ca_open": ca_open, "us_open": us_open}


def is_business_day(day: dt.date, calendar: str = "joint") -> bool:
    """Return True when the date is a business day on the given calendar."""
    status = leg_status(day)
    if calendar == "ca":
        return status["ca_open"]
    if calendar == "us":
        return status["us_open"]
    if calendar == "joint":
        return status["ca_open"] and status["us_open"]
    raise ValueError(f"unknown calendar: {calendar!r}")


def previous_business_day(day: dt.date, calendar: str = "joint") -> dt.date:
    """Return the previous business day strictly before the given date."""
    candidate = day - dt.timedelta(days=1)
    while not is_business_day(candidate, calendar):
        candidate -= dt.timedelta(days=1)
    return candidate


def next_business_day(day: dt.date, calendar: str = "joint") -> dt.date:
    """Return the next business day strictly after the given date."""
    candidate = day + dt.timedelta(days=1)
    while not is_business_day(candidate, calendar):
        candidate += dt.timedelta(days=1)
    return candidate


def add_business_days(day: dt.date, count: int, calendar: str = "joint") -> dt.date:
    """Add (or subtract) business days, skipping weekends and holidays."""
    if count == 0:
        return day
    if abs(count) > MAX_ADD_BUSINESS_DAYS:
        raise ValueError(f"count must be within {MAX_ADD_BUSINESS_DAYS} business days")
    step = 1 if count > 0 else -1
    candidate = day
    remaining = abs(count)
    while remaining > 0:
        candidate += dt.timedelta(days=step)
        if is_business_day(candidate, calendar):
            remaining -= 1
    return candidate


def resolve_observation_window(
    target_date: dt.date,
    lookback_business_days: int = 5,
    calendar: str = "joint",
) -> list[dt.date]:
    """Return candidate observation dates ending at the target date.

    The window walks back over business days so stale data checks can
    find the most recent printable observation. Fails closed on bad input.
    """
    if lookback_business_days < 1:
        raise ValueError("lookback_business_days must be at least 1")
    if lookback_business_days > MAX_LOOKBACK_BUSINESS_DAYS:
        raise ValueError(f"lookback_business_days must be at most {MAX_LOOKBACK_BUSINESS_DAYS}")
    anchor = target_date
    if not is_business_day(anchor, calendar):
        anchor = previous_business_day(anchor, calendar)
    window: list[dt.date] = [anchor]
    while len(window) < lookback_business_days:
        anchor = previous_business_day(anchor, calendar)
        window.append(anchor)
    return window


def snapshot_date_for_run(now: dt.datetime | None = None) -> dt.date:
    """Return the snapshot date for a pipeline run in America/Toronto.

    Weekend and holiday runs map back to the previous joint business day.
    """
    current = now if now is not None else dt.datetime.now(tz=TORONTO_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TORONTO_TZ)
    local = current.astimezone(TORONTO_TZ)
    day = local.date()
    if not is_business_day(day, "joint"):
        return previous_business_day(day, "joint")
    return day
