"""CPI golden tests: pinned trim, median, and compounding values."""

import hashlib

import pytest

from goc_rates.cpi.bulk import BulkTable
from goc_rates.cpi.changes import compound_annual_percent
from goc_rates.cpi.components import ComponentSpec
from goc_rates.cpi.section import build_inflation_section
from goc_rates.cpi.weights import WeightVintage


def _golden_section() -> dict[str, object]:
    """Build a three component golden section with constant rates.

    Sorted rates: B 0.1 (weight 0.3, cum 0.3), A 0.3 (weight 0.5,
    cum 0.8), C 0.5 (weight 0.2, cum 1.0). Median is A; trim keeps
    0.1 of B plus 0.5 of A over 0.6.
    """
    specs = [
        ComponentSpec("A", "Alpha", "1", 50.0, True),
        ComponentSpec("B", "Beta", "2", 30.0, True),
        ComponentSpec("C", "Gamma", "3", 20.0, True),
    ]
    weights = {"A": 0.50, "B": 0.30, "C": 0.20}
    months: list[str] = []
    year, month = 2023, 10
    for _ in range(40):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    rates = {"A": 0.30, "B": 0.10, "C": 0.50}
    monthly_indexes: dict[str, list[tuple[str, float]]] = {}
    for spec in specs:
        level = 100.0
        rows: list[tuple[str, float]] = []
        for calendar_month in months:
            rows.append((calendar_month, level))
            level *= 1.0 + rates[spec.component_id] / 100.0
        monthly_indexes[spec.component_id] = rows
    trim_mom = (0.10 * 0.10 + 0.30 * 0.50) / 0.60
    trim_yoy = compound_annual_percent([trim_mom] * 12)
    median_yoy = compound_annual_percent([0.30] * 12)
    yoy_months = months[12:]
    trim_series = [round(trim_yoy, 2)] * len(yoy_months)
    median_series = [round(median_yoy, 2)] * len(yoy_months)
    bulk_tables: dict[str, BulkTable] = {}
    for name, product_id in (
        ("cpi_monthly", 18100004),
        ("core_statistics", 18100256),
        ("basket_weights", 18100007),
    ):
        digest = hashlib.sha256(f"golden-{name}".encode()).hexdigest()
        bulk_tables[name] = BulkTable(
            product_id=product_id,
            zip_url=f"https://www150.statcan.gc.ca/n1/tbl/golden-{name}.zip",
            zip_sha256=digest,
            retrieved_utc="2026-10-01T00:00:00Z",
            members=(),
            zip_bytes=b"golden-zip-bytes",
        )
    section = build_inflation_section(
        specs=specs,
        weights=weights,
        monthly_indexes=monthly_indexes,
        published_trim_yoy=trim_series,
        published_median_yoy=median_series,
        published_months=yoy_months,
        bulk_tables=bulk_tables,
        vintage=WeightVintage(2024, "2025-05", True),
    )
    return {"section": section, "trim_mom": trim_mom, "trim_yoy": trim_yoy}


def test_golden_trim_and_median() -> None:
    """Golden trim is 0.2667 percent per month with median component A."""
    built = _golden_section()
    section = built["section"]
    assert isinstance(section, dict)
    latest = section["latest"]
    assert isinstance(latest, dict)
    trim_mom = latest["trim_mom"]
    median_mom = latest["median_mom"]
    assert isinstance(trim_mom, dict) and isinstance(median_mom, dict)
    assert trim_mom["value"] == pytest.approx(0.2666667, abs=1e-6)
    assert median_mom["value"] == pytest.approx(0.30)
    assert latest["median_component"] == "A"


def test_golden_yoy_compounds_not_averages() -> None:
    """Golden YoY compounds the monthly cores within 0.05pp of product."""
    built = _golden_section()
    section = built["section"]
    assert isinstance(section, dict)
    latest = section["latest"]
    assert isinstance(latest, dict)
    trim_yoy = latest["trim_yoy"]
    assert isinstance(trim_yoy, dict)
    expected = compound_annual_percent([float(str(built["trim_mom"]))] * 12)
    assert trim_yoy["value"] == pytest.approx(expected, abs=1e-9)
    naive = float(str(built["trim_mom"])) * 12.0
    assert abs(float(str(trim_yoy["value"])) - naive) > 0.01


def test_golden_history_and_indexes() -> None:
    """Golden history holds 12 months and indexes hold the trailing two."""
    built = _golden_section()
    section = built["section"]
    assert isinstance(section, dict)
    history = section["history"]
    assert isinstance(history, list) and len(history) == 12
    indexes = section["indexes"]
    assert isinstance(indexes, dict)
    assert len(indexes["months"]) == 2
    assert section["validation"]["exceeds_gate"] is False
