"""Shared deterministic CPI inflation fixture for Phase 4 tests."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from goc_rates.config import load_cpi_config
from goc_rates.cpi.bulk import BulkTable
from goc_rates.cpi.changes import compound_annual_percent, month_over_month_percent
from goc_rates.cpi.components import specs_from_config
from goc_rates.cpi.section import build_inflation_section
from goc_rates.cpi.trim_median import ComponentRate, compute_trim_median
from goc_rates.cpi.weights import normalize_weights, vintage_from_config

CPI_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "cpi_components.yaml"

DEMO_MONTH_COUNT = 40
DEMO_END_MONTH = "2026-09"


def demo_months(count: int = DEMO_MONTH_COUNT, end: str = DEMO_END_MONTH) -> list[str]:
    """Return ascending YYYY-MM months ending at the given month."""
    year, month = int(end[:4]), int(end[5:7])
    total = year * 12 + (month - 1)
    months: list[str] = []
    for offset in range(count - 1, -1, -1):
        stamp = total - offset
        stamp_year, stamp_month = divmod(stamp, 12)
        months.append(f"{stamp_year:04d}-{stamp_month + 1:02d}")
    return months


def _demo_rate(month_index: int, component_index: int) -> float:
    """Deterministic monthly rate in percent, spanning negative prints."""
    return 0.10 + 0.25 * math.sin(0.5 * float(month_index) + 0.7 * float(component_index))


def build_demo_inflation(
    month_count: int = DEMO_MONTH_COUNT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a passing demo inflation section plus its provenance entry."""
    config = load_cpi_config(CPI_REGISTRY_PATH)
    specs = specs_from_config(config)
    weights = normalize_weights(specs)
    vintage = vintage_from_config(config)
    months = demo_months(month_count)
    monthly_indexes: dict[str, list[tuple[str, float]]] = {}
    for component_index, spec in enumerate(specs):
        level = 100.0
        rows: list[tuple[str, float]] = []
        for month_index, month in enumerate(months):
            rows.append((month, level))
            level *= 1.0 + _demo_rate(month_index, component_index) / 100.0
        monthly_indexes[spec.component_id] = rows
    mom_months = months[1:]
    trim_moms: list[float] = []
    median_moms: list[float] = []
    for position, month in enumerate(mom_months):
        del month
        result = compute_trim_median(
            [
                ComponentRate(
                    component_id=spec.component_id,
                    monthly_rate_percent=month_over_month_percent(
                        monthly_indexes[spec.component_id][position + 1][1],
                        monthly_indexes[spec.component_id][position][1],
                    ),
                    weight_fraction=weights[spec.component_id],
                )
                for spec in specs
            ]
        )
        trim_moms.append(result.trim_mom_percent)
        median_moms.append(result.median_mom_percent)
    yoy_months = mom_months[11:]
    replica_trim = [
        compound_annual_percent(trim_moms[end - 11 : end + 1]) for end in range(11, len(trim_moms))
    ]
    replica_median = [
        compound_annual_percent(median_moms[end - 11 : end + 1])
        for end in range(11, len(median_moms))
    ]
    published_trim = [round(value, 2) for value in replica_trim]
    published_median = [round(value, 2) for value in replica_median]
    bulk_tables: dict[str, BulkTable] = {}
    for name in ("cpi_monthly", "core_statistics", "basket_weights"):
        digest = hashlib.sha256(f"demo-{name}".encode()).hexdigest()
        bulk_tables[name] = BulkTable(
            product_id=config.product_ids[name],
            zip_url=f"https://www150.statcan.gc.ca/n1/tbl/demo-{name}.zip",
            zip_sha256=digest,
            retrieved_utc="2026-10-01T00:00:00Z",
            members=(),
            zip_bytes=b"demo-zip-bytes",
        )
    section = build_inflation_section(
        specs=list(specs),
        weights=weights,
        monthly_indexes=monthly_indexes,
        published_trim_yoy=published_trim,
        published_median_yoy=published_median,
        published_months=yoy_months,
        bulk_tables=bulk_tables,
        vintage=vintage,
    )
    provenance = {
        "source_url": (
            "https://www150.statcan.gc.ca/t1/wds/rest/"
            f"getFullTableDownloadCSV/{config.product_ids['cpi_monthly']}/en"
        ),
        "retrieved_utc": "2026-10-01T00:00:00Z",
        "vintage": vintage.link_month,
    }
    return section, provenance


def attach_demo_inflation(observations: dict[str, Any], provenance: dict[str, Any]) -> None:
    """Attach a passing demo inflation section plus provenance in place."""
    section, entry = build_demo_inflation()
    observations["inflation"] = section
    provenance["statcan_cpi"] = entry
