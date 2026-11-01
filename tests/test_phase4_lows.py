"""Phase 4 lows: understated bulk sizes, product pins, duplicates, and history."""

from __future__ import annotations

import hashlib
import io
import zipfile
from typing import Any

import pytest

from goc_rates.config import load_cpi_config
from goc_rates.cpi.bulk import BulkTable, assemble_bulk_table
from tests.cpi_fixtures import CPI_REGISTRY_PATH, build_demo_inflation


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    """Build an in memory zip archive from member bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _demo_snapshot() -> dict[str, Any]:
    """Build a snapshot carrying only the demo inflation section."""
    section, entry = build_demo_inflation()
    return {
        "metadata": {"snapshot_date": "2026-09-30", "schema_version": 1},
        "observations": {"inflation": section},
        "provenance": {"statcan_cpi": entry},
    }


def _check(snapshot: dict[str, Any], check_id: str) -> Any:
    """Return one check result by id."""
    from goc_rates.verify import verify_snapshot

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


def test_bulk_declared_size_understates_streamed_size_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A declared member size below the streamed bytes still fails closed."""
    import goc_rates.cpi.bulk as bulk_mod

    content = b"x" * 50
    payload = _zip_bytes({"m.csv": content})
    real_infos = zipfile.ZipFile(io.BytesIO(payload)).infolist()
    assert len(real_infos) == 1
    understated = zipfile.ZipInfo(real_infos[0].filename)
    understated.file_size = 5
    understated.compress_size = 5

    def _fake_infolist(self: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
        return [understated]

    monkeypatch.setattr(zipfile.ZipFile, "infolist", _fake_infolist)
    monkeypatch.setattr(bulk_mod, "MAX_BULK_MEMBER_BYTES", 20)
    with pytest.raises(ValueError, match="cap"):
        assemble_bulk_table(
            18100004,
            "https://www150.statcan.gc.ca/n1/tbl/fulltable.zip",
            payload,
            "2026-10-01T00:00:00Z",
        )


def test_v21_scaled_contributions_and_total_together_fails() -> None:
    """Scaling every stored contribution and the total together still fails V21."""
    snapshot = _demo_snapshot()
    inflation = _inflation(snapshot)
    contributions = inflation["contributions"]
    assert isinstance(contributions, list)
    for row in contributions:
        assert isinstance(row, dict)
        row["contribution_pp"] = float(row["contribution_pp"]) * 1.5
    inflation["total_contribution_pp"] = float(inflation["total_contribution_pp"]) * 1.5
    headline = inflation["headline_mom"]
    assert isinstance(headline, dict)
    headline["value"] = float(headline["value"]) * 1.5
    assert _check(snapshot, "V21")["passed"] is False


def test_product_id_999_fails_v19() -> None:
    """A three digit product id breaks the eight digit grammar in V19."""
    snapshot = _demo_snapshot()
    bulk = _inflation(snapshot)["bulk"]
    assert isinstance(bulk, dict)
    entry = bulk["cpi_monthly"]
    assert isinstance(entry, dict)
    entry["product_id"] = 999
    assert _check(snapshot, "V19")["passed"] is False


def test_product_id_999_fails_v22() -> None:
    """A three digit product id breaks the bulk pin in V22 as well."""
    snapshot = _demo_snapshot()
    bulk = _inflation(snapshot)["bulk"]
    assert isinstance(bulk, dict)
    entry = bulk["cpi_monthly"]
    assert isinstance(entry, dict)
    entry["product_id"] = 999
    assert _check(snapshot, "V22")["passed"] is False


def test_duplicate_contribution_component_id_fails_v20_and_v21() -> None:
    """A repeated contribution component id fails the V20 and V21 recomputes."""
    snapshot = _demo_snapshot()
    contributions = _inflation(snapshot)["contributions"]
    assert isinstance(contributions, list)
    first = contributions[0]
    second = contributions[1]
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    second["component_id"] = first["component_id"]
    assert _check(snapshot, "V20")["passed"] is False
    assert _check(snapshot, "V21")["passed"] is False


def test_duplicate_vector_id_rejected_from_specs() -> None:
    """A registry with one repeated vector id fails closed on load."""
    from goc_rates.config import CpiComponent, CpiConfig, CpiWeightVintage

    config = load_cpi_config(CPI_REGISTRY_PATH)
    tampered = tuple(
        CpiComponent(
            component_id=item.component_id,
            label=item.label,
            vector_id=config.components[0].vector_id,
            weight_percent=item.weight_percent,
            seasonally_adjusted=item.seasonally_adjusted,
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
    from goc_rates.cpi.components import specs_from_config

    with pytest.raises(ValueError, match="duplicate.*vector"):
        specs_from_config(drifted)


def _basket_zip(
    weights_by_product: dict[str, float],
    vectors_by_product: dict[str, str] | None = None,
    year: int = 2024,
) -> bytes:
    """Build an in memory basket weights zip using the live 18100007 schema."""
    import csv as csv_mod

    vectors = vectors_by_product or {}
    output = io.StringIO()
    writer = csv_mod.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "REF_DATE",
            "GEO",
            "DGUID",
            "Products and product groups",
            "Price period of weight",
            "Geographic distribution of weight",
            "UOM",
            "UOM_ID",
            "SCALAR_FACTOR",
            "SCALAR_ID",
            "VECTOR",
            "COORDINATE",
            "VALUE",
            "STATUS",
            "SYMBOL",
            "TERMINATED",
            "DECIMALS",
        ]
    )
    for position, product in enumerate(sorted(weights_by_product.keys())):
        vector = vectors.get(product, f"{40000000 + position:08d}")
        writer.writerow(
            [
                str(year),
                "Canada",
                "2016A000011124",
                product,
                "Weight at basket link month prices",
                "Distribution to selected geographies",
                "Percent",
                "239",
                "units",
                "0",
                vector,
                f"1.{position + 1}.1.1",
                str(weights_by_product[product]),
                "",
                "",
                "",
                "",
            ]
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("basket-weights.csv", output.getvalue().encode("utf-8"))
    return buffer.getvalue()


def _registry_weights() -> dict[str, float]:
    """Return registry vector weights in percent."""
    config = load_cpi_config(CPI_REGISTRY_PATH)
    return {item.vector_id: item.weight_percent for item in config.components}


def _matching_basket_slice() -> tuple[dict[str, float], dict[str, str]]:
    """Return basket product weights and vectors matching the registry."""
    config = load_cpi_config(CPI_REGISTRY_PATH)
    weights_by_product: dict[str, float] = {}
    vectors_by_product: dict[str, str] = {}
    for component in config.components:
        groups = list(component.basket_product_groups)
        vectors = list(component.basket_vector_ids)
        share = float(component.weight_percent) / float(len(groups))
        for group, vector in zip(groups, vectors, strict=True):
            weights_by_product[group] = share
            vectors_by_product[group] = vector
    for exclusion in config.basket_exclusions:
        weights_by_product[exclusion.product_group] = 0.01
        vectors_by_product[exclusion.product_group] = exclusion.vector_id
    return weights_by_product, vectors_by_product


def test_basket_expenditure_year_disagree_fails_closed() -> None:
    """A basket vintage year differing from the registry fails closed."""
    from goc_rates.cpi.section import build_inflation_section_from_bulk

    config = load_cpi_config(CPI_REGISTRY_PATH)
    weights_by_product, vectors_by_product = _matching_basket_slice()
    basket_bytes = _basket_zip(weights_by_product, vectors_by_product, year=2023)
    bulk: dict[str, BulkTable] = {}
    for name, product_id in (
        ("cpi_monthly", 18100004),
        ("core_statistics", 18100256),
        ("basket_weights", 18100007),
    ):
        payload = basket_bytes if name == "basket_weights" else b"dummy"
        bulk[name] = BulkTable(
            product_id=product_id,
            zip_url=f"https://www150.statcan.gc.ca/n1/tbl/{name}.zip",
            zip_sha256=hashlib.sha256(payload).hexdigest(),
            retrieved_utc="2026-10-01T00:00:00Z",
            members=(),
            zip_bytes=payload,
        )
    with pytest.raises(ValueError, match="expenditure year"):
        build_inflation_section_from_bulk(config, bulk, "2026-10-01T00:00:00Z")


def test_basket_weight_disagree_fails_closed() -> None:
    """A basket weight beyond rounding tolerance fails closed."""
    from goc_rates.cpi.basket_map import component_tolerance
    from goc_rates.cpi.section import build_inflation_section_from_bulk

    config = load_cpi_config(CPI_REGISTRY_PATH)
    weights_by_product, vectors_by_product = _matching_basket_slice()
    first_component = config.components[0]
    first_group = first_component.basket_product_groups[0]
    tolerance = component_tolerance(len(first_component.basket_product_groups))
    weights_by_product[first_group] = weights_by_product[first_group] + tolerance + 0.05
    basket_bytes = _basket_zip(weights_by_product, vectors_by_product)
    bulk: dict[str, BulkTable] = {}
    for name, product_id in (
        ("cpi_monthly", 18100004),
        ("core_statistics", 18100256),
        ("basket_weights", 18100007),
    ):
        payload = basket_bytes if name == "basket_weights" else b"dummy"
        bulk[name] = BulkTable(
            product_id=product_id,
            zip_url=f"https://www150.statcan.gc.ca/n1/tbl/{name}.zip",
            zip_sha256=hashlib.sha256(payload).hexdigest(),
            retrieved_utc="2026-10-01T00:00:00Z",
            members=(),
            zip_bytes=payload,
        )
    with pytest.raises(ValueError, match="disagrees"):
        build_inflation_section_from_bulk(config, bulk, "2026-10-01T00:00:00Z")


def test_median_mom_only_tamper_fails_v20() -> None:
    """A median mom moved alone by 5bp fails the V20 recompute."""
    snapshot = _demo_snapshot()
    latest = _inflation(snapshot)["latest"]
    assert isinstance(latest, dict)
    median_mom = latest["median_mom"]
    assert isinstance(median_mom, dict)
    median_mom["value"] = float(median_mom["value"]) + 0.05
    assert _check(snapshot, "V20")["passed"] is False


def test_history_median_yoy_tamper_fails_v20() -> None:
    """A history median YoY moved by 5bp fails the V20 recompute."""
    snapshot = _demo_snapshot()
    history = _inflation(snapshot)["history"]
    assert isinstance(history, list)
    last = history[-1]
    assert isinstance(last, dict)
    last["median_yoy_percent"] = float(last["median_yoy_percent"]) + 0.05
    assert _check(snapshot, "V20")["passed"] is False


def test_latest_trim_yoy_tamper_fails_v20() -> None:
    """A latest trim YoY moved by 5bp fails the trailing compound check."""
    snapshot = _demo_snapshot()
    latest = _inflation(snapshot)["latest"]
    assert isinstance(latest, dict)
    trim_yoy = latest["trim_yoy"]
    assert isinstance(trim_yoy, dict)
    trim_yoy["value"] = float(trim_yoy["value"]) + 0.05
    assert _check(snapshot, "V20")["passed"] is False
