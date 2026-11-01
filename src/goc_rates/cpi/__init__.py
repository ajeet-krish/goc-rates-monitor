"""Phase 4 CPI engine: trim, median, weights, bulk ingest, and validation."""

from goc_rates.cpi.bulk import (
    BasketWeights,
    BulkMember,
    BulkTable,
    assemble_bulk_table,
    extract_basket_weights,
    extract_component_months,
    fetch_bulk_table,
)
from goc_rates.cpi.changes import (
    annualized_from_monthly_percent,
    compound_annual_percent,
    month_over_month_percent,
    year_over_year_percent,
)
from goc_rates.cpi.components import (
    EXPECTED_COMPONENT_COUNT,
    ComponentSpec,
    load_component_specs,
    specs_from_config,
)
from goc_rates.cpi.decomposition import (
    Contribution,
    contribution_pp,
    decompose_month,
    total_contribution_pp,
)
from goc_rates.cpi.section import (
    DERIVED_SOURCE,
    HISTORY_MONTHS,
    INDEX_MONTHS,
    INFLATION_LABEL,
    build_inflation_section,
    build_inflation_section_from_bulk,
    cpi_provenance_entry,
)
from goc_rates.cpi.trim_median import (
    TRIM_METHOD,
    ComponentRate,
    TrimMedianResult,
    compute_trim_median,
)
from goc_rates.cpi.validation import (
    MAE_GATE_PP,
    MIN_VALIDATION_MONTHS,
    VALIDATION_WINDOW_MONTHS,
    ValidationResult,
    validate_replica,
    validation_flag,
)
from goc_rates.cpi.weights import (
    WEIGHT_SUM_TOLERANCE,
    WeightVintage,
    normalize_weights,
    vintage_from_config,
)

__all__ = [
    "EXPECTED_COMPONENT_COUNT",
    "HISTORY_MONTHS",
    "INDEX_MONTHS",
    "INFLATION_LABEL",
    "MAE_GATE_PP",
    "MIN_VALIDATION_MONTHS",
    "TRIM_METHOD",
    "VALIDATION_WINDOW_MONTHS",
    "WEIGHT_SUM_TOLERANCE",
    "DERIVED_SOURCE",
    "BasketWeights",
    "BulkMember",
    "BulkTable",
    "ComponentRate",
    "ComponentSpec",
    "Contribution",
    "TrimMedianResult",
    "ValidationResult",
    "WeightVintage",
    "annualized_from_monthly_percent",
    "assemble_bulk_table",
    "build_inflation_section",
    "build_inflation_section_from_bulk",
    "compound_annual_percent",
    "compute_trim_median",
    "contribution_pp",
    "cpi_provenance_entry",
    "decompose_month",
    "extract_basket_weights",
    "extract_component_months",
    "fetch_bulk_table",
    "load_component_specs",
    "month_over_month_percent",
    "normalize_weights",
    "specs_from_config",
    "total_contribution_pp",
    "validate_replica",
    "validation_flag",
    "vintage_from_config",
    "year_over_year_percent",
]
