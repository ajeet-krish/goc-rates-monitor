"""Semiannual bond cashflow schedules with ACT/365 settlement timing.

Schedules step back in six month increments from maturity, with the day
clamped to the end of short months. Only cashflows strictly after the
settlement date are returned. Accrued interest uses ACT/365 day counts
from the previous coupon date, and dirty prices discount every cashflow
at the semiannual yield with a fractional exponent for the first period.
"""

from __future__ import annotations

import calendar as std_calendar
import datetime as dt
import math
from dataclasses import dataclass

from goc_rates.config import BenchmarkIssue
from goc_rates.limits import (
    MAX_CASHFLOWS_PER_INSTRUMENT,
    MAX_TENOR_YEARS,
    MAX_YIELD,
    MIN_YIELD,
)

DAYS_PER_YEAR: float = 365.0


@dataclass(frozen=True)
class CashFlow:
    """One bond payment measured from settlement.

    The payment date is a calendar date, years_from_settlement is a
    duration in duration_years on an ACT/365 basis, and
    amount_per_100_face is a payment in price_units_per_100_face.
    """

    payment_date: dt.date
    years_from_settlement: float
    amount_per_100_face: float


def _check_settlement(value: object) -> dt.date:
    """Return a validated settlement date, rejecting datetimes."""
    if isinstance(value, dt.datetime):
        raise ValueError("settlement must be a date, not a datetime")
    if not isinstance(value, dt.date):
        raise ValueError("settlement must be a date")
    return value


def _check_issue(issue: object) -> BenchmarkIssue:
    """Return a validated benchmark issue with semiannual coupons."""
    if not isinstance(issue, BenchmarkIssue):
        raise ValueError("issue must be a BenchmarkIssue")
    if issue.payments_per_year != 2:
        raise ValueError("issue must be semiannual (payments_per_year 2)")
    if not isinstance(issue.maturity_date, dt.date) or isinstance(issue.maturity_date, dt.datetime):
        raise ValueError("issue maturity_date must be a date")
    coupon = _check_coupon(issue.coupon_percent)
    if coupon < 0.0:
        raise ValueError("coupon_percent must be non negative")
    return issue


def _check_coupon(value: object) -> float:
    """Return a finite non negative coupon in percent."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("coupon_percent must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("coupon_percent must be finite")
    if not MIN_YIELD <= result <= MAX_YIELD:
        raise ValueError("coupon_percent is outside the supported yield range (unit: percent)")
    return result


def _check_yield(value: object) -> float:
    """Return a finite yield in percent within the supported range."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("yield_percent must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("yield_percent must be finite")
    if not MIN_YIELD <= result <= MAX_YIELD:
        raise ValueError("yield_percent is outside the supported range (unit: percent)")
    return result


def _shift_months(day: dt.date, months: int) -> dt.date:
    """Shift a date by whole months, clamping the day to month end."""
    total = day.year * 12 + (day.month - 1) + months
    year, month_index = divmod(total, 12)
    if year < 1 or year > 9999:
        raise ValueError("shifted date falls outside the supported year range")
    month = month_index + 1
    last_day = std_calendar.monthrange(year, month)[1]
    return dt.date(year, month, min(day.day, last_day))


def _coupon_dates_after(settlement: dt.date, maturity: dt.date) -> list[dt.date]:
    """Return coupon dates stepping back from maturity, strictly after settlement.

    Each date is derived directly from the maturity with a cumulative
    month offset so month end clamping never drifts (for example an
    August 31 maturity keeps August 31 across leap years instead of
    decaying to August 28). Iteration is capped so a compromised input
    cannot exhaust memory.
    """
    dates: list[dt.date] = []
    offset_months = 0
    steps = 0
    while True:
        candidate = _shift_months(maturity, offset_months)
        if not candidate > settlement:
            break
        dates.append(candidate)
        steps += 1
        if steps > MAX_CASHFLOWS_PER_INSTRUMENT:
            raise ValueError("cashflow count exceeds the per instrument cap")
        offset_months -= 6
    dates.reverse()
    return dates


def _previous_coupon_date(settlement: dt.date, maturity: dt.date) -> dt.date:
    """Return the latest coupon date on or before settlement.

    Dates are derived directly from the maturity with cumulative offsets
    so month end clamping never drifts across leap years.
    """
    offset_months = 0
    steps = 0
    while True:
        candidate = _shift_months(maturity, offset_months)
        if not candidate > settlement:
            return candidate
        offset_months -= 6
        steps += 1
        if steps > MAX_CASHFLOWS_PER_INSTRUMENT + 1:
            raise ValueError("coupon search exceeds the per instrument cap")


def generate_cashflows(settlement: dt.date, issue: BenchmarkIssue) -> tuple[CashFlow, ...]:
    """Generate cashflows strictly after settlement for one issue.

    Coupons step back semiannually from maturity with month end clamping.
    Intermediate coupons pay coupon divided by two, and the final payment
    adds 100 face. Times use ACT/365 from settlement in duration_years,
    and amounts use price_units_per_100_face.
    """
    settlement_date = _check_settlement(settlement)
    bond = _check_issue(issue)
    if not bond.maturity_date > settlement_date:
        raise ValueError("maturity_date must be strictly after settlement")
    residual_years = (bond.maturity_date - settlement_date).days / DAYS_PER_YEAR
    if residual_years > MAX_TENOR_YEARS:
        raise ValueError("residual tenor exceeds the tenor cap (unit: duration_years)")
    dates = _coupon_dates_after(settlement_date, bond.maturity_date)
    if not dates:
        raise ValueError("no cashflows fall strictly after settlement")
    half_coupon = bond.coupon_percent / 2.0
    flows: list[CashFlow] = []
    for day in dates:
        years = (day - settlement_date).days / DAYS_PER_YEAR
        if years <= 0.0:
            raise ValueError("cashflow must fall strictly after settlement")
        amount = half_coupon + (100.0 if day == bond.maturity_date else 0.0)
        if not math.isfinite(years) or not math.isfinite(amount):
            raise ValueError("cashflow terms must be finite")
        if amount <= 0.0:
            raise ValueError("cashflow amount must be positive")
        flows.append(
            CashFlow(
                payment_date=day,
                years_from_settlement=years,
                amount_per_100_face=amount,
            )
        )
    return tuple(flows)


def accrued_interest(settlement: dt.date, issue: BenchmarkIssue) -> float:
    """Return accrued interest per 100 face from the previous coupon date.

    The accrual is coupon_percent times ACT/365 days since the previous
    coupon date, in price_units_per_100_face. Settlement on a coupon date
    accrues zero.
    """
    settlement_date = _check_settlement(settlement)
    bond = _check_issue(issue)
    if not bond.maturity_date > settlement_date:
        raise ValueError("maturity_date must be strictly after settlement")
    previous = _previous_coupon_date(settlement_date, bond.maturity_date)
    days = (settlement_date - previous).days
    if days < 0:
        raise ValueError("previous coupon must not fall after settlement")
    result = bond.coupon_percent * float(days) / DAYS_PER_YEAR
    if not math.isfinite(result) or result < 0.0:
        raise ValueError("accrued interest must be finite and non negative")
    return result


def dirty_price_from_yield(
    settlement: dt.date, issue: BenchmarkIssue, yield_percent: float
) -> float:
    """Return the dirty price per 100 face at a semiannual yield.

    Every cashflow is discounted at 1 plus yield divided by two raised to
    twice its ACT/365 years from settlement, so the first fractional
    period is handled explicitly. The yield uses percent and the price
    uses price_units_per_100_face.
    """
    settlement_date = _check_settlement(settlement)
    bond = _check_issue(issue)
    rate = _check_yield(yield_percent) / 100.0
    base = 1.0 + rate / 2.0
    if base <= 0.0:
        raise ValueError("yield implies a non positive semiannual base")
    flows = generate_cashflows(settlement_date, bond)
    total = 0.0
    for flow in flows:
        try:
            total += flow.amount_per_100_face / (base ** (2.0 * flow.years_from_settlement))
        except (OverflowError, ZeroDivisionError):
            raise ValueError("dirty price computation overflowed") from None
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("dirty price must be finite and positive")
    return total
