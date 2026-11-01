"""CPI trim median tests: rank, median rule, tails, renormalization, compounding."""

import pytest

from goc_rates.cpi.changes import compound_annual_percent
from goc_rates.cpi.trim_median import (
    TRIM_METHOD,
    ComponentRate,
    compute_trim_median,
)


def _rate(component_id: str, monthly: float, weight: float) -> ComponentRate:
    """Build one component rate."""
    return ComponentRate(
        component_id=component_id,
        monthly_rate_percent=monthly,
        weight_fraction=weight,
    )


def test_method_id_is_pinned() -> None:
    """Method id stays pinned for audit."""
    assert TRIM_METHOD == "cpi_trim_median_weighted_sa_v1"


def test_median_is_first_cumulative_over_50() -> None:
    """A component ending exactly at 50 percent is not the median."""
    result = compute_trim_median(
        [
            _rate("A", 0.10, 0.50),
            _rate("B", 0.20, 0.30),
            _rate("C", 0.30, 0.20),
        ]
    )
    assert result.median_component_id == "B"
    assert result.median_mom_percent == pytest.approx(0.20)


def test_trim_excludes_20pct_tails_with_partial_splits() -> None:
    """Straddling components contribute only their kept weight slice."""
    result = compute_trim_median(
        [
            _rate("X", -1.00, 0.50),
            _rate("Y", 0.00, 0.30),
            _rate("Z", 1.00, 0.20),
        ]
    )
    assert result.trim_mom_percent == pytest.approx(-0.50)
    assert result.kept_weight_fraction == pytest.approx(0.60)
    assert result.excluded_weight_fraction == pytest.approx(0.40)
    assert "X" in result.lower_excluded
    assert "Z" in result.upper_excluded
    assert "Y" not in result.upper_excluded


def test_trim_renormalizes_kept_60pct() -> None:
    """Trim divides by the kept weight, renormalizing to 60 percent."""
    result = compute_trim_median(
        [
            _rate("A", 0.10, 0.25),
            _rate("B", 0.20, 0.25),
            _rate("C", 0.30, 0.25),
            _rate("D", 0.40, 0.25),
        ]
    )
    expected = (0.10 * 0.05 + 0.20 * 0.25 + 0.30 * 0.25 + 0.40 * 0.05) / 0.60
    assert result.trim_mom_percent == pytest.approx(expected)
    assert result.kept_weight_fraction == pytest.approx(0.60, abs=1e-9)
    assert result.median_component_id == "C"


def test_weights_must_sum_to_one() -> None:
    """Fractions summing to 0.9 fail closed instead of rescaling."""
    with pytest.raises(ValueError, match="expected 1.0"):
        compute_trim_median([_rate("A", 0.10, 0.50), _rate("B", 0.20, 0.40)])


def test_duplicate_components_raise() -> None:
    """Duplicate component ids raise."""
    with pytest.raises(ValueError, match="duplicate"):
        compute_trim_median([_rate("A", 0.10, 0.50), _rate("A", 0.20, 0.50)])


def test_empty_rates_raise() -> None:
    """An empty distribution raises."""
    with pytest.raises(ValueError, match="at least one"):
        compute_trim_median([])


def test_mean_of_12_fails_while_product_passes() -> None:
    """A volatile year shows the mean failing where compounding passes."""
    rates = [5.0, -4.0] * 6
    naive_annual = sum(rates) / 12.0 * 12.0
    assert naive_annual == pytest.approx(6.0)
    assert compound_annual_percent(rates) == pytest.approx((1.008**6 - 1.0) * 100.0)
    assert abs(compound_annual_percent(rates) - naive_annual) > 0.05


def test_flat_rates_compound_within_golden() -> None:
    """Twelve months at 0.2 percent compound to about 2.43 percent."""
    assert compound_annual_percent([0.2] * 12) == pytest.approx(2.4266, abs=1e-4)
