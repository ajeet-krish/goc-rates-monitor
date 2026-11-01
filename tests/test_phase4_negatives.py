"""Phase 4 negative tests: drift, tamper, suppression, and flag honesty."""

from __future__ import annotations

from typing import Any

from goc_rates.verify import verify_snapshot
from tests.cpi_fixtures import build_demo_inflation


def _inflation_snapshot() -> dict[str, Any]:
    """Build a snapshot carrying only the demo inflation section."""
    section, entry = build_demo_inflation()
    return {
        "metadata": {"snapshot_date": "2026-09-30", "schema_version": 1},
        "observations": {"inflation": section},
        "provenance": {"statcan_cpi": entry},
    }


def _check(snapshot: dict[str, Any], check_id: str) -> Any:
    """Return one check result by id."""
    report = verify_snapshot(snapshot)
    for item in report["checks"]:
        assert isinstance(item, dict)
        if item["id"] == check_id:
            return item
    raise AssertionError(f"missing check {check_id}")


def _inflation(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the inflation section mapping."""
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    inflation = observations["inflation"]
    assert isinstance(inflation, dict)
    return inflation


def test_demo_fixture_passes_v19_to_v22() -> None:
    """The demo inflation section passes V19 to V22."""
    snapshot = _inflation_snapshot()
    for check_id in ("V19", "V20", "V21", "V22"):
        assert _check(snapshot, check_id)["passed"] is True


def test_missing_inflation_fails_all_four() -> None:
    """No inflation section fails V19 to V22."""
    snapshot = _inflation_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    del observations["inflation"]
    for check_id in ("V19", "V20", "V21", "V22"):
        assert _check(snapshot, check_id)["passed"] is False


def test_weight_drift_tamper_fails_v19() -> None:
    """A drifted registry weight total fails V19."""
    snapshot = _inflation_snapshot()
    contributions = _inflation(snapshot)["contributions"]
    assert isinstance(contributions, list)
    first = contributions[0]
    assert isinstance(first, dict)
    first["weight_percent"] = float(first["weight_percent"]) + 2.0
    assert _check(snapshot, "V19")["passed"] is False


def test_component_count_tamper_fails_v19() -> None:
    """A count of 54 fails the 55 component pin in V19."""
    snapshot = _inflation_snapshot()
    _inflation(snapshot)["component_count"] = 54
    assert _check(snapshot, "V19")["passed"] is False


def test_link_month_tamper_fails_v19() -> None:
    """A wrong link month fails the 2025-05 pin in V19."""
    snapshot = _inflation_snapshot()
    vintage = _inflation(snapshot)["weight_vintage"]
    assert isinstance(vintage, dict)
    vintage["link_month"] = "2025-06"
    assert _check(snapshot, "V19")["passed"] is False


def test_sa_owns_tamper_fails_v19() -> None:
    """Claiming seasonal adjustment ownership fails V19."""
    snapshot = _inflation_snapshot()
    _inflation(snapshot)["owns_seasonal_adjustment"] = True
    assert _check(snapshot, "V19")["passed"] is False


def test_reference_month_grammar_fails_v19() -> None:
    """A slash dated reference month fails V19."""
    snapshot = _inflation_snapshot()
    _inflation(snapshot)["reference_month"] = "2026/09"
    assert _check(snapshot, "V19")["passed"] is False


def test_sha12_mismatch_fails_v19() -> None:
    """A short hash that does not prefix its sha256 fails V19."""
    snapshot = _inflation_snapshot()
    bulk = _inflation(snapshot)["bulk"]
    assert isinstance(bulk, dict)
    entry = bulk["cpi_monthly"]
    assert isinstance(entry, dict)
    entry["zip_sha12"] = "0" * 12
    assert _check(snapshot, "V19")["passed"] is False


def test_missing_component_label_fails_v20_v21() -> None:
    """A contribution row without a component id fails V20 and V21."""
    snapshot = _inflation_snapshot()
    contributions = _inflation(snapshot)["contributions"]
    assert isinstance(contributions, list)
    first = contributions[0]
    assert isinstance(first, dict)
    del first["component_id"]
    assert _check(snapshot, "V20")["passed"] is False
    assert _check(snapshot, "V21")["passed"] is False


def test_stored_trim_tamper_fails_v20() -> None:
    """A stored trim moved by 5bp fails the 1bp recompute in V20."""
    snapshot = _inflation_snapshot()
    latest = _inflation(snapshot)["latest"]
    assert isinstance(latest, dict)
    trim_mom = latest["trim_mom"]
    assert isinstance(trim_mom, dict)
    trim_mom["value"] = float(trim_mom["value"]) + 0.05
    assert _check(snapshot, "V20")["passed"] is False


def test_excluded_weight_tamper_fails_v21() -> None:
    """An excluded weight of 0.30 fails the 0.40 pin in V21."""
    snapshot = _inflation_snapshot()
    inflation = _inflation(snapshot)
    inflation["excluded_weight_fraction"] = 0.30
    inflation["kept_weight_fraction"] = 0.70
    assert _check(snapshot, "V21")["passed"] is False


def test_label_tamper_fails_v22() -> None:
    """A non experimental label fails V22."""
    snapshot = _inflation_snapshot()
    _inflation(snapshot)["label"] = "official"
    assert _check(snapshot, "V22")["passed"] is False


def test_is_official_tamper_fails_v22() -> None:
    """Claiming official status fails V22."""
    snapshot = _inflation_snapshot()
    _inflation(snapshot)["is_official"] = True
    assert _check(snapshot, "V22")["passed"] is False


def test_mae_suppression_fails_v22() -> None:
    """Zeroing the stored MAE while keeping residuals fails V22."""
    snapshot = _inflation_snapshot()
    validation = _inflation(snapshot)["validation"]
    assert isinstance(validation, dict)
    trim = validation["trim"]
    assert isinstance(trim, dict)
    trim["mae_pp"] = 0.0
    assert _check(snapshot, "V22")["passed"] is False


def test_wrong_exceeds_flag_fails_v22() -> None:
    """Claiming a breach when the gate passes fails V22."""
    snapshot = _inflation_snapshot()
    validation = _inflation(snapshot)["validation"]
    assert isinstance(validation, dict)
    validation["exceeds_gate"] = True
    validation["flag"] = "exceeds_gate_needs_explanation"
    assert _check(snapshot, "V22")["passed"] is False


def test_honest_breach_still_passes_v22() -> None:
    """An honestly flagged breach passes V22: the flag never blocks."""
    snapshot = _inflation_snapshot()
    validation = _inflation(snapshot)["validation"]
    assert isinstance(validation, dict)
    residuals = validation["residuals_trim_pp"]
    assert isinstance(residuals, list)
    scaled = [float(item) * 50.0 for item in residuals]
    validation["residuals_trim_pp"] = scaled
    trim = validation["trim"]
    assert isinstance(trim, dict)
    trim["mae_pp"] = sum(abs(item) for item in scaled) / float(len(scaled))
    trim["bias_pp"] = sum(scaled) / float(len(scaled))
    trim["max_abs_resid_pp"] = max(abs(item) for item in scaled)
    assert trim["mae_pp"] > 0.10
    validation["exceeds_gate"] = True
    validation["flag"] = "exceeds_gate_needs_explanation"
    item = _check(snapshot, "V22")
    assert item["passed"] is True
