"""Phase 1 negative plus boundary tests (reviews follow up).

Covers tampered V10 bytes, missing manifest V10, StatCan failure modes,
CLI exit codes, calendar boundary dates, FRED key leak V11, path traversal
plus ID grammar, oversize caps, and fsync ordering for atomic writes.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from goc_rates.__main__ import parse_snapshot_date, run_snapshot
from goc_rates.calendar import ca_holidays, is_business_day
from goc_rates.clients.base import (
    MAX_RESPONSE_BYTES,
    BaseClient,
    parse_json_capped,
)
from goc_rates.clients.statcan import fetch_statcan_vectors
from goc_rates.clients.valet import fetch_valet_group, fetch_valet_series
from goc_rates.snapshot import atomic_write_text, canonical_dumps
from goc_rates.verify import run_checks, tbill_price_from_yield, verify_file


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
    }


def _write_good_pair(tmp_path: Path) -> tuple[Path, str]:
    snapshot = _passing_snapshot()
    text = canonical_dumps(snapshot)
    snap_path = tmp_path / "snapshot.json"
    snap_path.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    manifest = {"files": {"snapshot.json": {"sha256": digest}}}
    (tmp_path / "manifest.json").write_text(canonical_dumps(manifest), encoding="utf-8")
    return snap_path, digest


def _check_id(results: list[Any], check_id: str) -> Any:
    for item in results:
        item_id = item.check_id if hasattr(item, "check_id") else item["id"]
        if item_id == check_id:
            return item
    raise AssertionError(f"missing check {check_id}")


def test_verify_v10_tampered_bytes_fail(tmp_path: Path) -> None:
    """Tampered snapshot bytes fail V10 with a mismatch detail."""
    snap_path, _ = _write_good_pair(tmp_path)
    with snap_path.open("ab") as handle:
        handle.write(b" ")
    code = verify_file(snap_path)
    assert code == 1
    report = json.loads((tmp_path / "verify.json").read_text(encoding="utf-8"))
    assert report["passed"] is False
    v10 = next(item for item in report["checks"] if item["id"] == "V10")
    assert v10["passed"] is False
    assert "mismatch" in v10["detail"]


def test_verify_v10_missing_manifest_fails(tmp_path: Path) -> None:
    """A missing sibling manifest.json fails V10 instead of passing."""
    snapshot = _passing_snapshot()
    snap_path = tmp_path / "snapshot.json"
    snap_path.write_text(canonical_dumps(snapshot), encoding="utf-8")
    assert not (tmp_path / "manifest.json").exists()
    code = verify_file(snap_path)
    assert code == 1
    report = json.loads((tmp_path / "verify.json").read_text(encoding="utf-8"))
    v10 = next(item for item in report["checks"] if item["id"] == "V10")
    assert v10["passed"] is False
    assert "missing" in v10["detail"].lower()


def _statcan_client(body: str) -> BaseClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    return BaseClient(transport=httpx.MockTransport(handler))


def test_statcan_non_success_status_raises() -> None:
    """A non SUCCESS entry status raises instead of returning rows."""
    body = json.dumps([{"status": "ERROR", "object": {"vectorId": 41690973}}])
    client = _statcan_client(body)
    try:
        with pytest.raises(ValueError, match="status"):
            fetch_statcan_vectors(["41690973"], client, latest_n=2)
    finally:
        client.close()


def test_statcan_missing_vector_data_point_raises() -> None:
    """An entry without vectorDataPoint raises a clear error."""
    body = json.dumps([{"status": "SUCCESS", "object": {"vectorId": 41690973}}])
    client = _statcan_client(body)
    try:
        with pytest.raises(ValueError, match="vectorDataPoint"):
            fetch_statcan_vectors(["41690973"], client, latest_n=2)
    finally:
        client.close()


def test_statcan_missing_requested_vector_raises() -> None:
    """A response that omits a requested vector id raises."""
    body = json.dumps(
        [
            {
                "status": "SUCCESS",
                "object": {"vectorId": 99999999, "vectorDataPoint": []},
            }
        ]
    )
    client = _statcan_client(body)
    try:
        with pytest.raises(ValueError, match="missing requested"):
            fetch_statcan_vectors(["41690973"], client, latest_n=2)
    finally:
        client.close()


def test_cli_config_failure_returns_2(tmp_path: Path, capsys: Any) -> None:
    """A missing benchmark map makes snapshot exit 2."""
    code = run_snapshot("2026-10-30", str(tmp_path / "out"), str(tmp_path / "nope.yaml"))
    assert code == 2
    captured = capsys.readouterr()
    assert "snapshot failed" in captured.err


def test_cli_skeleton_returns_1_not_0(tmp_path: Path) -> None:
    """The Phase 1 skeleton writes output but exits 1 to fail closed."""
    config = Path(__file__).resolve().parent.parent / "config" / "benchmark_map.yaml"
    out_dir = tmp_path / "snap"
    code = run_snapshot("2026-10-30", str(out_dir), str(config))
    assert code == 1
    assert code != 0
    assert (out_dir / "snapshot.json").is_file()
    assert (out_dir / "manifest.json").is_file()


def test_us_saturday_new_year_observed_friday_closed() -> None:
    """Saturday Jan 1 2022 is observed Friday Dec 31 2021 on the US leg."""
    import datetime as dt

    from goc_rates.calendar import us_bond_holidays

    assert dt.date(2021, 12, 31) in us_bond_holidays(2022)
    assert not is_business_day(dt.date(2021, 12, 31), "us")
    assert not is_business_day(dt.date(2021, 12, 31), "joint")
    assert is_business_day(dt.date(2021, 12, 31), "ca")


def test_ca_2027_christmas_and_boxing_day_bump() -> None:
    """Christmas Saturday observes Dec 27 and Boxing Day bumps to Dec 28."""
    import datetime as dt

    holidays = ca_holidays(2027)
    assert dt.date(2027, 12, 27) in holidays
    assert dt.date(2027, 12, 28) in holidays
    assert not is_business_day(dt.date(2027, 12, 27), "ca")
    assert not is_business_day(dt.date(2027, 12, 28), "ca")


def test_ca_2027_family_day_and_sep30() -> None:
    """Family Day is Feb 15 2027 and Sep 30 is a CA holiday."""
    import datetime as dt

    holidays = ca_holidays(2027)
    assert dt.date(2027, 2, 15) in holidays
    assert dt.date(2027, 9, 30) in holidays
    assert not is_business_day(dt.date(2027, 2, 15), "ca")
    assert not is_business_day(dt.date(2027, 9, 30), "ca")


def test_fred_key_leak_fails_v11_without_printing_key() -> None:
    """A configured key present in snapshot text fails V11 redacted."""
    key = "test-secret-key-ABCD-1234"
    snapshot = _passing_snapshot()
    observations = snapshot["observations"]
    assert isinstance(observations, dict)
    fred_lag = observations["fred_lag"]
    assert isinstance(fred_lag, dict)
    fred_lag["expected_lag_note"] = f"note carries {key} inside"
    results = run_checks(snapshot, fred_api_key=key)
    v11 = _check_id(results, "V11")
    passed = v11.passed if hasattr(v11, "passed") else v11["passed"]
    detail = v11.detail if hasattr(v11, "detail") else v11["detail"]
    assert passed is False
    assert key not in detail
    assert "API key" in detail or "secret" in detail.lower()


def test_path_traversal_date_rejected() -> None:
    """Date values with path separators never reach Path use."""
    for bad in ("../etc/passwd", "2026-10-30/../../x", "2026/10/30", "..", ""):
        with pytest.raises(ValueError):
            parse_snapshot_date(bad)


def test_valet_id_with_slash_rejected() -> None:
    """Valet ids with a slash are rejected by the closed grammar."""

    def exploding(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be reached for a bad id")

    client = BaseClient(transport=httpx.MockTransport(exploding))
    try:
        with pytest.raises(ValueError, match="must match"):
            fetch_valet_series("BD.CDN/10YR", client)
        with pytest.raises(ValueError, match="must match"):
            fetch_valet_group("bond/yields", client)
    finally:
        client.close()


def test_oversize_declared_content_length_capped() -> None:
    """A declared Content-Length over the cap fails closed."""
    big = MAX_RESPONSE_BYTES + 1
    response = httpx.Response(
        200, headers={"content-length": str(big)}, content=b'{"ok": true}'
    )
    with pytest.raises(ValueError, match="cap"):
        parse_json_capped(response)


def test_oversize_snapshot_file_capped(tmp_path: Path, monkeypatch: Any) -> None:
    """verify_file rejects a snapshot file that exceeds the byte cap."""
    import goc_rates.verify as verify_mod

    monkeypatch.setattr(verify_mod, "MAX_SNAPSHOT_BYTES", 16)
    snap_path = tmp_path / "snapshot.json"
    snap_path.write_text(canonical_dumps(_passing_snapshot()), encoding="utf-8")
    with pytest.raises(ValueError, match="exceeds"):
        verify_file(snap_path)


def test_atomic_write_fsync_ordering(tmp_path: Path) -> None:
    """File fsync runs before rename and dir fsync runs after."""
    from unittest import mock

    import goc_rates.snapshot as snapshot_mod

    real_replace = os.replace
    real_fsync = os.fsync
    order: list[str] = []

    def fake_fsync(fd: int) -> None:
        order.append("fsync")
        real_fsync(fd)

    def fake_replace(src: Any, dst: Any) -> None:
        order.append("replace")
        real_replace(src, dst)

    def fake_dir(directory: Path) -> None:
        order.append("dir_fsync")

    target = tmp_path / "out.json"
    with (
        mock.patch.object(snapshot_mod.os, "fsync", side_effect=fake_fsync),
        mock.patch.object(snapshot_mod.os, "replace", side_effect=fake_replace),
        mock.patch.object(snapshot_mod, "_fsync_dir", side_effect=fake_dir),
    ):
        atomic_write_text(target, '{"a": 1}\n')
    assert order == ["fsync", "replace", "dir_fsync"]
    assert target.is_file()
