"""FRED client. An API key is required; a missing key yields missing quality."""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass

import httpx

from goc_rates.clients.base import (
    BaseClient,
    ensure_bounded_list,
    parse_json_capped,
)
from goc_rates.models import Quantity, make_missing, make_quantity

FRED_BASE_URL = "https://api.stlouisfed.org/fred"
FRED_API_KEY_ENV_VAR = "FRED_API_KEY"

FRED_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class FredObservation:
    """One FRED observation with its observation date."""

    observation_date: str
    series_id: str
    quantity: Quantity


def read_api_key(env: dict[str, str] | None = None) -> str | None:
    """Read the FRED API key from the environment, returning None when absent."""
    source = env if env is not None else os.environ
    raw = source.get(FRED_API_KEY_ENV_VAR, "")
    text = raw.strip() if isinstance(raw, str) else ""
    return text if text else None


def redact_api_key_text(text: str) -> str:
    """Redact an api_key query value so exceptions never print the key."""
    return re.sub(r"api_key=[^&\s'\"]*", "api_key=[REDACTED]", text)


def _parse_iso_param(value: str, field: str) -> str:
    """Parse a FRED date parameter and re-serialize it as ISO YYYY-MM-DD."""
    try:
        return dt.date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise ValueError(f"FRED {field} must be ISO YYYY-MM-DD: {value!r}") from None


def fetch_fred_series(
    series_id: str,
    client: BaseClient,
    api_key: str | None,
    observation_start: str | None = None,
    observation_end: str | None = None,
    realtime_start: str | None = None,
    realtime_end: str | None = None,
    limit: int | None = None,
    sort_order: str | None = None,
) -> list[FredObservation]:
    """Fetch a FRED series. A missing key returns one missing observation, no crash.

    Optional observation_start and observation_end bound the upstream
    window as strict ISO dates. Optional limit caps the returned rows and
    is bounded by MAX_HISTORY_OBS so the 254 print backtest stays within
    the 2000 row cap. Optional sort_order is asc or desc.
    """
    cleaned = series_id.strip()
    if not FRED_ID_PATTERN.match(cleaned):
        raise ValueError(f"series_id must match {FRED_ID_PATTERN.pattern}: {series_id!r}")
    if api_key is None or not api_key.strip():
        return [
            FredObservation(
                observation_date="",
                series_id=cleaned,
                quantity=make_missing(unit="percent", source_id=f"fred:{cleaned}"),
            )
        ]
    params: dict[str, str] = {
        "series_id": cleaned,
        "api_key": api_key.strip(),
        "file_type": "json",
    }
    if observation_start is not None:
        params["observation_start"] = _parse_iso_param(observation_start, "observation_start")
    if observation_end is not None:
        params["observation_end"] = _parse_iso_param(observation_end, "observation_end")
    if realtime_start is not None:
        params["realtime_start"] = _parse_iso_param(realtime_start, "realtime_start")
    if realtime_end is not None:
        params["realtime_end"] = _parse_iso_param(realtime_end, "realtime_end")
    if limit is not None:
        from goc_rates.limits import MAX_HISTORY_OBS

        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("FRED limit must be an int")
        if limit < 1 or limit > MAX_HISTORY_OBS:
            raise ValueError(f"FRED limit must be within 1 and {MAX_HISTORY_OBS}")
        params["limit"] = str(limit)
    if sort_order is not None:
        cleaned_sort = sort_order.strip().lower()
        if cleaned_sort not in ("asc", "desc"):
            raise ValueError("FRED sort_order must be asc or desc")
        params["sort_order"] = cleaned_sort
    try:
        response = client.get(f"{FRED_BASE_URL}/series/observations", params=params)
    except httpx.HTTPError as exc:
        raise httpx.HTTPError(redact_api_key_text(str(exc))) from None
    try:
        payload = parse_json_capped(response)
    except ValueError as exc:
        raise ValueError(redact_api_key_text(str(exc))) from None
    if not isinstance(payload, dict):
        raise ValueError("FRED response root must be an object")
    if "observations" not in payload:
        raise ValueError("FRED response is missing its observations key")
    observations = payload.get("observations")
    if not isinstance(observations, list):
        raise ValueError("FRED observations must be a list")
    ensure_bounded_list(observations, "FRED observations")
    results: list[FredObservation] = []
    for item in observations:
        if not isinstance(item, dict):
            raise ValueError("FRED observation must be an object")
        date_text = item.get("date", "")
        if not isinstance(date_text, str) or not date_text.strip():
            raise ValueError("FRED observation is missing its date")
        try:
            observation_date = dt.date.fromisoformat(date_text.strip()).isoformat()
        except ValueError:
            raise ValueError(
                f"FRED observation date is not ISO YYYY-MM-DD: {date_text!r}"
            ) from None
        raw_value = item.get("value", "")
        if not isinstance(raw_value, str):
            raise ValueError("FRED value must be a string")
        text = raw_value.strip()
        if text in ("", ".", "NA"):
            quantity = make_missing(unit="percent", source_id=f"fred:{cleaned}")
        else:
            quantity = make_quantity(
                value=float(text),
                unit="percent",
                quality="observed",
                source_id=f"fred:{cleaned}",
            )
        results.append(
            FredObservation(
                observation_date=observation_date,
                series_id=cleaned,
                quantity=quantity,
            )
        )
    return results
