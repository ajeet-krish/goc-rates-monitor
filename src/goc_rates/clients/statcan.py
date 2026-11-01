"""StatCan Web Data Service client. No API key is required.

Uses getDataFromVectorsAndLatestNPeriods and reuses seasonally adjusted
values as published, without extra transformation.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

from goc_rates.clients.base import (
    BaseClient,
    ensure_bounded_list,
    parse_json_capped,
)
from goc_rates.models import Quantity, Unit, make_missing, make_quantity

STATCAN_WDS_BASE_URL = "https://www150.statcan.gc.ca/t1/wds/rest"

DEFAULT_STATCAN_UNIT: Unit = "index_points"

MAX_LATEST_N = 120

_REFPER_FULL = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
_REFPER_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_REFPER_YEAR = re.compile(r"^(\d{4})$")
_REFPER_QUARTER = re.compile(r"^(\d{4})-Q([1-4])$")


@dataclass(frozen=True)
class StatCanObservation:
    """One StatCan vector observation, reused as published."""

    vector_id: str
    reference_period: str
    quantity: Quantity


def _vector_unit(vector_id: str, vector_units: dict[str, Unit] | None) -> Unit:
    """Return the published unit for a vector, defaulting to index points."""
    if vector_units is not None and vector_id in vector_units:
        return vector_units[vector_id]
    return DEFAULT_STATCAN_UNIT


def _validate_reference_period(period: str, vector_id: str) -> str:
    """Validate a StatCan reference period grammar and re-serialize it.

    Accepted forms are YYYY, YYYY-MM, YYYY-MM-DD, and YYYY-Q1 to YYYY-Q4.
    Full dates must be real calendar dates.
    """
    cleaned = period.strip()
    if _REFPER_YEAR.match(cleaned) or _REFPER_MONTH.match(cleaned):
        return cleaned
    if _REFPER_QUARTER.match(cleaned):
        return cleaned
    if _REFPER_FULL.match(cleaned):
        try:
            return dt.date.fromisoformat(cleaned).isoformat()
        except ValueError:
            raise ValueError(
                f"StatCan vector {vector_id} has an invalid period: {period!r}"
            ) from None
    raise ValueError(f"StatCan vector {vector_id} has an invalid period: {period!r}")


def fetch_statcan_vectors(
    vector_ids: list[str],
    client: BaseClient,
    latest_n: int = 3,
    vector_units: dict[str, Unit] | None = None,
) -> dict[str, list[StatCanObservation]]:
    """Fetch the latest N periods for each vector id, failing closed on drift."""
    cleaned = [item.strip() for item in vector_ids if isinstance(item, str) and item.strip()]
    if not cleaned:
        raise ValueError("vector_ids must contain at least one id")
    if latest_n < 1:
        raise ValueError("latest_n must be at least 1")
    if latest_n > MAX_LATEST_N:
        raise ValueError(f"latest_n must be at most {MAX_LATEST_N}")
    ensure_bounded_list(cleaned, "StatCan vector request")
    numeric_ids: list[int] = []
    for vector_id in cleaned:
        try:
            numeric_ids.append(int(vector_id))
        except ValueError:
            raise ValueError(f"StatCan vector id must be an integer: {vector_id!r}") from None
    payload: list[dict[str, Any]] = [
        {"vectorId": number, "latestN": latest_n} for number in numeric_ids
    ]
    response = client.post_json(
        f"{STATCAN_WDS_BASE_URL}/getDataFromVectorsAndLatestNPeriods", payload
    )
    body = parse_json_capped(response)
    if not isinstance(body, list):
        raise ValueError("StatCan response root must be a list")
    ensure_bounded_list(body, "StatCan response entries")
    results: dict[str, list[StatCanObservation]] = {vector_id: [] for vector_id in cleaned}
    seen: set[str] = set()
    for entry in body:
        if not isinstance(entry, dict):
            raise ValueError("StatCan response entry must be an object")
        status = entry.get("status")
        if status != "SUCCESS":
            raise ValueError(f"StatCan request failed with status: {status!r}")
        obj = entry.get("object")
        if not isinstance(obj, dict):
            raise ValueError("StatCan response entry is missing its object")
        raw_vector_id = obj.get("vectorId", "")
        vector_id = str(raw_vector_id).strip()
        if not vector_id:
            raise ValueError("StatCan response entry is missing its vectorId")
        if vector_id not in results:
            continue
        seen.add(vector_id)
        if "vectorDataPoint" not in obj:
            raise ValueError(f"StatCan vector {vector_id} is missing vectorDataPoint")
        raw_points = obj.get("vectorDataPoint")
        if not isinstance(raw_points, list):
            raise ValueError(f"StatCan vector {vector_id} has no observation list")
        ensure_bounded_list(raw_points, f"StatCan vector {vector_id} observations")
        unit = _vector_unit(vector_id, vector_units)
        parsed: list[StatCanObservation] = []
        for point in raw_points:
            if not isinstance(point, dict):
                raise ValueError("StatCan observation must be an object")
            period = str(
                point.get("refPer", point.get("referencePeriod", point.get("date", "")))
            ).strip()
            if not period:
                raise ValueError(f"StatCan vector {vector_id} observation is missing its period")
            reference_period = _validate_reference_period(period, vector_id)
            raw_value = point.get("value", point.get("v"))
            if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
                quantity = make_missing(
                    unit=unit,
                    source_id=f"statcan:{vector_id}",
                )
            else:
                quantity = make_quantity(
                    value=float(str(raw_value).strip()),
                    unit=unit,
                    quality="observed",
                    source_id=f"statcan:{vector_id}",
                )
            parsed.append(
                StatCanObservation(
                    vector_id=vector_id,
                    reference_period=reference_period,
                    quantity=quantity,
                )
            )
        results[vector_id] = parsed
    missing = [vector_id for vector_id in cleaned if vector_id not in seen]
    if missing:
        raise ValueError(f"StatCan response is missing requested vectors: {missing}")
    return results
