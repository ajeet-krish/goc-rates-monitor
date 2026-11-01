"""Verification tests: V01 to V12 checks with a 1.0 basis point tolerance."""

import json
from pathlib import Path
from typing import Any

from goc_rates.verify import (
    TOLERANCE_BP,
    tbill_price_from_yield,
    verify_file,
    verify_snapshot,
)


def _passing_snapshot() -> dict[str, Any]:
    price = tbill_price_from_yield(4.0, 90)
    return {
        "metadata": {"snapshot_date": "2026-10-30", "schema_version": 1},
        "observations": {
            "tbill_check": {"yield_percent": 4.0, "price": price, "days_to_maturity": 90},
            "benchmarks": {
                "10Y": {
                    "valet_label": "10-year benchmark bond yield",
                    "valet": {
                        "value": 3.85,
                        "unit": "percent",
                        "quality": "observed",
                        "source_id": "valet:BD.CDN.10YR.DQ.YLD",
                    },
                }
            },
            "corra": {
                "value_date": "2026-10-29",
                "pub_date": "2026-10-30",
                "date_role": "value_date_lags_pub_date",
            },
            "fred_lag": {
                "observation_date": "2026-10-29",
                "expected_lag_note": "DGS prints land T+1",
            },
            "statcan": {"seasonally_adjusted_reused_as_is": True, "vectors": {}},
            "cross_source_diff_bp": {"value_bp": 0.5, "unit": "basis_points"},
            "staleness": {"max_age_business_days": 1, "unit": "business_days"},
        },
        "provenance": {
            "valet": {
                "source_url": "https://www.bankofcanada.ca/valet/",
                "retrieved_utc": "2026-10-31T00:00:00Z",
                "vintage": "2026-10-30",
            }
        },
        "manifest": {"snapshot.json": {"sha256": "test-fixture-digest"}},
    }


def test_tolerance_is_one_basis_point() -> None:
    """Tolerance constant stays pinned at 1.0 bp."""
    assert TOLERANCE_BP == 1.0


def test_tbill_price_inversion_matches_formula() -> None:
    """T-bill price recovery matches the ACT/365 add-on formula."""
    assert tbill_price_from_yield(4.0, 365) == 100.0 / 1.04


def test_passing_snapshot_passes_all_twelve_checks() -> None:
    """A complete snapshot passes V01 to V12."""
    report = verify_snapshot(_passing_snapshot())
    assert report["passed"] is True
    assert len(report["checks"]) == 12
    assert report["failed_count"] == 0
    assert report["tolerance_unit"] == "basis_points"


def test_failing_snapshot_reports_failures() -> None:
    """A snapshot with drift fails the tolerance and label checks."""
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    cross = observations["cross_source_diff_bp"]
    assert isinstance(cross, dict)
    cross["value_bp"] = 5.0
    report = verify_snapshot(snapshot)
    assert report["passed"] is False
    failed_ids = [item["id"] for item in report["checks"] if not item["passed"]]
    assert "V11" in failed_ids


def test_verify_file_writes_verify_json_with_exit_code(tmp_path: Path) -> None:
    """verify_file writes verify.json and returns 0 for a passing snapshot."""
    import hashlib

    from goc_rates.snapshot import canonical_dumps

    snapshot = _passing_snapshot()
    snapshot.pop("manifest", None)
    snapshot_text = canonical_dumps(snapshot)
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(snapshot_text, encoding="utf-8")
    raw_digest = hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest()
    manifest = {"files": {"snapshot.json": {"sha256": raw_digest}}}
    (tmp_path / "manifest.json").write_text(canonical_dumps(manifest), encoding="utf-8")
    code = verify_file(snapshot_path)
    assert code == 0
    report = json.loads((tmp_path / "verify.json").read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert "snapshot_sha256" in report
