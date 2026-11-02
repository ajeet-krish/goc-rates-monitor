"""Backfill command tests: strict asof, minimum rows, degrade paths, sealed writes."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import zipfile
from pathlib import Path
from typing import Any

from goc_rates.__main__ import build_parser, main
from goc_rates.backfill import run_backfill
from goc_rates.clients.valet import ValetObservation
from goc_rates.config import load_cpi_config
from goc_rates.cpi.bulk import BulkTable
from goc_rates.cpi.components import specs_from_config
from goc_rates.history import build_backfill_document
from goc_rates.models import make_quantity
from goc_rates.snapshot import canonical_dumps, sha256_text

CONFIG = Path(__file__).resolve().parent.parent / "config" / "benchmark_map.yaml"
CPI_CONFIG = Path(__file__).resolve().parent.parent / "config" / "cpi_components.yaml"
ASOF = "2026-10-30"

VALET_SERIES = (
    "BD.CDN.2YR.DQ.YLD",
    "BD.CDN.5YR.DQ.YLD",
    "BD.CDN.10YR.DQ.YLD",
    "BD.CDN.LONG.DQ.YLD",
)
FRED_SERIES = ("DGS2", "DGS5", "DGS10", "DGS30")


def _dates(count: int) -> list[str]:
    """Return count consecutive calendar dates ending at the pinned asof."""
    end = dt.date.fromisoformat(ASOF)
    return [(end - dt.timedelta(days=offset)).isoformat() for offset in reversed(range(count))]


def _valet_group(dates: list[str], base: float = 3.0) -> dict[str, list[Any]]:
    """Build a joint complete Valet group with one print per date per series."""
    grouped: dict[str, list[Any]] = {}
    for position, series_id in enumerate(VALET_SERIES):
        grouped[series_id] = [
            ValetObservation(
                observation_date=day,
                series_id=series_id,
                label="backfill test",
                quantity=make_quantity(
                    base + position * 0.3 + index * 0.001,
                    "percent",
                    "observed",
                    f"valet:{series_id}",
                ),
            )
            for index, day in enumerate(dates)
        ]
    return grouped


def _months(count: int) -> list[str]:
    """Return count YYYY-MM months ending at the asof month."""
    year, month = 2026, 10
    months: list[str] = []
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return sorted(months)


def _component_zip(vectors: list[str], months: list[str]) -> bytes:
    """Build a minimal bulk zip with REF_DATE, VECTOR, and VALUE columns."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        text = io.StringIO()
        writer = csv.writer(text)
        writer.writerow(["REF_DATE", "VECTOR", "VALUE"])
        for position, vector in enumerate(vectors):
            for index, month in enumerate(months):
                level = 100.0 + index * 0.15 + position * 0.5
                writer.writerow([f"{month}-01", vector, f"{level:.4f}"])
        archive.writestr("data.csv", text.getvalue())
    return buffer.getvalue()


def _bulk_table(product_id: int, zip_bytes: bytes) -> BulkTable:
    """Wrap fake zip bytes in a BulkTable with a valid sha256."""
    return BulkTable(
        product_id=product_id,
        zip_url=f"https://www150.statcan.gc.ca/t1/wds/rest/getFullTableDownloadCSV/{product_id}/en",
        zip_sha256="ab" * 32,
        retrieved_utc="2026-10-30T00:00:00+00:00",
        members=(),
        zip_bytes=zip_bytes,
    )


def _fake_bulk_tables() -> dict[str, BulkTable]:
    """Build fake monthly and core zips covering every registry vector."""
    config = load_cpi_config(CPI_CONFIG)
    vectors = [spec.vector_id for spec in specs_from_config(config)]
    months = _months(42)
    return {
        "cpi_monthly": _bulk_table(18100004, _component_zip(vectors, months)),
        "core_statistics": _bulk_table(18100256, _component_zip(vectors, months)),
    }


def test_backfill_rejects_non_iso_asof(tmp_path: Path) -> None:
    """A non strict asof exits 2 and writes nothing."""
    out = tmp_path / "backfill.json"
    assert run_backfill("10/30/2026", str(out), str(CONFIG)) == 2
    assert run_backfill("2026-13-01", str(out), str(CONFIG)) == 2
    assert not out.exists()
    assert not (tmp_path / "backfill-manifest.json").exists()


def test_backfill_valet_failure_exits_2_with_no_write(tmp_path: Path, monkeypatch: Any) -> None:
    """A Valet fetch failure exits 2 and writes neither artifact nor manifest."""
    import goc_rates.backfill as backfill_mod

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("upstream down")

    monkeypatch.setattr(backfill_mod, "fetch_valet_group", boom)
    out = tmp_path / "backfill.json"
    assert run_backfill(ASOF, str(out), str(CONFIG)) == 2
    assert not out.exists()
    assert not (tmp_path / "backfill-manifest.json").exists()


def test_backfill_minimum_rows_write_nothing_nonzero(tmp_path: Path, monkeypatch: Any) -> None:
    """Ten joint rows exit 1 with no artifact and no manifest."""
    import goc_rates.backfill as backfill_mod

    grouped = _valet_group(_dates(10))
    monkeypatch.setattr(backfill_mod, "fetch_valet_group", lambda *a, **k: grouped)
    monkeypatch.setattr(backfill_mod, "read_api_key", lambda: None)
    monkeypatch.setattr(
        backfill_mod, "fetch_bulk_table", lambda *a, **k: (_ for _ in ()).throw(ValueError("down"))
    )
    out = tmp_path / "backfill.json"
    assert run_backfill(ASOF, str(out), str(CONFIG)) == 1
    assert not out.exists()
    assert not (tmp_path / "backfill-manifest.json").exists()


def test_backfill_degraded_fred_and_cpi_exits_0(tmp_path: Path, monkeypatch: Any) -> None:
    """No FRED key and no bulk still exits 0 with an empty CPI section."""
    import goc_rates.backfill as backfill_mod

    grouped = _valet_group(_dates(300))
    monkeypatch.setattr(backfill_mod, "fetch_valet_group", lambda *a, **k: grouped)
    monkeypatch.setattr(backfill_mod, "read_api_key", lambda: None)

    def no_bulk(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("bulk down")

    monkeypatch.setattr(backfill_mod, "fetch_bulk_table", no_bulk)
    out = tmp_path / "backfill.json"
    assert run_backfill(ASOF, str(out), str(CONFIG)) == 0
    artifact = json.loads(out.read_text(encoding="utf-8"))
    assert artifact["metadata"]["daily_count"] == 300
    assert artifact["metadata"]["daily_count_unit"] == "count"
    assert artifact["cpi"] == []
    assert artifact["metadata"]["cpi_count"] == 0
    assert artifact["daily"][0]["spreads_status"] == "missing"
    assert artifact["provenance"]["statcan_cpi"]["status"] == "missing"
    assert artifact["exclusions"]
    assert "test-key" not in out.read_text(encoding="utf-8")
    manifest = json.loads((tmp_path / "backfill-manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["backfill.json"]["bytes_utf8"] == len(out.read_bytes())


def test_backfill_full_writes_sealed_artifact(tmp_path: Path, monkeypatch: Any) -> None:
    """Keyed FRED plus bulk months exit 0 with a builder sealed artifact."""
    import goc_rates.backfill as backfill_mod
    from goc_rates.clients.fred import FredObservation

    dates = _dates(300)
    grouped = _valet_group(dates)
    monkeypatch.setattr(backfill_mod, "fetch_valet_group", lambda *a, **k: grouped)
    monkeypatch.setattr(backfill_mod, "read_api_key", lambda: "test-key")

    def fake_fred(series_id: str, client: Any, api_key: Any = None, **kwargs: Any) -> list[Any]:
        position = FRED_SERIES.index(series_id)
        return [
            FredObservation(
                observation_date=day,
                series_id=series_id,
                quantity=make_quantity(
                    2.9 + position * 0.3 + index * 0.001,
                    "percent",
                    "observed",
                    f"fred:{series_id}",
                ),
            )
            for index, day in enumerate(dates)
        ]

    monkeypatch.setattr(backfill_mod, "fetch_fred_series", fake_fred)
    tables = _fake_bulk_tables()

    def fake_bulk(product_id: int, client: Any) -> BulkTable:
        if product_id == 18100007:
            raise ValueError("basket bulk unavailable in test")
        for table in tables.values():
            if table.product_id == product_id:
                return table
        raise ValueError(f"unknown product {product_id}")

    monkeypatch.setattr(backfill_mod, "fetch_bulk_table", fake_bulk)
    out = tmp_path / "backfill.json"
    assert main(["backfill", "--asof", ASOF, "--out", str(out), "--config", str(CONFIG)]) == 0
    raw = out.read_text(encoding="utf-8")
    assert "test-key" not in raw
    assert "api_key=" not in raw
    artifact = json.loads(raw)
    assert artifact["metadata"]["daily_count"] == 300
    assert artifact["metadata"]["cpi_count"] == 41
    assert artifact["daily"][0]["spreads_status"] == "ok"
    assert artifact["daily"][0]["row_digest"]
    assert artifact["cpi"][0]["row_digest"]
    expected = build_backfill_document(
        ASOF,
        artifact["daily"],
        artifact["cpi"],
        artifact["provenance"],
        artifact["exclusions"],
        artifact["retrieved_utc"],
    )
    assert json.loads(canonical_dumps(expected)) == artifact
    manifest = json.loads((tmp_path / "backfill-manifest.json").read_text(encoding="utf-8"))
    entry = manifest["files"]["backfill.json"]
    assert entry["sha256"] == sha256_text(raw)
    assert entry["bytes_utf8"] == len(raw.encode("utf-8"))


def test_backfill_parser_flags() -> None:
    """The backfill subcommand carries asof, out, and config flags."""
    args = build_parser().parse_args(["backfill", "--asof", ASOF, "--out", "history/backfill.json"])
    assert args.command == "backfill"
    assert args.asof == ASOF
    assert args.out == "history/backfill.json"
    assert args.config == "config/benchmark_map.yaml"


def test_backfill_config_failure_exits_2_with_no_write(tmp_path: Path) -> None:
    """A missing benchmark map exits 2 and writes nothing."""
    out = tmp_path / "backfill.json"
    assert run_backfill(ASOF, str(out), str(tmp_path / "missing.yaml")) == 2
    assert not out.exists()
    assert not (tmp_path / "backfill-manifest.json").exists()


def test_extract_table_months_merges_partial_tables() -> None:
    """Tables holding disjoint vector subsets merge instead of failing."""
    from goc_rates.backfill import _extract_table_months

    months = ["2026-07", "2026-08", "2026-09"]
    left = _component_zip(["101"], months)
    right = _component_zip(["102"], months)
    merged: dict[str, list[tuple[str, float]]] = {}
    for payload in (left, right):
        for vector, rows in _extract_table_months(payload, {"101", "102"}).items():
            merged[vector] = rows
    assert set(merged) == {"101", "102"}
    assert [month for month, _ in merged["101"]] == months


def _gapped_monthly_indexes() -> dict[str, list[tuple[str, float]]]:
    """Return two component series sharing Jan and Mar with Feb missing."""
    rows_a = [("2026-01", 100.0), ("2026-03", 100.4)]
    rows_b = [("2026-01", 200.0), ("2026-03", 200.6)]
    return {"comp_a": rows_a, "comp_b": rows_b}


def test_build_cpi_rows_rejects_gapped_months() -> None:
    """Jan beside Mar must fail instead of labeling a two month move as MoM."""
    import pytest

    from goc_rates.cpi.weights import WeightVintage
    from goc_rates.history import build_cpi_rows

    vintage = WeightVintage(2021, "2024-06", True)
    with pytest.raises(ValueError, match="consecutive"):
        build_cpi_rows(_gapped_monthly_indexes(), {"comp_a": 0.5, "comp_b": 0.5}, vintage)


def test_build_cpi_rows_accepts_year_boundary() -> None:
    """Dec beside Jan is consecutive and builds one MoM row."""
    from goc_rates.cpi.weights import WeightVintage
    from goc_rates.history import build_cpi_rows

    vintage = WeightVintage(2021, "2024-06", True)
    monthly = {
        "comp_a": [("2025-12", 100.0), ("2026-01", 100.2)],
        "comp_b": [("2025-12", 200.0), ("2026-01", 200.4)],
    }
    rows = build_cpi_rows(monthly, {"comp_a": 0.5, "comp_b": 0.5}, vintage)
    assert len(rows) == 1
    assert rows[0]["month"] == "2026-01"


def test_cpi_inputs_rejects_gapped_intersection() -> None:
    """A shared intersection that drops Feb must fail closed before row building."""
    import pytest

    from goc_rates.backfill import _cpi_inputs
    from goc_rates.cpi.components import ComponentSpec
    from goc_rates.cpi.weights import WeightVintage

    specs = (
        ComponentSpec("comp_a", "Label A", "101", 50.0, True, ("Basket A",), ("11111111",)),
        ComponentSpec("comp_b", "Label B", "102", 50.0, True, ("Basket B",), ("22222222",)),
    )
    weights = {"comp_a": 0.5, "comp_b": 0.5}
    vintage = WeightVintage(2021, "2024-06", True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        text = io.StringIO()
        writer = csv.writer(text)
        writer.writerow(["REF_DATE", "VECTOR", "VALUE"])
        for month, level_a in (
            ("2026-01-01", "100.0000"),
            ("2026-02-01", "100.2000"),
            ("2026-03-01", "100.4000"),
        ):
            writer.writerow([month, "101", level_a])
        for month, level_b in (("2026-01-01", "200.0000"), ("2026-03-01", "200.6000")):
            writer.writerow([month, "102", level_b])
        archive.writestr("data.csv", text.getvalue())
    tables = {"cpi_monthly": _bulk_table(18100004, buffer.getvalue())}
    with pytest.raises(ValueError, match="consecutive"):
        _cpi_inputs(specs, weights, vintage, tables, "2026-03")


def test_backfill_document_rejects_gapped_cpi_months() -> None:
    """A sealed document must reject CPI months that skip a calendar month."""
    import pytest

    from goc_rates.cpi.weights import WeightVintage
    from goc_rates.history import _row_digest as _digest
    from goc_rates.history import build_backfill_document, build_cpi_rows

    vintage = WeightVintage(2021, "2024-06", True)
    monthly = {
        "comp_a": [("2026-01", 100.0), ("2026-02", 100.2), ("2026-03", 100.4)],
        "comp_b": [("2026-01", 200.0), ("2026-02", 200.4), ("2026-03", 200.6)],
    }
    rows = build_cpi_rows(monthly, {"comp_a": 0.5, "comp_b": 0.5}, vintage)
    assert [row["month"] for row in rows] == ["2026-02", "2026-03"]
    gapped_bodies = [
        {key: value for key, value in rows[0].items() if key != "row_digest"},
        {key: value for key, value in rows[1].items() if key != "row_digest"},
    ]
    gapped_bodies[1]["month"] = "2026-04"
    sealed = [{**body, "row_digest": _digest(body)} for body in gapped_bodies]
    provenance = {
        "valet": {
            "source_url": "https://example.invalid/valet",
            "retrieved_utc": "2026-10-30T00:00:00+00:00",
            "vintage": "2026-10-30",
        }
    }
    daily_bodies: list[dict[str, object]] = []
    for day in _dates(250):
        daily_bodies.append(
            {
                "date": day,
                "yields_percent": {"2Y": 3.0, "5Y": 3.3, "10Y": 3.6, "30Y": 3.9},
                "yields_unit": "percent",
                "slopes_bp": {"2Y_5Y": 30.0, "2Y_10Y": 60.0, "5Y_30Y": 60.0, "10Y_30Y": 30.0},
                "slopes_unit": "basis_points",
                "spreads_bp": {"2Y": None, "5Y": None, "10Y": None, "30Y": None},
                "spreads_unit": "basis_points",
                "spreads_status": "missing",
                "switch_in_window": False,
                "switch_by_tenor": {"2Y": False, "5Y": False, "10Y": False, "30Y": False},
                "calendar_gap": False,
                "verified": False,
                "source": "derived:backfill_v1",
                "snapshot_sha256": None,
                "input_digest_sha256": None,
            }
        )
    daily = [{**body, "row_digest": _digest(body)} for body in daily_bodies]
    with pytest.raises(ValueError, match="consecutive"):
        build_backfill_document(
            "2026-10-30",
            daily,
            sealed,
            provenance,
            [],
            "2026-10-30T00:00:00+00:00",
        )
