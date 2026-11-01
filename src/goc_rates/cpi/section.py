"""Inflation section builder: experimental trim and median with provenance."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from goc_rates.config import CpiConfig
from goc_rates.cpi.basket_map import check_basket_agreement
from goc_rates.cpi.bulk import (
    EXPECTED_BULK_PRODUCT_IDS,
    STATCAN_WDS_BASE_URL,
    BulkTable,
    bulk_tables_for_snapshot,
    extract_basket_weights,
    extract_component_months,
)
from goc_rates.cpi.changes import (
    compound_annual_percent,
    month_over_month_percent,
    year_over_year_percent,
)
from goc_rates.cpi.components import ComponentSpec, specs_from_config
from goc_rates.cpi.decomposition import decompose_month, total_contribution_pp
from goc_rates.cpi.trim_median import TRIM_METHOD, ComponentRate, compute_trim_median
from goc_rates.cpi.validation import (
    MAE_GATE_PP,
    MIN_VALIDATION_MONTHS,
    validate_replica,
    validation_flag,
)
from goc_rates.cpi.weights import WeightVintage, normalize_weights, vintage_from_config
from goc_rates.limits import MAX_CPI_COMPONENTS, MAX_CPI_MONTHS
from goc_rates.models import make_quantity

INFLATION_LABEL = "experimental"
DERIVED_SOURCE = "derived:cpi_trim_median"

HISTORY_MONTHS = 12
INDEX_MONTHS = 2

_MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def _check_month(text: str, name: str) -> str:
    """Return a YYYY-MM month string, else raise."""
    if not isinstance(text, str) or not _MONTH_PATTERN.match(text.strip()):
        raise ValueError(f"{name} must be YYYY-MM")
    return text.strip()


def build_inflation_section(
    *,
    specs: Sequence[ComponentSpec],
    weights: Mapping[str, float],
    monthly_indexes: Mapping[str, Sequence[tuple[str, float]]],
    published_trim_yoy: Sequence[float],
    published_median_yoy: Sequence[float],
    published_months: Sequence[str],
    bulk_tables: Mapping[str, BulkTable],
    vintage: WeightVintage,
) -> dict[str, Any]:
    """Build the experimental inflation section with trim, median, and validation.

    Monthly SA indexes per component drive replica trim and median mom
    rates; annual rates compound the trailing 12 monthly cores. Published
    YoY series validate the replica over a trailing window of at least 24
    months, flagging gate breaches without blocking. The section stores
    two months of chained index levels, twelve months of history, and the
    bulk zip hashes for audit.
    """
    items = list(specs)
    if not items:
        raise ValueError("need at least one component spec")
    if len(items) > MAX_CPI_COMPONENTS:
        raise ValueError(f"component count {len(items)} exceeds the {MAX_CPI_COMPONENTS} cap")
    spec_ids = [spec.component_id for spec in items]
    if set(weights.keys()) != set(spec_ids):
        raise ValueError("weights must cover exactly the spec components")
    if set(monthly_indexes.keys()) != set(spec_ids):
        raise ValueError("monthly indexes must cover exactly the spec components")
    for component_id, fraction in weights.items():
        if isinstance(fraction, bool) or not isinstance(fraction, (int, float)):
            raise ValueError(f"weight fraction for {component_id!r} must be numeric")
        value = float(fraction)
        if value != value or value in (float("inf"), float("-inf")) or value <= 0.0:
            raise ValueError(f"weight fraction for {component_id!r} must be positive")
    shared_months: list[str] | None = None
    series: dict[str, list[tuple[str, float]]] = {}
    for spec in items:
        raw = list(monthly_indexes[spec.component_id])
        if len(raw) < 2:
            raise ValueError(f"component {spec.component_id!r} needs monthly history")
        if len(raw) > MAX_CPI_MONTHS:
            raise ValueError(
                f"component {spec.component_id!r} exceeds the {MAX_CPI_MONTHS} month cap"
            )
        cleaned: list[tuple[str, float]] = []
        for month, index in raw:
            month_text = _check_month(month, f"month for {spec.component_id!r}")
            if isinstance(index, bool) or not isinstance(index, (int, float)):
                raise ValueError(f"index for {spec.component_id!r} must be numeric")
            index_value = float(index)
            if (
                index_value != index_value
                or index_value in (float("inf"), float("-inf"))
                or index_value <= 0.0
            ):
                raise ValueError(f"index for {spec.component_id!r} must be positive")
            cleaned.append((month_text, index_value))
        months_only = [month for month, _ in cleaned]
        if months_only != sorted(months_only):
            raise ValueError(f"months for {spec.component_id!r} must be ascending")
        if len(set(months_only)) != len(months_only):
            raise ValueError(f"months for {spec.component_id!r} must be unique")
        if shared_months is None:
            shared_months = months_only
        elif months_only != shared_months:
            raise ValueError("all components must share one month sequence")
        series[spec.component_id] = cleaned
    assert shared_months is not None
    if len(shared_months) < MIN_VALIDATION_MONTHS + 12:
        raise ValueError(
            f"need at least {MIN_VALIDATION_MONTHS + 12} months of indexes, "
            f"got {len(shared_months)}"
        )
    mom_months = shared_months[1:]
    mom_by_month: dict[str, dict[str, float]] = {}
    for position in range(1, len(shared_months)):
        month = shared_months[position]
        rates: dict[str, float] = {}
        for spec in items:
            rows = series[spec.component_id]
            rates[spec.component_id] = month_over_month_percent(
                rows[position][1], rows[position - 1][1]
            )
        mom_by_month[month] = rates
    trim_moms: list[float] = []
    median_moms: list[float] = []
    median_components: list[str] = []
    for month in mom_months:
        rates = mom_by_month[month]
        result = compute_trim_median(
            [
                ComponentRate(
                    component_id=spec.component_id,
                    monthly_rate_percent=rates[spec.component_id],
                    weight_fraction=float(weights[spec.component_id]),
                )
                for spec in items
            ]
        )
        trim_moms.append(result.trim_mom_percent)
        median_moms.append(result.median_mom_percent)
        median_components.append(result.median_component_id)
    trim_yoys = _trailing_compounded(trim_moms)
    median_yoys = _trailing_compounded(median_moms)
    yoy_months = mom_months[11:]
    pub_months = [_check_month(month, "published month") for month in published_months]
    pub_trim = _check_float_list(published_trim_yoy, "published_trim_yoy")
    pub_median = _check_float_list(published_median_yoy, "published_median_yoy")
    if not pub_months or not (len(pub_months) == len(pub_trim) == len(pub_median)):
        raise ValueError("published months and YoY series must align and be non empty")
    if len(pub_months) < MIN_VALIDATION_MONTHS:
        raise ValueError(
            f"published history needs at least {MIN_VALIDATION_MONTHS} months, "
            f"got {len(pub_months)}"
        )
    if pub_months != yoy_months[-len(pub_months) :]:
        raise ValueError("published months must match the trailing replica months")
    replica_trim = trim_yoys[-len(pub_months) :]
    replica_median = median_yoys[-len(pub_months) :]
    trim_check = validate_replica(replica_trim, pub_trim)
    median_check = validate_replica(replica_median, pub_median)
    exceeds = bool(trim_check.exceeds_gate or median_check.exceeds_gate)
    latest_month = shared_months[-1]
    latest_rates = mom_by_month[latest_month]
    weights_percent = {
        spec.component_id: float(weights[spec.component_id]) * 100.0 for spec in items
    }
    contributions = decompose_month(latest_rates, weights_percent)
    contribution_total = total_contribution_pp(contributions)
    latest_trim = compute_trim_median(
        [
            ComponentRate(
                component_id=spec.component_id,
                monthly_rate_percent=latest_rates[spec.component_id],
                weight_fraction=float(weights[spec.component_id]),
            )
            for spec in items
        ]
    )
    chained_trim = _chain_levels(trim_moms)
    chained_median = _chain_levels(median_moms)
    index_months = mom_months[-INDEX_MONTHS:]
    history_months = mom_months[-HISTORY_MONTHS:]
    history_rows: list[dict[str, Any]] = []
    for month in history_months:
        position = mom_months.index(month)
        row: dict[str, Any] = {
            "month": month,
            "trim_mom_percent": trim_moms[position],
            "median_mom_percent": median_moms[position],
            "median_component": median_components[position],
        }
        if position >= 11:
            yoy_position = position - 11
            row["trim_yoy_percent"] = trim_yoys[yoy_position]
            row["median_yoy_percent"] = median_yoys[yoy_position]
        else:
            row["trim_yoy_percent"] = None
            row["median_yoy_percent"] = None
        history_rows.append(row)
    residual_trim = [
        replica - published for replica, published in zip(replica_trim, pub_trim, strict=True)
    ]
    residual_median = [
        replica - published for replica, published in zip(replica_median, pub_median, strict=True)
    ]
    section: dict[str, Any] = {
        "label": INFLATION_LABEL,
        "is_official": False,
        "publisher_series": "statcan",
        "experimental_series": DERIVED_SOURCE,
        "method": TRIM_METHOD,
        "owns_seasonal_adjustment": False,
        "seasonally_adjusted_source": "statcan",
        "component_count": len(items),
        "weight_vintage": {
            "expenditure_year": vintage.expenditure_year,
            "link_month": vintage.link_month,
            "provisional": vintage.provisional,
        },
        "reference_month": latest_month,
        "indexes": {
            "months": list(index_months),
            "trim": [
                make_quantity(
                    value=float(chained_trim[mom_months.index(month)]),
                    unit="index_points",
                    quality="observed",
                    source_id=DERIVED_SOURCE,
                )
                for month in index_months
            ],
            "median": [
                make_quantity(
                    value=float(chained_median[mom_months.index(month)]),
                    unit="index_points",
                    quality="observed",
                    source_id=DERIVED_SOURCE,
                )
                for month in index_months
            ],
        },
        "latest": {
            "month": latest_month,
            "trim_mom": make_quantity(
                value=latest_trim.trim_mom_percent,
                unit="percent_per_month",
                quality="observed",
                source_id=DERIVED_SOURCE,
            ),
            "median_mom": make_quantity(
                value=latest_trim.median_mom_percent,
                unit="percent_per_month",
                quality="observed",
                source_id=DERIVED_SOURCE,
            ),
            "trim_yoy": make_quantity(
                value=trim_yoys[-1],
                unit="percent",
                quality="observed",
                source_id=DERIVED_SOURCE,
            ),
            "median_yoy": make_quantity(
                value=median_yoys[-1],
                unit="percent",
                quality="observed",
                source_id=DERIVED_SOURCE,
            ),
            "median_component": latest_trim.median_component_id,
        },
        "history": history_rows,
        "history_months": HISTORY_MONTHS,
        "contributions": [
            {
                "component_id": item.component_id,
                "monthly_rate_percent": item.monthly_rate_percent,
                "weight_percent": item.weight_percent,
                "contribution_pp": item.contribution_pp,
            }
            for item in contributions
        ],
        "total_contribution_pp": contribution_total,
        "headline_mom": make_quantity(
            value=contribution_total,
            unit="percent_per_month",
            quality="observed",
            source_id=DERIVED_SOURCE,
        ),
        "kept_weight_fraction": latest_trim.kept_weight_fraction,
        "excluded_weight_fraction": latest_trim.excluded_weight_fraction,
        "validation": {
            "months": trim_check.months,
            "gate_pp": MAE_GATE_PP,
            "trim": {
                "mae_pp": trim_check.mae_pp,
                "bias_pp": trim_check.bias_pp,
                "max_abs_resid_pp": trim_check.max_abs_resid_pp,
            },
            "median": {
                "mae_pp": median_check.mae_pp,
                "bias_pp": median_check.bias_pp,
                "max_abs_resid_pp": median_check.max_abs_resid_pp,
            },
            "exceeds_gate": exceeds,
            "flag": validation_flag(exceeds),
            "note": (
                "replica validated against published vintages; "
                "a breached gate flags for explanation and never blocks"
            ),
            "published_months": list(pub_months),
            "residuals_trim_pp": residual_trim,
            "residuals_median_pp": residual_median,
        },
        "bulk": bulk_tables_for_snapshot(bulk_tables),
    }
    return section


def _trailing_compounded(monthly: list[float]) -> list[float]:
    """Compound trailing 12 month windows into YoY values."""
    yoys: list[float] = []
    for end in range(11, len(monthly)):
        window = monthly[end - 11 : end + 1]
        yoys.append(compound_annual_percent(window))
    return yoys


def _chain_levels(monthly: list[float]) -> list[float]:
    """Chain monthly rates from 100 into index levels."""
    levels: list[float] = []
    level = 100.0
    for rate in monthly:
        level *= 1.0 + float(rate) / 100.0
        if level != level or level in (float("inf"), float("-inf")) or level <= 0.0:
            raise ValueError("chained index level overflowed")
        levels.append(level)
    return levels


def _levels_to_yoy(levels: list[tuple[str, float]], name: str) -> dict[str, float]:
    """Convert ascending published index levels into YoY percent by month."""
    if len(levels) < MIN_VALIDATION_MONTHS + 12:
        raise ValueError(
            f"published {name} levels need at least "
            f"{MIN_VALIDATION_MONTHS + 12} months, got {len(levels)}"
        )
    result: dict[str, float] = {}
    for position in range(12, len(levels)):
        month = levels[position][0]
        result[month] = year_over_year_percent(levels[position][1], levels[position - 12][1])
    return result


def _check_float_list(values: Sequence[float], name: str) -> list[float]:
    """Return finite floats from a sequence, else raise."""
    cleaned = list(values)
    if not cleaned:
        raise ValueError(f"{name} must contain at least one value")
    result: list[float] = []
    for value in cleaned:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} values must be numeric")
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"{name} values must be finite")
        result.append(number)
    return result


def cpi_provenance_entry(
    bulk_tables: Mapping[str, BulkTable],
    vintage: WeightVintage,
    retrieved_utc: str,
    monthly_product: str = "cpi_monthly",
) -> dict[str, Any]:
    """Build the statcan_cpi provenance entry with vintage and short hashes."""
    if monthly_product not in bulk_tables:
        raise ValueError(f"bulk tables are missing {monthly_product!r}")
    product_id = bulk_tables[monthly_product].product_id
    if not isinstance(retrieved_utc, str) or not retrieved_utc.strip():
        raise ValueError("retrieved_utc must be a non empty string")
    sha12 = {name: table.zip_sha256.strip().lower()[:12] for name, table in bulk_tables.items()}
    return {
        "source_url": f"{STATCAN_WDS_BASE_URL}/getFullTableDownloadCSV/{product_id}/en",
        "retrieved_utc": retrieved_utc.strip(),
        "vintage": vintage.link_month,
        "weight_vintage": (
            f"expenditure {vintage.expenditure_year}, link month {vintage.link_month}, "
            f"provisional {str(vintage.provisional).lower()}"
        ),
        "bulk_sha12": sha12,
    }


def build_inflation_section_from_bulk(
    config: CpiConfig,
    bulk_tables: Mapping[str, BulkTable],
    retrieved_utc: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the inflation section plus provenance from fetched bulk tables.

    Component SA indexes merge across the monthly and core bulk zips,
    published trim and median index levels come from the core zip via the
    registry index pins (converted to YoY with year_over_year_percent),
    and basket agreement is validated through check_basket_agreement over
    the 18100007 product groups with per component tolerances. The direct
    index vector lookup is retired: basket vectors never equal registry
    index vectors. Bulk unit metadata is asserted before any derive step.
    """
    specs = specs_from_config(config)
    weights = normalize_weights(specs)
    vintage = vintage_from_config(config)
    for name, expected_id in EXPECTED_BULK_PRODUCT_IDS.items():
        if name not in bulk_tables:
            raise ValueError(f"bulk tables are missing {name!r}")
        if bulk_tables[name].product_id != expected_id:
            raise ValueError(
                f"bulk table {name!r} product id {bulk_tables[name].product_id} "
                f"must pin {expected_id}"
            )
    basket = extract_basket_weights(
        bulk_tables["basket_weights"].zip_bytes,
        expenditure_year=vintage.expenditure_year,
        link_month=vintage.link_month,
    )
    check_basket_agreement(config, basket)
    wanted = {spec.vector_id: spec.component_id for spec in specs}
    merged: dict[str, dict[str, float]] = {}
    for key in ("cpi_monthly", "core_statistics"):
        table = bulk_tables[key]
        by_vector = extract_component_months(table.zip_bytes, set(wanted.keys()))
        for vector, months in by_vector.items():
            slot = merged.setdefault(vector, {})
            for month, index in months:
                slot.setdefault(month, index)
    missing = sorted(vector for vector in wanted if vector not in merged)
    if missing:
        raise ValueError(f"bulk zips are missing registry vectors: {missing}")
    monthly_indexes: dict[str, list[tuple[str, float]]] = {}
    month_sets = {vector: set(months.keys()) for vector, months in merged.items()}
    shared = set.intersection(*month_sets.values())
    if len(shared) < MIN_VALIDATION_MONTHS + 12:
        raise ValueError("bulk history is too short for the 24 month validation window")
    use_months = sorted(shared)
    for vector, component_id in wanted.items():
        monthly_indexes[component_id] = [(month, merged[vector][month]) for month in use_months]
    published = config.published
    trim_vector = published.get("trim_index_vector_id", "")
    median_vector = published.get("median_index_vector_id", "")
    if not trim_vector or not median_vector:
        raise ValueError("registry published index pins must name trim and median vectors")
    core_bytes = bulk_tables["core_statistics"].zip_bytes
    published_series = extract_component_months(core_bytes, [trim_vector, median_vector])
    trim_yoy_by_month = _levels_to_yoy(published_series[trim_vector], "trim")
    median_yoy_by_month = _levels_to_yoy(published_series[median_vector], "median")
    replica_tail = set(use_months[12:])
    aligned = sorted(
        month
        for month in trim_yoy_by_month
        if month in median_yoy_by_month and month in replica_tail
    )
    if len(aligned) < MIN_VALIDATION_MONTHS:
        raise ValueError("published history is too short for the 24 month window")
    aligned = aligned[-36:]
    section = build_inflation_section(
        specs=list(specs),
        weights=weights,
        monthly_indexes=monthly_indexes,
        published_trim_yoy=[trim_yoy_by_month[month] for month in aligned],
        published_median_yoy=[median_yoy_by_month[month] for month in aligned],
        published_months=aligned,
        bulk_tables=dict(bulk_tables),
        vintage=vintage,
    )
    provenance = cpi_provenance_entry(dict(bulk_tables), vintage, retrieved_utc)
    return section, provenance
