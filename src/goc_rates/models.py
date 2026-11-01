"""Core data model: every numeric field carries an explicit unit.

Fail closed: invalid quantities raise instead of returning partial data.
"""

from __future__ import annotations

import re
from typing import Literal, TypedDict

from goc_rates.limits import MAX_SOURCE_ID_LENGTH

Unit = Literal[
    "percent",
    "basis_points",
    "index_points",
    "business_days",
    "price_units_per_100_face",
    "days",
    "percent_yield",
    "bp",
    "bp_per_annum",
    "duration_years",
    "dv01_per_million",
    "unitless_ratio",
]
SourceId = str
Quality = Literal["observed", "missing", "stale", "revised"]


class Quantity(TypedDict):
    """A single numeric observation with explicit units and provenance."""

    value: float | None
    unit: Unit
    quality: Quality
    source_id: SourceId


_ALLOWED_QUALITIES: frozenset[str] = frozenset({"observed", "missing", "stale", "revised"})

SOURCE_ID_PATTERN = re.compile(r"^(derived|valet|fred|statcan):[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def validate_source_id(source_id: str) -> str:
    """Validate a source identifier against the closed grammar."""
    if not isinstance(source_id, str):
        raise ValueError("source_id must be a string")
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id exceeds {MAX_SOURCE_ID_LENGTH} characters")
    if not SOURCE_ID_PATTERN.match(source_id):
        raise ValueError(f"source_id uses an unknown grammar: {source_id!r}")
    return source_id


ALLOWED_UNITS: frozenset[str] = frozenset(
    {
        "percent",
        "basis_points",
        "index_points",
        "business_days",
        "price_units_per_100_face",
        "days",
        "percent_yield",
        "bp",
        "bp_per_annum",
        "duration_years",
        "dv01_per_million",
        "unitless_ratio",
    }
)


def make_quantity(
    value: float | None,
    unit: Unit,
    quality: Quality,
    source_id: SourceId,
) -> Quantity:
    """Build a Quantity and validate it before returning."""
    quantity: Quantity = {
        "value": value,
        "unit": unit,
        "quality": quality,
        "source_id": source_id,
    }
    validate_quantity(quantity)
    return quantity


def make_missing(unit: Unit, source_id: SourceId) -> Quantity:
    """Build a missing quality Quantity (value must be None)."""
    return make_quantity(value=None, unit=unit, quality="missing", source_id=source_id)


def validate_quantity(quantity: Quantity) -> None:
    """Validate a Quantity, raising ValueError on any violation."""
    if not isinstance(quantity, dict):
        raise ValueError("quantity must be a dict")
    for key in ("value", "unit", "quality", "source_id"):
        if key not in quantity:
            raise ValueError(f"quantity is missing required key: {key}")
    unit = quantity["unit"]
    quality = quantity["quality"]
    source_id = quantity["source_id"]
    value = quantity["value"]
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("quantity unit must be a non empty string")
    if unit.strip() not in ALLOWED_UNITS:
        raise ValueError(f"quantity unit is not in the closed unit set: {unit!r}")
    if quality not in _ALLOWED_QUALITIES:
        raise ValueError(f"quantity quality is not allowed: {quality!r}")
    if not isinstance(source_id, str):
        raise ValueError("quantity source_id must be a string")
    validate_source_id(source_id)
    if quality == "missing":
        if value is not None:
            raise ValueError("missing quantity must have value None")
        return
    if value is None:
        raise ValueError(f"quantity with quality {quality!r} must have a numeric value")
    if not isinstance(value, (int, float)):
        raise ValueError("quantity value must be numeric or None")
    if isinstance(value, bool):
        raise ValueError("quantity value must be numeric, not bool")
    float_value = float(value)
    if float_value != float_value or float_value in (float("inf"), float("-inf")):
        raise ValueError("quantity value must be finite")


def to_basis_points(percent_value: float, unit: Unit) -> float:
    """Convert a percent value to basis points, validating the unit label."""
    if not isinstance(unit, str):
        raise ValueError(f"expected a percent unit, got: {unit!r}")
    if unit.strip() not in ("percent", "percent_yield"):
        raise ValueError(f"expected a percent unit, got: {unit!r}")
    if not isinstance(percent_value, (int, float)) or isinstance(percent_value, bool):
        raise ValueError("percent_value must be numeric")
    result = float(percent_value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError("percent_value must be finite")
    return result * 100.0
