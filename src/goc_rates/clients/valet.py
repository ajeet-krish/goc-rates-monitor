"""Bank of Canada Valet client. No API key is required."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from goc_rates.clients.base import (
    BaseClient,
    ensure_bounded_list,
    parse_json_capped,
)
from goc_rates.models import Quantity, make_missing, make_quantity

VALET_BASE_URL = "https://www.bankofcanada.ca/valet"
VALET_GROUP = "bond_yields_benchmark"

VALET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class ValetObservation:
    """One Valet observation with its upstream label."""

    observation_date: str
    series_id: str
    label: str
    quantity: Quantity


def _parse_float(raw: str) -> float | None:
    """Parse a Valet value string, returning None for empty prints."""
    text = raw.strip()
    if text == "":
        return None
    return float(text)


def _check_valet_id(value: str, field: str) -> str:
    """Validate a Valet path segment against the closed ID grammar."""
    cleaned = value.strip()
    if not VALET_ID_PATTERN.match(cleaned):
        raise ValueError(f"{field} must match {VALET_ID_PATTERN.pattern}: {cleaned!r}")
    return cleaned


def _parse_observation_date(raw: str) -> str:
    """Parse an upstream observation date and re-serialize it as ISO."""
    try:
        return dt.date.fromisoformat(raw.strip()).isoformat()
    except ValueError:
        raise ValueError(f"Valet observation date is not ISO YYYY-MM-DD: {raw!r}") from None


def fetch_valet_series(
    series_id: str,
    client: BaseClient,
    label: str | None = None,
) -> list[ValetObservation]:
    """Fetch one Valet series and assert its label when an expected label is given."""
    cleaned = _check_valet_id(series_id, "series_id")
    url = f"{VALET_BASE_URL}/observations/{cleaned}/json"
    response = client.get(url)
    payload = parse_json_capped(response)
    if not isinstance(payload, dict):
        raise ValueError("Valet response root must be an object")
    detail = payload.get("seriesDetail", {})
    upstream_label = ""
    if isinstance(detail, dict):
        entry = detail.get(cleaned, {})
        if isinstance(entry, dict):
            raw_label = entry.get("label", "")
            if isinstance(raw_label, str):
                upstream_label = raw_label.strip()
    if label is not None and upstream_label != label.strip():
        raise ValueError(
            f"Valet label drift for {cleaned}: expected {label!r}, got {upstream_label!r}"
        )
    if "observations" not in payload:
        raise ValueError("Valet response is missing its observations key")
    observations = payload.get("observations")
    if not isinstance(observations, list):
        raise ValueError("Valet observations must be a list")
    ensure_bounded_list(observations, "Valet observations")
    results: list[ValetObservation] = []
    for item in observations:
        if not isinstance(item, dict):
            raise ValueError("Valet observation must be an object")
        date_text = item.get("d", "")
        if not isinstance(date_text, str) or not date_text.strip():
            raise ValueError("Valet observation is missing its date")
        observation_date = _parse_observation_date(date_text)
        cell = item.get(cleaned, {})
        if not isinstance(cell, dict):
            raise ValueError(f"Valet observation is missing series cell: {cleaned}")
        raw_value = cell.get("v", "")
        if not isinstance(raw_value, str):
            raise ValueError("Valet value must be a string")
        parsed = _parse_float(raw_value)
        if parsed is None:
            quantity = make_missing(unit="percent", source_id=f"valet:{cleaned}")
        else:
            quantity = make_quantity(
                value=parsed,
                unit="percent",
                quality="observed",
                source_id=f"valet:{cleaned}",
            )
        results.append(
            ValetObservation(
                observation_date=observation_date,
                series_id=cleaned,
                label=upstream_label,
                quantity=quantity,
            )
        )
    return results


def fetch_valet_group(
    group_name: str,
    client: BaseClient,
    expected_labels: dict[str, str] | None = None,
) -> dict[str, list[ValetObservation]]:
    """Fetch a Valet group from its single group payload and assert each label once."""
    cleaned_group = _check_valet_id(group_name, "group_name")
    url = f"{VALET_BASE_URL}/observations/groups/{cleaned_group}/json"
    response = client.get(url)
    payload = parse_json_capped(response)
    if not isinstance(payload, dict):
        raise ValueError("Valet group response root must be an object")
    detail = payload.get("seriesDetail", {})
    if not isinstance(detail, dict):
        raise ValueError("Valet group response is missing seriesDetail")
    if expected_labels is not None:
        for series_id in expected_labels:
            _check_valet_id(series_id, "expected series_id")
        for series_id, expected in expected_labels.items():
            entry = detail.get(series_id)
            if not isinstance(entry, dict):
                raise ValueError(f"Valet group is missing expected series: {series_id}")
            actual = entry.get("label", "")
            actual_text = actual.strip() if isinstance(actual, str) else ""
            if actual_text != expected.strip():
                raise ValueError(
                    f"Valet label drift for {series_id}: expected {expected!r}, got {actual_text!r}"
                )
        target_ids = sorted(expected_labels.keys())
    else:
        for series_id in detail.keys():
            if isinstance(series_id, str):
                _check_valet_id(series_id, "upstream series_id")
        target_ids = sorted(detail.keys())
    if not target_ids:
        raise ValueError("Valet group response has no series")
    labels: dict[str, str] = {}
    for series_id in target_ids:
        entry = detail.get(series_id, {})
        upstream_label = ""
        if isinstance(entry, dict):
            raw_label = entry.get("label", "")
            if isinstance(raw_label, str):
                upstream_label = raw_label.strip()
        labels[series_id] = upstream_label
    observations = payload.get("observations")
    if "observations" not in payload:
        raise ValueError("Valet group response is missing its observations key")
    if not isinstance(observations, list):
        raise ValueError("Valet group observations must be a list")
    ensure_bounded_list(observations, "Valet group observations")
    results: dict[str, list[ValetObservation]] = {series_id: [] for series_id in target_ids}
    for item in observations:
        if not isinstance(item, dict):
            raise ValueError("Valet observation must be an object")
        date_text = item.get("d", "")
        if not isinstance(date_text, str) or not date_text.strip():
            raise ValueError("Valet observation is missing its date")
        observation_date = _parse_observation_date(date_text)
        for series_id in target_ids:
            cell = item.get(series_id, {})
            if not isinstance(cell, dict):
                raise ValueError(f"Valet observation is missing series cell: {series_id}")
            raw_value = cell.get("v", "")
            if not isinstance(raw_value, str):
                raise ValueError("Valet value must be a string")
            parsed = _parse_float(raw_value)
            if parsed is None:
                quantity = make_missing(unit="percent", source_id=f"valet:{series_id}")
            else:
                quantity = make_quantity(
                    value=parsed,
                    unit="percent",
                    quality="observed",
                    source_id=f"valet:{series_id}",
                )
            results[series_id].append(
                ValetObservation(
                    observation_date=observation_date,
                    series_id=series_id,
                    label=labels[series_id],
                    quantity=quantity,
                )
            )
    return results
