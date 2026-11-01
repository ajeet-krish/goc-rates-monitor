"""Calendar tests: Easter computus, holidays, business day arithmetic."""

import datetime as dt
from zoneinfo import ZoneInfo

from goc_rates.calendar import (
    add_business_days,
    ca_holidays,
    easter_sunday,
    is_business_day,
    leg_status,
    next_business_day,
    previous_business_day,
    resolve_observation_window,
    snapshot_date_for_run,
    us_bond_holidays,
)


def test_easter_sunday_known_dates() -> None:
    """Easter computus matches known Sundays."""
    assert easter_sunday(2025) == dt.date(2025, 4, 20)
    assert easter_sunday(2026) == dt.date(2026, 4, 5)


def test_good_friday_is_not_business_day() -> None:
    """Good Friday closes both legs."""
    assert not is_business_day(dt.date(2026, 4, 3), "joint")
    assert not is_business_day(dt.date(2026, 4, 3), "ca")
    assert not is_business_day(dt.date(2026, 4, 3), "us")


def test_christmas_observed_rule() -> None:
    """Holidays landing on weekends shift to Monday."""
    holidays = ca_holidays(2027)
    assert dt.date(2027, 12, 27) in holidays


def test_joint_calendar_requires_both_legs() -> None:
    """US Thanksgiving closes the joint calendar even when CA is open."""
    day = dt.date(2026, 11, 26)
    assert day not in ca_holidays(2026)
    assert day in us_bond_holidays(2026)
    assert is_business_day(day, "ca")
    assert not is_business_day(day, "joint")


def test_add_and_previous_next_business_days() -> None:
    """Business day arithmetic skips weekends."""
    friday = dt.date(2026, 10, 30)
    assert next_business_day(friday, "ca") == dt.date(2026, 11, 2)
    assert previous_business_day(dt.date(2026, 11, 2), "ca") == friday
    assert add_business_days(friday, 1, "ca") == dt.date(2026, 11, 2)
    assert add_business_days(friday, 0, "ca") == friday


def test_resolve_observation_window_walks_back() -> None:
    """Observation windows return business days ending at the anchor."""
    window = resolve_observation_window(dt.date(2026, 11, 2), 3, "ca")
    assert len(window) == 3
    assert window[0] == dt.date(2026, 11, 2)
    assert all(is_business_day(day, "ca") for day in window)


def test_snapshot_date_for_run_maps_weekends_back() -> None:
    """Saturday runs map to the previous Friday in Toronto time."""
    saturday = dt.datetime(2026, 10, 31, 12, 0, tzinfo=ZoneInfo("America/Toronto"))
    assert snapshot_date_for_run(saturday) == dt.date(2026, 10, 30)


def test_us_new_year_observed_crosses_year_boundary() -> None:
    """US observes Saturday Jan 1 2022 on Friday Dec 31 2021."""
    assert dt.date(2021, 12, 31) in us_bond_holidays(2022)
    status = leg_status(dt.date(2021, 12, 31))
    assert status == {"ca_open": True, "us_open": False}
    assert not is_business_day(dt.date(2021, 12, 31), "us")
    assert not is_business_day(dt.date(2021, 12, 31), "joint")
    assert is_business_day(dt.date(2021, 12, 31), "ca")
    assert not is_business_day(dt.date(2022, 1, 1), "joint")
    assert not is_business_day(dt.date(2022, 1, 1), "us")
