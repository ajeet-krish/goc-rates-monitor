"""Month over month, annualized, and year over year CPI changes."""

from __future__ import annotations

from collections.abc import Sequence

from goc_rates.limits import MAX_CPI_MONTHS


def _check_index(value: float, name: str) -> float:
    """Return a finite positive index level, else raise."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be finite")
    if result <= 0.0:
        raise ValueError(f"{name} must be positive")
    return result


def _check_monthly_percent(value: float, name: str) -> float:
    """Return a finite monthly percent change, else raise."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be finite")
    return result


def month_over_month_percent(current_index: float, previous_index: float) -> float:
    """Return the monthly rate in percent: (cur / prev - 1) * 100."""
    current = _check_index(current_index, "current_index")
    previous = _check_index(previous_index, "previous_index")
    result = (current / previous - 1.0) * 100.0
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("month over month computation overflowed")
    return result


def annualized_from_monthly_percent(monthly_percent: float) -> float:
    """Annualize one monthly rate: ((1 + m / 100) ^ 12 - 1) * 100."""
    monthly = _check_monthly_percent(monthly_percent, "monthly_percent")
    if 1.0 + monthly / 100.0 <= 0.0:
        raise ValueError("monthly_percent implies a non positive monthly factor")
    try:
        result = float(((1.0 + monthly / 100.0) ** 12.0 - 1.0) * 100.0)
    except OverflowError:
        raise ValueError("annualized computation overflowed") from None
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("annualized computation overflowed")
    return result


def year_over_year_percent(current_index: float, year_ago_index: float) -> float:
    """Return the 12 month rate in percent: (cur / ago - 1) * 100."""
    current = _check_index(current_index, "current_index")
    year_ago = _check_index(year_ago_index, "year_ago_index")
    result = (current / year_ago - 1.0) * 100.0
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("year over year computation overflowed")
    return result


def compound_annual_percent(monthly_rates: Sequence[float]) -> float:
    """Compound monthly rates into an annual rate, never averaging.

    annual = (prod(1 + m / 100) - 1) * 100 over the supplied months.
    """
    rates = list(monthly_rates)
    if not rates:
        raise ValueError("need at least one monthly rate to compound")
    if len(rates) > MAX_CPI_MONTHS:
        raise ValueError(f"monthly rate count {len(rates)} exceeds the {MAX_CPI_MONTHS} month cap")
    factor = 1.0
    for rate in rates:
        monthly = _check_monthly_percent(rate, "monthly rate")
        if 1.0 + monthly / 100.0 <= 0.0:
            raise ValueError("monthly rate implies a non positive monthly factor")
        try:
            factor *= 1.0 + monthly / 100.0
        except OverflowError:
            raise ValueError("compounding overflowed") from None
        if factor != factor or factor in (float("inf"), float("-inf")):
            raise ValueError("compounding overflowed")
    result = (factor - 1.0) * 100.0
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("compounding overflowed")
    return result
