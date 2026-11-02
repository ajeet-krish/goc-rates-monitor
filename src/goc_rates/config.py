"""Benchmark map loading with label assertion support."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from goc_rates.dates import parse_strict_iso_date
from goc_rates.limits import MAX_YIELD

EXPECTED_SCHEMA_VERSION = 2
EXPECTED_BENCHMARK_TENORS: tuple[str, ...] = ("2Y", "5Y", "10Y", "30Y")

SERIES_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class BenchmarkIssue:
    """One benchmark issue with maturity, coupon, and frequency."""

    maturity_date: dt.date
    coupon_percent: float
    payments_per_year: int = 2


@dataclass(frozen=True)
class BenchmarkEntry:
    """One benchmark tenor with Valet and FRED identifiers."""

    tenor: str
    valet_series_id: str
    valet_label: str
    fred_series_id: str
    comparator_label: str
    legacy_v_code: str | None
    issue: BenchmarkIssue


@dataclass(frozen=True)
class BenchmarkMap:
    """Parsed benchmark map with schema version and entries."""

    schema_version: int
    benchmarks: dict[str, BenchmarkEntry]
    statcan_indicators: list[str]


def _load_benchmark_issue(tenor: str, raw: object) -> BenchmarkIssue:
    """Validate one benchmark issue mapping, failing closed on drift."""
    if not isinstance(raw, dict):
        raise ValueError(f"benchmark issue for {tenor!r} must be a mapping")
    maturity_raw = raw.get("maturity_date")
    if isinstance(maturity_raw, dt.datetime):
        raise ValueError(f"benchmark issue for {tenor!r} needs a maturity_date string")
    if isinstance(maturity_raw, dt.date):
        maturity = maturity_raw
    elif isinstance(maturity_raw, str):
        try:
            maturity = parse_strict_iso_date(maturity_raw)
        except ValueError as exc:
            raise ValueError(
                f"benchmark issue for {tenor!r} has an invalid maturity_date: {exc}"
            ) from None
    else:
        raise ValueError(f"benchmark issue for {tenor!r} needs a maturity_date string")
    coupon_raw = raw.get("coupon_percent")
    if isinstance(coupon_raw, bool) or not isinstance(coupon_raw, (int, float)):
        raise ValueError(f"benchmark issue for {tenor!r} needs a numeric coupon_percent")
    coupon = float(coupon_raw)
    if coupon != coupon or coupon in (float("inf"), float("-inf")):
        raise ValueError(f"benchmark issue for {tenor!r} coupon_percent must be finite")
    if coupon < 0.0 or coupon > MAX_YIELD:
        raise ValueError(
            f"benchmark issue for {tenor!r} coupon_percent "
            f"{coupon!r} is outside the supported range "
            f"[0.0, {MAX_YIELD}] (unit: percent)"
        )
    frequency_raw = raw.get("payments_per_year")
    if isinstance(frequency_raw, bool) or not isinstance(frequency_raw, int):
        raise ValueError(f"benchmark issue for {tenor!r} needs an integer payments_per_year")
    if frequency_raw != 2:
        raise ValueError(
            f"benchmark issue for {tenor!r} must be semiannual "
            f"(payments_per_year 2), got {frequency_raw!r}"
        )
    return BenchmarkIssue(
        maturity_date=maturity,
        coupon_percent=coupon,
        payments_per_year=frequency_raw,
    )


def load_benchmark_map(path: str | Path) -> BenchmarkMap:
    """Load and validate the benchmark map, failing closed on drift."""
    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError(f"benchmark map not found: {file_path}")
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("benchmark map root must be a mapping")
    schema_version = raw.get("schema_version")
    if schema_version != EXPECTED_SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {schema_version!r}")
    raw_benchmarks = raw.get("benchmarks")
    if not isinstance(raw_benchmarks, dict) or not raw_benchmarks:
        raise ValueError("benchmark map needs a non empty benchmarks mapping")
    benchmarks: dict[str, BenchmarkEntry] = {}
    for tenor, item in raw_benchmarks.items():
        if not isinstance(item, dict):
            raise ValueError(f"benchmark entry for {tenor!r} must be a mapping")
        for key in ("valet_series_id", "fred_series_id"):
            if key not in item or not isinstance(item[key], str) or not item[key].strip():
                raise ValueError(f"benchmark entry for {tenor!r} needs a non empty {key}")
            if not SERIES_ID_PATTERN.match(item[key].strip()):
                raise ValueError(
                    f"benchmark entry for {tenor!r} has an invalid {key}: {item[key]!r}"
                )
        for key in ("valet_label", "comparator_label"):
            if key not in item or not isinstance(item[key], str) or not item[key].strip():
                raise ValueError(f"benchmark entry for {tenor!r} needs a non empty {key}")
        legacy = item.get("legacy_v_code")
        if legacy is not None and not isinstance(legacy, str):
            raise ValueError(f"legacy_v_code for {tenor!r} must be a string or null")
        issue = _load_benchmark_issue(str(tenor), item.get("issue"))
        benchmarks[str(tenor)] = BenchmarkEntry(
            tenor=str(tenor),
            valet_series_id=item["valet_series_id"].strip(),
            valet_label=item["valet_label"].strip(),
            fred_series_id=item["fred_series_id"].strip(),
            comparator_label=item["comparator_label"].strip(),
            legacy_v_code=legacy.strip() if isinstance(legacy, str) and legacy.strip() else None,
            issue=issue,
        )
    if set(benchmarks.keys()) != set(EXPECTED_BENCHMARK_TENORS):
        raise ValueError(
            f"benchmark tenor set must be {sorted(EXPECTED_BENCHMARK_TENORS)}, "
            f"got {sorted(benchmarks.keys())}"
        )
    raw_indicators = raw.get("statcan_indicators", [])
    if not isinstance(raw_indicators, list):
        raise ValueError("statcan_indicators must be a list")
    indicators: list[str] = []
    for indicator in raw_indicators:
        if not isinstance(indicator, str) or not indicator.strip():
            raise ValueError("statcan_indicators entries must be non empty strings")
        cleaned_indicator = indicator.strip()
        try:
            int(cleaned_indicator)
        except ValueError:
            raise ValueError(
                f"statcan_indicators entries must be integer vector ids: {indicator!r}"
            ) from None
        indicators.append(cleaned_indicator)
    return BenchmarkMap(
        schema_version=int(schema_version),
        benchmarks=benchmarks,
        statcan_indicators=indicators,
    )


CPI_SCHEMA_VERSION = 2

CPI_LINK_MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
CPI_PRODUCT_ID_PATTERN = re.compile(r"^[1-9][0-9]{7}$")
CPI_VECTOR_ID_PATTERN = re.compile(r"^[0-9]{8}$")
CPI_BASKET_VECTOR_PATTERN = re.compile(r"^[0-9]{8}(?:[0-9]{2})?$")

EXPECTED_CPI_PRODUCT_IDS: dict[str, int] = {
    "cpi_monthly": 18100004,
    "core_statistics": 18100256,
    "basket_weights": 18100007,
}

EXPECTED_PUBLISHED_KEYS: tuple[str, str] = (
    "trim_index_vector_id",
    "median_index_vector_id",
)

BASKET_EXCLUSION_REASONS: frozenset[str] = frozenset({"aggregate", "special_aggregate"})


@dataclass(frozen=True)
class CpiWeightVintage:
    """Pinned basket weight vintage for the CPI engine."""

    expenditure_year: int
    link_month: str
    provisional: bool


@dataclass(frozen=True)
class CpiComponent:
    """One registry pinned CPI component with its basket weight."""

    component_id: str
    label: str
    vector_id: str
    weight_percent: float
    seasonally_adjusted: bool
    basket_product_groups: tuple[str, ...]
    basket_vector_ids: tuple[str, ...]


@dataclass(frozen=True)
class BasketExclusion:
    """One excluded basket product: aggregate or special aggregate."""

    product_group: str
    vector_id: str
    reason: str


@dataclass(frozen=True)
class CpiConfig:
    """Parsed CPI component registry with weight vintage and products."""

    schema_version: int
    weight_vintage: CpiWeightVintage
    product_ids: dict[str, int]
    components: tuple[CpiComponent, ...]
    published: dict[str, str]
    basket_exclusions: tuple[BasketExclusion, ...]


def load_cpi_config(path: str | Path) -> CpiConfig:
    """Load and validate the CPI component registry, failing closed on drift."""
    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError(f"CPI component registry not found: {file_path}")
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("CPI registry root must be a mapping")
    schema_version = raw.get("schema_version")
    if schema_version != CPI_SCHEMA_VERSION:
        raise ValueError(f"unsupported CPI schema_version: {schema_version!r}")
    vintage_raw = raw.get("weight_vintage")
    if not isinstance(vintage_raw, dict):
        raise ValueError("CPI registry needs a weight_vintage mapping")
    expenditure_year = vintage_raw.get("expenditure_year")
    if (
        isinstance(expenditure_year, bool)
        or not isinstance(expenditure_year, int)
        or expenditure_year < 1900
        or expenditure_year > 2100
    ):
        raise ValueError("weight_vintage.expenditure_year must be a plausible year")
    link_month = vintage_raw.get("link_month")
    if not isinstance(link_month, str) or not CPI_LINK_MONTH_PATTERN.match(link_month.strip()):
        raise ValueError("weight_vintage.link_month must be YYYY-MM")
    provisional = vintage_raw.get("provisional")
    if not isinstance(provisional, bool):
        raise ValueError("weight_vintage.provisional must be a bool")
    vintage = CpiWeightVintage(
        expenditure_year=expenditure_year,
        link_month=link_month.strip(),
        provisional=provisional,
    )
    products_raw = raw.get("product_ids")
    if not isinstance(products_raw, dict) or not products_raw:
        raise ValueError("CPI registry needs a non empty product_ids mapping")
    product_ids: dict[str, int] = {}
    for name, product_id in products_raw.items():
        if isinstance(product_id, bool) or not isinstance(product_id, int):
            raise ValueError(f"CPI product id for {name!r} must be an integer")
        if not CPI_PRODUCT_ID_PATTERN.match(str(product_id)):
            raise ValueError(
                f"CPI product id for {name!r} must be an 8 digit id, got {product_id!r}"
            )
        product_ids[str(name)] = product_id
    if set(product_ids.keys()) != set(EXPECTED_CPI_PRODUCT_IDS.keys()):
        raise ValueError(
            f"CPI product_ids keys must be {sorted(EXPECTED_CPI_PRODUCT_IDS)}, "
            f"got {sorted(product_ids)}"
        )
    for name, expected in EXPECTED_CPI_PRODUCT_IDS.items():
        if product_ids[name] != expected:
            raise ValueError(
                f"CPI product id for {name!r} must pin {expected}, got {product_ids[name]}"
            )
    raw_components = raw.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        raise ValueError("CPI registry needs a non empty components list")
    components: list[CpiComponent] = []
    seen_ids: set[str] = set()
    seen_vectors: set[str] = set()
    seen_basket_products: set[str] = set()
    seen_basket_vectors: set[str] = set()
    for row in raw_components:
        if not isinstance(row, dict):
            raise ValueError("CPI component rows must be mappings")
        component_id = row.get("component_id", "")
        label = row.get("label", "")
        vector_id = row.get("vector_id", "")
        if not isinstance(component_id, str) or not component_id.strip():
            raise ValueError("CPI component_id must be a non empty string")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("CPI component label must be a non empty string")
        if not isinstance(vector_id, str) or not vector_id.strip():
            raise ValueError("CPI component vector_id must be a non empty string")
        cleaned_id = component_id.strip()
        cleaned_vector = vector_id.strip()
        if not CPI_VECTOR_ID_PATTERN.match(cleaned_vector):
            raise ValueError(
                f"CPI vector_id for {cleaned_id!r} must be an 8 digit id, got {cleaned_vector!r}"
            )
        if cleaned_id in seen_ids:
            raise ValueError(f"duplicate CPI component_id: {cleaned_id!r}")
        if cleaned_vector in seen_vectors:
            raise ValueError(f"duplicate CPI vector_id: {cleaned_vector!r}")
        seen_ids.add(cleaned_id)
        seen_vectors.add(cleaned_vector)
        weight = row.get("weight_percent")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise ValueError(f"CPI weight for {cleaned_id!r} must be numeric")
        weight_value = float(weight)
        if weight_value != weight_value or weight_value in (float("inf"), float("-inf")):
            raise ValueError(f"CPI weight for {cleaned_id!r} must be finite")
        if weight_value <= 0.0:
            raise ValueError(f"CPI weight for {cleaned_id!r} must be positive")
        seasonally_adjusted = row.get("seasonally_adjusted")
        if not isinstance(seasonally_adjusted, bool):
            raise ValueError(f"CPI seasonally_adjusted for {cleaned_id!r} must be a bool")
        basket_groups = _load_basket_list(row, cleaned_id, "basket_product_groups")
        basket_vectors = _load_basket_list(row, cleaned_id, "basket_vector_ids")
        if len(basket_groups) != len(basket_vectors):
            raise ValueError(
                f"CPI basket lists for {cleaned_id!r} must be parallel equal length, "
                f"got {len(basket_groups)} groups and {len(basket_vectors)} vectors"
            )
        if not basket_groups:
            raise ValueError(f"CPI basket lists for {cleaned_id!r} must be non empty")
        for group, vector in zip(basket_groups, basket_vectors, strict=True):
            if not CPI_BASKET_VECTOR_PATTERN.match(vector):
                raise ValueError(
                    f"CPI basket vector for {cleaned_id!r} must be an 8 digit classic "
                    f"id or a 10 digit extended id, got {vector!r}"
                )
            if group in seen_basket_products:
                raise ValueError(f"duplicate CPI basket product group: {group!r}")
            if vector in seen_basket_vectors:
                raise ValueError(f"duplicate CPI basket vector id: {vector!r}")
            seen_basket_products.add(group)
            seen_basket_vectors.add(vector)
        components.append(
            CpiComponent(
                component_id=cleaned_id,
                label=label.strip(),
                vector_id=cleaned_vector,
                weight_percent=weight_value,
                seasonally_adjusted=seasonally_adjusted,
                basket_product_groups=tuple(basket_groups),
                basket_vector_ids=tuple(basket_vectors),
            )
        )
    exclusions = _load_basket_exclusions(raw, seen_basket_products, seen_basket_vectors)
    return CpiConfig(
        schema_version=int(schema_version),
        weight_vintage=vintage,
        product_ids=product_ids,
        components=tuple(components),
        published=_load_cpi_published(raw),
        basket_exclusions=tuple(exclusions),
    )


def _load_cpi_published(raw: dict[str, object]) -> dict[str, str]:
    """Load the pinned published index vector pins, failing closed.

    The registry pins StatCan index levels (not precomputed YoY): the
    trim and median index vectors are converted to YoY with
    year_over_year_percent before validation. Any YoY vector pin or
    missing pin fails closed so semantics stay explicit.
    """
    raw_published = raw.get("published", {})
    if raw_published is None:
        raise ValueError("CPI published must be a mapping")
    if not isinstance(raw_published, dict):
        raise ValueError("CPI published must be a mapping")
    if set(raw_published.keys()) != set(EXPECTED_PUBLISHED_KEYS):
        raise ValueError(
            f"CPI published keys must be {sorted(EXPECTED_PUBLISHED_KEYS)}, "
            f"got {sorted(str(key) for key in raw_published.keys())}"
        )
    published: dict[str, str] = {}
    for name, vector_id in raw_published.items():
        if not isinstance(vector_id, str) or not vector_id.strip():
            raise ValueError(f"CPI published vector for {name!r} must be a non empty string")
        cleaned = vector_id.strip()
        if not CPI_VECTOR_ID_PATTERN.match(cleaned):
            raise ValueError(
                f"CPI published vector for {name!r} must be an 8 digit id, got {cleaned!r}"
            )
        published[str(name)] = cleaned
    return published


def _load_basket_list(row: dict[str, object], component_id: str, key: str) -> list[str]:
    """Return a cleaned non empty string list for a basket mapping key."""
    raw_list = row.get(key)
    if not isinstance(raw_list, list) or not raw_list:
        raise ValueError(f"CPI {key} for {component_id!r} must be a non empty list")
    cleaned: list[str] = []
    for item in raw_list:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"CPI {key} for {component_id!r} must hold non empty strings")
        cleaned.append(item.strip())
    return cleaned


def _load_basket_exclusions(
    raw: dict[str, object],
    seen_products: set[str],
    seen_vectors: set[str],
) -> list[BasketExclusion]:
    """Load basket exclusions with aggregate or special aggregate reasons."""
    raw_exclusions = raw.get("basket_exclusions")
    if raw_exclusions is None:
        raise ValueError("CPI registry needs a basket_exclusions list")
    if not isinstance(raw_exclusions, list):
        raise ValueError("CPI basket_exclusions must be a list")
    exclusions: list[BasketExclusion] = []
    for entry in raw_exclusions:
        if not isinstance(entry, dict):
            raise ValueError("CPI basket_exclusions rows must be mappings")
        product = entry.get("product_group", "")
        vector = entry.get("vector_id", "")
        reason = entry.get("reason", "")
        if not isinstance(product, str) or not product.strip():
            raise ValueError("CPI exclusion product_group must be a non empty string")
        if not isinstance(vector, str) or not vector.strip():
            raise ValueError("CPI exclusion vector_id must be a non empty string")
        if not isinstance(reason, str) or reason.strip() not in BASKET_EXCLUSION_REASONS:
            raise ValueError(
                "CPI exclusion reason must be one of "
                f"{sorted(BASKET_EXCLUSION_REASONS)}, got {reason!r}"
            )
        cleaned_product = product.strip()
        cleaned_vector = vector.strip()
        if not CPI_BASKET_VECTOR_PATTERN.match(cleaned_vector):
            raise ValueError(
                f"CPI exclusion vector for {cleaned_product!r} must be an 8 digit "
                f"classic id or a 10 digit extended id, got {cleaned_vector!r}"
            )
        if cleaned_product in seen_products:
            raise ValueError(f"duplicate CPI basket product group: {cleaned_product!r}")
        if cleaned_vector in seen_vectors:
            raise ValueError(f"duplicate CPI basket vector id: {cleaned_vector!r}")
        seen_products.add(cleaned_product)
        seen_vectors.add(cleaned_vector)
        exclusions.append(
            BasketExclusion(
                product_group=cleaned_product,
                vector_id=cleaned_vector,
                reason=reason.strip(),
            )
        )
    return exclusions
