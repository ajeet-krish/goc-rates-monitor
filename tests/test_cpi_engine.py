"""CPI engine tests: changes, weights, decomposition, validation, section."""

import pytest

from goc_rates.config import load_cpi_config
from goc_rates.cpi.changes import (
    annualized_from_monthly_percent,
    compound_annual_percent,
    month_over_month_percent,
    year_over_year_percent,
)
from goc_rates.cpi.components import load_component_specs, specs_from_config
from goc_rates.cpi.decomposition import (
    contribution_pp,
    decompose_month,
    total_contribution_pp,
)
from goc_rates.cpi.validation import (
    MAE_GATE_PP,
    validate_replica,
    validation_flag,
)
from goc_rates.cpi.weights import normalize_weights, vintage_from_config
from tests.cpi_fixtures import CPI_REGISTRY_PATH, build_demo_inflation


def test_month_over_month_and_yoy() -> None:
    """Index ratios map to percent changes."""
    assert month_over_month_percent(101.0, 100.0) == pytest.approx(1.0)
    assert year_over_year_percent(103.0, 100.0) == pytest.approx(3.0)
    with pytest.raises(ValueError):
        month_over_month_percent(100.0, 0.0)


def test_annualized_rejects_non_positive_factor() -> None:
    """A monthly rate of negative 100 percent raises."""
    with pytest.raises(ValueError):
        annualized_from_monthly_percent(-100.0)
    assert annualized_from_monthly_percent(0.0) == pytest.approx(0.0)


def test_compound_caps_and_empties() -> None:
    """Compounding fails closed on empty input and month caps."""
    with pytest.raises(ValueError):
        compound_annual_percent([])
    with pytest.raises(ValueError):
        compound_annual_percent([0.1] * 241)


def test_registry_loads_55_sa_components() -> None:
    """The pinned registry holds 55 seasonally adjusted components."""
    specs = load_component_specs(CPI_REGISTRY_PATH)
    assert len(specs) == 55
    assert all(spec.seasonally_adjusted for spec in specs)
    assert {spec.component_id for spec in specs} == {f"C{i:02d}" for i in range(1, 56)}


def test_weights_renormalize_and_sum() -> None:
    """Registry weights normalize to fractions summing to one."""
    specs = load_component_specs(CPI_REGISTRY_PATH)
    weights = normalize_weights(specs)
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-12)
    assert weights["C11"] == pytest.approx(0.0565, abs=1e-12)


def test_weight_drift_fails() -> None:
    """A tampered weight total fails closed instead of rescaling."""
    from dataclasses import replace

    specs = list(load_component_specs(CPI_REGISTRY_PATH))
    specs[0] = replace(specs[0], weight_percent=specs[0].weight_percent + 2.0)
    with pytest.raises(ValueError, match="sum to"):
        normalize_weights(specs)


def test_vintage_pins_link_month() -> None:
    """Weight vintage pins expenditure 2024 and link month 2025-05."""
    config = load_cpi_config(CPI_REGISTRY_PATH)
    vintage = vintage_from_config(config)
    assert vintage.expenditure_year == 2024
    assert vintage.link_month == "2025-05"
    assert isinstance(vintage.provisional, bool)


def test_specs_reject_non_sa_component() -> None:
    """A registry row without seasonal adjustment fails closed."""
    from goc_rates.config import CpiComponent, CpiConfig, CpiWeightVintage

    config = load_cpi_config(CPI_REGISTRY_PATH)
    tampered = tuple(
        CpiComponent(
            component_id=item.component_id,
            label=item.label,
            vector_id=item.vector_id,
            weight_percent=item.weight_percent,
            seasonally_adjusted=False,
            basket_product_groups=item.basket_product_groups,
            basket_vector_ids=item.basket_vector_ids,
        )
        for item in config.components
    )
    drifted = CpiConfig(
        schema_version=config.schema_version,
        weight_vintage=CpiWeightVintage(2024, "2025-05", True),
        product_ids=dict(config.product_ids),
        components=tampered,
        published=dict(config.published),
        basket_exclusions=tuple(config.basket_exclusions),
    )
    with pytest.raises(ValueError, match="seasonally adjusted"):
        specs_from_config(drifted)


def test_contribution_is_weight_times_rate_over_100() -> None:
    """Contributions land in percentage points."""
    assert contribution_pp(50.0, 0.2) == pytest.approx(0.10)
    contributions = decompose_month({"A": 0.2, "B": 0.4}, {"A": 50.0, "B": 50.0})
    assert total_contribution_pp(contributions) == pytest.approx(0.30)
    with pytest.raises(ValueError):
        decompose_month({"A": 0.2}, {"A": 50.0, "B": 50.0})


def test_validation_gate_flags_without_blocking() -> None:
    """A breached MAE gate flags for explanation and never raises."""
    replica = [2.0] * 30
    published = [2.0] * 30
    passing = validate_replica(replica, published)
    assert passing.exceeds_gate is False
    assert validation_flag(False) == "within_gate"
    breached = validate_replica([3.0] * 30, published)
    assert breached.exceeds_gate is True
    assert breached.mae_pp == pytest.approx(1.0)
    assert validation_flag(True) == "exceeds_gate_needs_explanation"


def test_validation_needs_24_months() -> None:
    """Twelve months of history fail the 24 month minimum."""
    with pytest.raises(ValueError, match="at least 24"):
        validate_replica([2.0] * 12, [2.0] * 12)


def test_validation_window_uses_trailing_36() -> None:
    """Forty months validate over the trailing 36."""
    result = validate_replica([2.0] * 40, [2.0] * 40)
    assert result.months == 36
    assert MAE_GATE_PP == 0.10


def test_section_labels_and_provenance() -> None:
    """The demo section is experimental, unofficial, and fully hashed."""
    section, _ = build_demo_inflation()
    assert section["label"] == "experimental"
    assert section["is_official"] is False
    assert section["method"] == "cpi_trim_median_weighted_sa_v1"
    assert section["owns_seasonal_adjustment"] is False
    assert section["component_count"] == 55
    assert section["weight_vintage"] == {
        "expenditure_year": 2024,
        "link_month": "2025-05",
        "provisional": True,
    }
    assert len(section["indexes"]["months"]) == 2
    assert len(section["indexes"]["trim"]) == 2
    assert len(section["history"]) == 12
    for quantity in (
        *section["indexes"]["trim"],
        *section["indexes"]["median"],
    ):
        assert quantity["unit"] == "index_points"
    assert section["latest"]["trim_mom"]["unit"] == "percent_per_month"
    assert section["latest"]["trim_yoy"]["unit"] == "percent"
    assert section["validation"]["months"] >= 24
    assert section["validation"]["exceeds_gate"] is False
    for name, entry in section["bulk"].items():
        assert entry["zip_sha12"] == entry["zip_sha256"][:12]
        assert name in ("cpi_monthly", "core_statistics", "basket_weights")
