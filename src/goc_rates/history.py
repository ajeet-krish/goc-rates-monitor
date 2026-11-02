"""Phase 7 backfill history builder: pure joint daily plus CPI rows.

The builder is pure with no I/O and no clock. The only time input is
the injected retrieved_utc string passed to the document builder.
Daily rows join the four Canadian benchmark tenors on joint complete
dates, compute slopes from the curve analytics, join per tenor US
spreads on the same date only with no forward fill, flag benchmark
switch windows and calendar gaps with the breaks helpers, and seal
each row with a canonical subdocument sha256 digest. CPI rows reuse
the weighted trim and median engine with trailing 12 month
compounding. The backfill document seals row counts and fails closed
when daily counts, CPI months, or canonical bytes exceed the limits.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from goc_rates.analytics import SLOPE_PAIRS, canada_us_spread_bp, slope_bp
from goc_rates.breaks import SwitchFeed, switch_in_window
from goc_rates.calendar import is_business_day, previous_business_day
from goc_rates.cpi.changes import compound_annual_percent, month_over_month_percent
from goc_rates.cpi.trim_median import ComponentRate, compute_trim_median
from goc_rates.cpi.weights import WeightVintage
from goc_rates.dates import parse_strict_iso_date
from goc_rates.limits import (
    MAX_BACKFILL_BYTES,
    MAX_BACKFILL_CPI_MONTHS,
    MAX_BACKFILL_DAILY_ROWS,
    MAX_CPI_COMPONENTS,
    MAX_CPI_MONTHS,
    MAX_HISTORY_OBS,
    MAX_YIELD,
    MIN_BACKFILL_DAILY_ROWS,
    MIN_YIELD,
)
from goc_rates.models import validate_source_id

BACKFILL_SCHEMA_VERSION: int = 1
BACKFILL_METHOD: str = "backfill_v1"
BACKFILL_SOURCE_ID: str = "derived:backfill_v1"

TENORS: tuple[str, ...] = ("2Y", "5Y", "10Y", "30Y")
SPREAD_STATUSES: tuple[str, ...] = ("ok", "partial", "missing")

SLOPE_KEY_BY_PAIR: dict[tuple[str, str], str] = {
    ("2Y", "5Y"): "2Y_5Y",
    ("2Y", "10Y"): "2Y_10Y",
    ("5Y", "30Y"): "5Y_30Y",
    ("10Y", "30Y"): "10Y_30Y",
}

_MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")

__all__ = [
    "BACKFILL_METHOD",
    "BACKFILL_SCHEMA_VERSION",
    "BACKFILL_SOURCE_ID",
    "SLOPE_KEY_BY_PAIR",
    "SPREAD_STATUSES",
    "TENORS",
    "build_backfill_document",
    "build_cpi_rows",
    "build_daily_rows",
]


def _canonical_text(payload: dict[str, Any]) -> str:
    """Serialize a mapping with sorted keys, indent 2, and strict floats."""
    return (
        json.dumps(
            payload,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _row_digest(row: dict[str, Any]) -> str:
    """Return the hex sha256 of the canonical row subdocument."""
    return hashlib.sha256(_canonical_text(row).encode("utf-8")).hexdigest()


def _check_month(text: str, name: str) -> str:
    """Return a YYYY-MM month string, else raise (strict, no whitespace)."""
    if not isinstance(text, str) or not _MONTH_PATTERN.match(text):
        raise ValueError(f"{name} must be YYYY-MM")
    return text


def _next_month(month: str) -> str:
    """Return the calendar month after a validated YYYY-MM month."""
    year = int(month[0:4])
    value = int(month[5:7])
    if value == 12:
        return f"{year + 1:04d}-01"
    return f"{year:04d}-{value + 1:02d}"


def _check_yield(value: float, name: str) -> float:
    """Validate a yield in percent and return it as float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be finite")
    if not MIN_YIELD <= result <= MAX_YIELD:
        raise ValueError(f"{name} must be within [{MIN_YIELD}, {MAX_YIELD}] percent")
    return result


def _clean_history(raw: Mapping[str, float], tenor: str) -> dict[str, float]:
    """Validate one tenor history mapping of strict ISO dates to yields."""
    if not isinstance(raw, Mapping):
        raise ValueError(f"history for {tenor} must be a mapping")
    if len(raw) > MAX_HISTORY_OBS:
        raise ValueError(f"history for {tenor} exceeds the {MAX_HISTORY_OBS} cap")
    cleaned: dict[str, float] = {}
    # Note: Mapping keys are unique by definition, so a duplicate history
    # date cannot survive dict construction upstream. Uniqueness within one
    # tenor therefore holds here, and cross tenor joint logic intersects keys.
    for date_text, value in raw.items():
        if not isinstance(date_text, str):
            raise ValueError(f"history dates for {tenor} must be strict ISO strings")
        parse_strict_iso_date(date_text)
        cleaned[date_text] = _check_yield(value, f"yield for {tenor} on {date_text}")
    return cleaned


def _asof_day(asof: str | dt.date) -> dt.date:
    """Parse the asof bound as a strict ISO date or pass through a date."""
    if isinstance(asof, dt.date) and not isinstance(asof, dt.datetime):
        return asof
    if not isinstance(asof, str):
        raise ValueError("asof must be a strict ISO string or date")
    return parse_strict_iso_date(asof)


def build_daily_rows(
    ca_histories: Mapping[str, Mapping[str, float]],
    us_histories: Mapping[str, Mapping[str, float]] | None,
    asof: str | dt.date,
    switch_feed: SwitchFeed,
) -> list[dict[str, Any]]:
    """Build joint complete daily rows up to asof with slopes and spreads.

    Canadian legs must cover exactly the 2Y, 5Y, 10Y, and 30Y tenors.
    Joint dates are the sorted intersection of the four Canadian legs
    filtered to dates on or before asof, with no filling. Slopes use
    the pinned slope pairs. Spreads join each tenor US leg on the same
    date only, so a missing US print yields null for that tenor and a
    status of ok, partial, or missing. Switch flags use switch_in_window
    per tenor with a row flag when any tenor switches, and calendar gaps
    compare the previous row date to the previous joint business day.
    Each row carries verified false, the closed backfill source, null
    snapshot and input digests, and a row_digest over the subdocument.
    """
    asof_day = _asof_day(asof)
    asof_text = asof_day.isoformat()
    if not isinstance(switch_feed, SwitchFeed):
        raise ValueError("switch_feed must be a SwitchFeed")
    if not isinstance(ca_histories, Mapping):
        raise ValueError("ca_histories must be a mapping")
    if set(ca_histories.keys()) != set(TENORS):
        raise ValueError(f"ca_histories tenor set must be {sorted(TENORS)}")
    cleaned_ca: dict[str, dict[str, float]] = {}
    for tenor in TENORS:
        cleaned_ca[tenor] = _clean_history(ca_histories[tenor], tenor)
    cleaned_us: dict[str, dict[str, float]] = {}
    if us_histories is not None:
        if not isinstance(us_histories, Mapping):
            raise ValueError("us_histories must be a mapping or None")
        for tenor, raw in us_histories.items():
            if tenor not in TENORS:
                raise ValueError(f"us_histories tenor must be one of {list(TENORS)}")
            if not isinstance(raw, Mapping):
                raise ValueError(f"us history for {tenor} must be a mapping")
            cleaned_us[tenor] = _clean_history(raw, f"US {tenor}")
    joint = sorted(
        {
            date
            for date in cleaned_ca[TENORS[0]]
            if date <= asof_text and all(date in cleaned_ca[tenor] for tenor in TENORS)
        }
    )
    if not joint:
        raise ValueError("no joint complete CA prints on or before asof")
    if len(joint) > MAX_BACKFILL_DAILY_ROWS:
        raise ValueError(
            f"joint daily count {len(joint)} exceeds the {MAX_BACKFILL_DAILY_ROWS} cap"
        )
    joint_days = [parse_strict_iso_date(date) for date in joint]
    rows: list[dict[str, Any]] = []
    for index, date_text in enumerate(joint):
        current_day = joint_days[index]
        yields_percent = {tenor: cleaned_ca[tenor][date_text] for tenor in TENORS}
        slopes_bp: dict[str, float] = {}
        for pair in SLOPE_PAIRS:
            key = SLOPE_KEY_BY_PAIR[pair]
            slopes_bp[key] = slope_bp(yields_percent[pair[0]], yields_percent[pair[1]])
        spreads_bp: dict[str, float | None] = {}
        for tenor in TENORS:
            us_value = cleaned_us.get(tenor, {}).get(date_text)
            if us_value is None:
                spreads_bp[tenor] = None
            else:
                spreads_bp[tenor] = canada_us_spread_bp(yields_percent[tenor], us_value)
        present = sum(1 for value in spreads_bp.values() if value is not None)
        if present == len(TENORS):
            spreads_status = "ok"
        elif present > 0:
            spreads_status = "partial"
        else:
            spreads_status = "missing"
        if index == 0:
            switch_by_tenor = {tenor: False for tenor in TENORS}
            switch_flag = False
            calendar_gap = not is_business_day(current_day, "joint")
        else:
            prev_day = joint_days[index - 1]
            switch_by_tenor = {
                tenor: switch_in_window(tenor, prev_day, current_day, switch_feed)
                for tenor in TENORS
            }
            switch_flag = any(switch_by_tenor.values())
            expected_prev = previous_business_day(current_day, "joint")
            calendar_gap = prev_day != expected_prev or not is_business_day(current_day, "joint")
        row: dict[str, Any] = {
            "date": date_text,
            "yields_percent": dict(yields_percent),
            "yields_unit": "percent",
            "slopes_bp": dict(slopes_bp),
            "slopes_unit": "basis_points",
            "spreads_bp": dict(spreads_bp),
            "spreads_unit": "basis_points",
            "spreads_status": spreads_status,
            "switch_in_window": switch_flag,
            "switch_by_tenor": dict(switch_by_tenor),
            "calendar_gap": calendar_gap,
            "verified": False,
            "source": validate_source_id(BACKFILL_SOURCE_ID),
            "snapshot_sha256": None,
            "input_digest_sha256": None,
        }
        row["row_digest"] = _row_digest(row)
        rows.append(row)
    return rows


def build_cpi_rows(
    monthly_indexes: Mapping[str, Sequence[tuple[str, float]]],
    weights: Mapping[str, float],
    vintage: WeightVintage,
) -> list[dict[str, Any]]:
    """Build monthly CPI backfill rows with trailing 12 month compounding.

    Component indexes must share one ascending unique consecutive YYYY-MM
    sequence with positive finite levels. Weights are fractions summing to one
    within 1e-6. Each month compounds the monthly trim and median with
    the shared trim median engine, and annual rates compound the
    trailing 12 monthly cores, leaving the first 11 months null for
    year over year. Production runs pass the 55 component registry.
    Each row carries explicit mom and yoy units plus a row digest.
    """
    if not isinstance(vintage, WeightVintage):
        raise ValueError("vintage must be a WeightVintage")
    if (
        isinstance(vintage.expenditure_year, bool)
        or not isinstance(vintage.expenditure_year, int)
        or not 1000 <= vintage.expenditure_year <= 9999
    ):
        raise ValueError("vintage expenditure_year must be a 4 digit year")
    _check_month(vintage.link_month, "vintage link_month")
    if not isinstance(vintage.provisional, bool):
        raise ValueError("vintage provisional must be a bool")
    if not isinstance(monthly_indexes, Mapping) or not monthly_indexes:
        raise ValueError("monthly_indexes must be a non empty mapping")
    if len(monthly_indexes) > MAX_CPI_COMPONENTS:
        raise ValueError(
            f"component count {len(monthly_indexes)} exceeds the {MAX_CPI_COMPONENTS} cap"
        )
    if not isinstance(weights, Mapping) or not weights:
        raise ValueError("weights must be a non empty mapping")
    if set(weights.keys()) != set(monthly_indexes.keys()):
        raise ValueError("weights must cover exactly the monthly index components")
    fractions: dict[str, float] = {}
    total = 0.0
    for component_id, weight in weights.items():
        if not isinstance(component_id, str) or not component_id.strip():
            raise ValueError("weight component ids must be non empty strings")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise ValueError(f"weight fraction for {component_id!r} must be numeric")
        value = float(weight)
        if value != value or value in (float("inf"), float("-inf")) or value <= 0.0:
            raise ValueError(f"weight fraction for {component_id!r} must be positive")
        fractions[component_id] = value
        total += value
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"weight fractions sum to {total:.9f}, expected 1.0 within 1e-6")
    series: dict[str, list[tuple[str, float]]] = {}
    shared_months: list[str] | None = None
    for component_id, raw_rows in monthly_indexes.items():
        if not isinstance(component_id, str) or not component_id.strip():
            raise ValueError("component ids must be non empty strings")
        rows = list(raw_rows)
        if len(rows) < 2:
            raise ValueError(f"component {component_id!r} needs monthly history")
        if len(rows) > MAX_CPI_MONTHS:
            raise ValueError(f"component {component_id!r} exceeds the {MAX_CPI_MONTHS} month cap")
        cleaned: list[tuple[str, float]] = []
        for month, index in rows:
            month_text = _check_month(month, f"month for {component_id!r}")
            if isinstance(index, bool) or not isinstance(index, (int, float)):
                raise ValueError(f"index for {component_id!r} must be numeric")
            index_value = float(index)
            if index_value != index_value or index_value in (
                float("inf"),
                float("-inf"),
            ):
                raise ValueError(f"index for {component_id!r} must be finite")
            if index_value <= 0.0:
                raise ValueError(f"index for {component_id!r} must be positive")
            cleaned.append((month_text, index_value))
        months_only = [month for month, _ in cleaned]
        if months_only != sorted(months_only):
            raise ValueError(f"months for {component_id!r} must be ascending")
        if len(set(months_only)) != len(months_only):
            raise ValueError(f"months for {component_id!r} must be unique")
        if shared_months is None:
            shared_months = months_only
        elif months_only != shared_months:
            raise ValueError("all components must share one month sequence")
        series[component_id] = cleaned
    assert shared_months is not None
    for position in range(1, len(shared_months)):
        if shared_months[position] != _next_month(shared_months[position - 1]):
            raise ValueError(
                "shared months must be consecutive calendar months, "
                f"gap between {shared_months[position - 1]!r} "
                f"and {shared_months[position]!r}"
            )
    component_ids = sorted(series.keys())
    mom_months = shared_months[1:]
    if len(mom_months) > MAX_BACKFILL_CPI_MONTHS:
        raise ValueError(
            f"cpi month count {len(mom_months)} exceeds the {MAX_BACKFILL_CPI_MONTHS} cap"
        )
    trim_moms: list[float] = []
    median_moms: list[float] = []
    median_components: list[str] = []
    for position in range(1, len(shared_months)):
        rates = [
            ComponentRate(
                component_id=component_id,
                monthly_rate_percent=month_over_month_percent(
                    series[component_id][position][1],
                    series[component_id][position - 1][1],
                ),
                weight_fraction=fractions[component_id],
            )
            for component_id in component_ids
        ]
        result = compute_trim_median(rates)
        trim_moms.append(result.trim_mom_percent)
        median_moms.append(result.median_mom_percent)
        median_components.append(result.median_component_id)
    trim_yoys: list[float | None] = [None] * len(mom_months)
    median_yoys: list[float | None] = [None] * len(mom_months)
    for end in range(11, len(mom_months)):
        trim_yoys[end] = compound_annual_percent(trim_moms[end - 11 : end + 1])
        median_yoys[end] = compound_annual_percent(median_moms[end - 11 : end + 1])
    rows: list[dict[str, Any]] = []
    for position, month in enumerate(mom_months):
        row = {
            "month": month,
            "trim_mom_percent": trim_moms[position],
            "median_mom_percent": median_moms[position],
            "median_component": median_components[position],
            "trim_yoy_percent": trim_yoys[position],
            "median_yoy_percent": median_yoys[position],
            "mom_unit": "percent_per_month",
            "yoy_unit": "percent",
            "verified": False,
            "source": validate_source_id(BACKFILL_SOURCE_ID),
        }
        row["row_digest"] = _row_digest(row)
        rows.append(row)
    return rows


def _require_provenance(provenance: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the backfill provenance mapping and return a copy."""
    if not isinstance(provenance, Mapping) or not provenance:
        raise ValueError("provenance must be a non empty mapping")
    cleaned: dict[str, Any] = {}
    for key, entry in provenance.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("provenance keys must be non empty strings")
        if not isinstance(entry, Mapping):
            raise ValueError(f"provenance entry for {key!r} must be a mapping")
        for field in ("source_url", "retrieved_utc", "vintage"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"provenance {key!r} needs a non empty {field}")
        cleaned[key] = dict(entry)
    return cleaned


def _verify_row_digest(row: Mapping[str, Any], label: str) -> dict[str, Any]:
    """Recompute one row digest and return a copy, failing closed on drift."""
    if not isinstance(row, Mapping):
        raise ValueError(f"{label} rows must be mappings")
    stored = row.get("row_digest")
    if not isinstance(stored, str) or not stored.strip():
        raise ValueError(f"{label} row is missing its row_digest")
    body = {key: value for key, value in row.items() if key != "row_digest"}
    expected = _row_digest(body)
    if expected != stored.strip():
        raise ValueError(f"{label} row digest mismatch for {row.get('date', row.get('month'))!r}")
    return dict(row)


def build_backfill_document(
    asof: str | dt.date,
    daily_rows: Sequence[Mapping[str, Any]],
    cpi_rows: Sequence[Mapping[str, Any]],
    provenance: Mapping[str, Any],
    exclusions: Sequence[Mapping[str, Any]],
    retrieved_utc: str,
) -> dict[str, Any]:
    """Assemble the backfill document with counts and byte cap enforcement.

    Daily rows must count between the backfill minimum and maximum with
    ascending dates on or before asof and recomputing digests. CPI rows
    follow the degraded zero CPI contract: either an empty list meaning
    degraded CPI with cpi_count zero and the same sealed shape, or one to
    sixty ascending unique consecutive months on or before the asof month
    with recomputing digests. Provenance must carry non empty source url, retrieved, and
    vintage per entry. Exclusions must be a list. The injected
    retrieved_utc stamps metadata with no clock read, and the canonical
    document must fit within the backfill byte cap.
    """
    asof_day = _asof_day(asof)
    asof_text = asof_day.isoformat()
    if not isinstance(retrieved_utc, str) or not retrieved_utc.strip():
        raise ValueError("retrieved_utc must be a non empty string")
    cleaned_provenance = _require_provenance(provenance)
    if not isinstance(exclusions, Sequence) or isinstance(exclusions, (str, bytes)):
        raise ValueError("exclusions must be a list")
    cleaned_exclusions = list(exclusions)
    for entry in cleaned_exclusions:
        if not isinstance(entry, Mapping):
            raise ValueError("exclusion rows must be mappings")
    daily = list(daily_rows)
    if len(daily) < MIN_BACKFILL_DAILY_ROWS:
        raise ValueError(
            f"daily row count {len(daily)} is below the {MIN_BACKFILL_DAILY_ROWS} minimum"
        )
    if len(daily) > MAX_BACKFILL_DAILY_ROWS:
        raise ValueError(f"daily row count {len(daily)} exceeds the {MAX_BACKFILL_DAILY_ROWS} cap")
    verified_daily: list[dict[str, Any]] = []
    seen_dates: list[str] = []
    for row in daily:
        copied = _verify_row_digest(row, "daily")
        date_text = copied.get("date")
        if not isinstance(date_text, str):
            raise ValueError("daily rows must carry a date string")
        parse_strict_iso_date(date_text)
        if date_text > asof_text:
            raise ValueError(f"daily date {date_text!r} exceeds asof {asof_text!r}")
        seen_dates.append(date_text)
        verified_daily.append(copied)
    if seen_dates != sorted(seen_dates):
        raise ValueError("daily rows must be ascending")
    if len(set(seen_dates)) != len(seen_dates):
        raise ValueError("daily rows must hold unique dates")
    cpi = list(cpi_rows)
    if len(cpi) > MAX_BACKFILL_CPI_MONTHS:
        raise ValueError(f"cpi row count {len(cpi)} exceeds the {MAX_BACKFILL_CPI_MONTHS} cap")
    asof_month = asof_text[:7]
    verified_cpi: list[dict[str, Any]] = []
    seen_months: list[str] = []
    for row in cpi:
        copied = _verify_row_digest(row, "cpi")
        month_text = copied.get("month")
        if not isinstance(month_text, str):
            raise ValueError("cpi rows must carry a month string")
        _check_month(month_text, "cpi month")
        if month_text > asof_month:
            raise ValueError(f"cpi month {month_text!r} exceeds asof {asof_month!r}")
        seen_months.append(month_text)
        verified_cpi.append(copied)
    if seen_months != sorted(seen_months):
        raise ValueError("cpi rows must be ascending")
    if len(set(seen_months)) != len(seen_months):
        raise ValueError("cpi rows must hold unique months")
    for position in range(1, len(seen_months)):
        if seen_months[position] != _next_month(seen_months[position - 1]):
            raise ValueError(
                "cpi rows must hold consecutive calendar months, "
                f"gap between {seen_months[position - 1]!r} "
                f"and {seen_months[position]!r}"
            )
    document: dict[str, Any] = {
        "metadata": {
            "asof": asof_text,
            "schema_version": BACKFILL_SCHEMA_VERSION,
            "method": BACKFILL_METHOD,
            "retrieved_utc": retrieved_utc.strip(),
            "daily_count": len(verified_daily),
            "daily_count_unit": "count",
            "cpi_count": len(verified_cpi),
            "cpi_count_unit": "count",
        },
        "daily": verified_daily,
        "cpi": verified_cpi,
        "provenance": cleaned_provenance,
        "exclusions": cleaned_exclusions,
        "retrieved_utc": retrieved_utc.strip(),
    }
    payload_bytes = len(_canonical_text(document).encode("utf-8"))
    if payload_bytes > MAX_BACKFILL_BYTES:
        raise ValueError(
            f"backfill document of {payload_bytes} bytes exceeds the {MAX_BACKFILL_BYTES} byte cap"
        )
    return document
