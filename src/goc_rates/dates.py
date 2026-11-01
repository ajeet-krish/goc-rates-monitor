"""Strict ISO date parsing with a fixed YYYY-MM-DD grammar."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Sequence

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_strict_iso_date(text: str) -> dt.date:
    """Parse an exact YYYY-MM-DD date string, failing closed otherwise.

    The input must match the fixed grammar with no surrounding whitespace.
    Parsing uses fromisoformat plus an isoformat round trip so impossible
    calendar dates are rejected.
    """
    if not isinstance(text, str):
        raise ValueError(f"date must be a string, got {type(text).__name__}")
    if not _ISO_DATE_RE.match(text):
        raise ValueError(f"date must use YYYY-MM-DD grammar: {text!r}")
    try:
        parsed = dt.date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"date is not a real calendar date: {text!r}") from None
    if parsed.isoformat() != text:
        raise ValueError(f"date round trip failed: {text!r}")
    return parsed


def validate_strictly_increasing_dates(dates: Sequence[str]) -> list[dt.date]:
    """Parse strict ISO dates and require a strictly increasing sequence."""
    parsed: list[dt.date] = [parse_strict_iso_date(item) for item in dates]
    for first, second in zip(parsed, parsed[1:], strict=False):
        if not second > first:
            raise ValueError("dates must be strictly increasing")
    return parsed
