"""Phase 4 highs: V21 recompute, basket parsing, product and published pins."""

from __future__ import annotations

import hashlib
import io
import zipfile
from typing import Any

import pytest

from goc_rates.config import load_cpi_config
from goc_rates.cpi.bulk import (
    BulkTable,
    extract_basket_weights,
)
from tests.cpi_fixtures import CPI_REGISTRY_PATH, build_demo_inflation


def _basket_zip(
    weights_by_product: dict[str, float],
    vectors_by_product: dict[str, str] | None = None,
    year: int = 2024,
) -> bytes:
    """Build an in memory basket weights zip using the live 18100007 schema.

    Keys are basket product groups with percent weights. Vectors default to
    distinct 8 digit ids, but callers pass the registry basket vectors so
    the slice carries real product group and vector pins with retained
    coordinates. Fields are CSV quoted so product commas survive.
    """
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


def _registry_weights() -> tuple[dict[str, float], dict[str, str]]:
    """Return registry vector weights plus component mapping."""
    config = load_cpi_config(CPI_REGISTRY_PATH)
    weights = {item.vector_id: item.weight_percent for item in config.components}
    mapping = {item.vector_id: item.component_id for item in config.components}
    assert len(weights) == 55
    return weights, mapping


def _matching_basket_slice(
    config: object,
) -> tuple[dict[str, float], dict[str, str]]:
    """Return basket product weights and vectors matching the registry.

    Each component aggregate splits its registry weight evenly across its
    mapped groups so the slice passes agreement. Exclusions get a small
    positive weight so they exist without affecting the component total.
    """
    from goc_rates.config import CpiConfig

    assert isinstance(config, CpiConfig)
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


def test_basket_weights_parse_matches_registry() -> None:
    """A basket zip matching the registry parses with the pinned vintage."""
    config = load_cpi_config(CPI_REGISTRY_PATH)
    weights_by_product, vectors_by_product = _matching_basket_slice(config)
    payload = _basket_zip(weights_by_product, vectors_by_product)
    basket = extract_basket_weights(payload, expenditure_year=2024, link_month="2025-05")
    assert basket.expenditure_year == 2024
    assert basket.link_month == "2025-05"
    from goc_rates.cpi.basket_map import check_basket_agreement

    aggregated = check_basket_agreement(config, basket)
    for component in config.components:
        assert aggregated[component.component_id] == pytest.approx(
            component.weight_percent, abs=1e-9
        )


def test_basket_weight_disagree_fails_closed() -> None:
    """A basket weight drifting beyond rounding tolerance fails closed."""
    from goc_rates.config import load_cpi_config
    from goc_rates.cpi.basket_map import component_tolerance
    from goc_rates.cpi.section import build_inflation_section_from_bulk

    config = load_cpi_config(CPI_REGISTRY_PATH)
    weights_by_product, vectors_by_product = _matching_basket_slice(config)
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
        digest = hashlib.sha256(payload).hexdigest()
        bulk[name] = BulkTable(
            product_id=product_id,
            zip_url=f"https://www150.statcan.gc.ca/n1/tbl/{name}.zip",
            zip_sha256=digest,
            retrieved_utc="2026-10-01T00:00:00Z",
            members=(),
            zip_bytes=payload,
        )
    with pytest.raises(ValueError, match="disagrees"):
        build_inflation_section_from_bulk(config, bulk, "2026-10-01T00:00:00Z")


def test_basket_link_month_pin_validated() -> None:
    """The caller pinned link month is validated and carried to the result."""
    config = load_cpi_config(CPI_REGISTRY_PATH)
    weights_by_product, vectors_by_product = _matching_basket_slice(config)
    payload = _basket_zip(weights_by_product, vectors_by_product)
    basket = extract_basket_weights(payload, expenditure_year=2024, link_month="2025-05")
    assert basket.link_month == "2025-05"
    with pytest.raises(ValueError, match="link_month"):
        extract_basket_weights(payload, expenditure_year=2024, link_month="2025-13")


def _demo_snapshot() -> dict[str, Any]:
    """Build a snapshot carrying the demo inflation section."""
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


def test_v21_scaling_together_still_fails() -> None:
    """Scaling stored contributions and the stored total together still fails V21."""
    snapshot = _demo_snapshot()
    inflation = snapshot["observations"]["inflation"]
    assert isinstance(inflation, dict)
    contributions = inflation["contributions"]
    assert isinstance(contributions, list)
    for row in contributions:
        assert isinstance(row, dict)
        row["contribution_pp"] = float(row["contribution_pp"]) * 2.0
    inflation["total_contribution_pp"] = float(inflation["total_contribution_pp"]) * 2.0
    headline = inflation["headline_mom"]
    assert isinstance(headline, dict)
    headline["value"] = float(headline["value"]) * 2.0
    assert _check(snapshot, "V21")["passed"] is False


def test_v21_rate_edit_without_contribution_fails() -> None:
    """Editing a monthly rate without its contribution fails V21."""
    snapshot = _demo_snapshot()
    inflation = snapshot["observations"]["inflation"]
    assert isinstance(inflation, dict)
    contributions = inflation["contributions"]
    assert isinstance(contributions, list)
    first = contributions[0]
    assert isinstance(first, dict)
    first["monthly_rate_percent"] = float(first["monthly_rate_percent"]) + 1.0
    assert _check(snapshot, "V21")["passed"] is False


def test_v21_weight_edit_without_contribution_fails() -> None:
    """Editing a weight without its contribution fails V21."""
    snapshot = _demo_snapshot()
    inflation = snapshot["observations"]["inflation"]
    assert isinstance(inflation, dict)
    contributions = inflation["contributions"]
    assert isinstance(contributions, list)
    first = contributions[0]
    assert isinstance(first, dict)
    first["weight_percent"] = float(first["weight_percent"]) + 10.0
    assert _check(snapshot, "V21")["passed"] is False


def test_v20_median_component_mismatch_fails() -> None:
    """A median component naming the wrong row fails V20."""
    snapshot = _demo_snapshot()
    inflation = snapshot["observations"]["inflation"]
    assert isinstance(inflation, dict)
    latest = inflation["latest"]
    assert isinstance(latest, dict)
    contributions = inflation["contributions"]
    assert isinstance(contributions, list)
    other = contributions[1]
    assert isinstance(other, dict)
    latest["median_component"] = other["component_id"]
    assert _check(snapshot, "V20")["passed"] is False


def test_v20_history_yoy_tamper_fails() -> None:
    """A history YoY moved by 5bp fails the 0.01 recompute in V20."""
    snapshot = _demo_snapshot()
    inflation = snapshot["observations"]["inflation"]
    assert isinstance(inflation, dict)
    history = inflation["history"]
    assert isinstance(history, list)
    last = history[-1]
    assert isinstance(last, dict)
    last["trim_yoy_percent"] = float(last["trim_yoy_percent"]) + 0.05
    assert _check(snapshot, "V20")["passed"] is False


def test_duplicate_vector_id_rejected() -> None:
    """A registry with a repeated vector id fails closed on load."""
    import copy
    import tempfile
    from pathlib import Path

    import yaml

    from goc_rates.config import CpiComponent, CpiConfig, CpiWeightVintage, load_cpi_config
    from goc_rates.cpi.components import specs_from_config

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
    with pytest.raises(ValueError, match="duplicate.*vector"):
        specs_from_config(drifted)
    raw = yaml.safe_load(CPI_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    duped = copy.deepcopy(raw)
    assert isinstance(duped, dict)
    components = duped["components"]
    assert isinstance(components, list)
    second = components[1]
    assert isinstance(second, dict)
    second["vector_id"] = components[0]["vector_id"]
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
        yaml.safe_dump(duped, handle)
        temp_path = Path(handle.name)
    try:
        with pytest.raises(ValueError, match="duplicate.*vector"):
            load_cpi_config(temp_path)
    finally:
        temp_path.unlink()


def test_product_id_grammar_rejects_ten_digit() -> None:
    """Ten digit bulk ids fail the 8 digit grammar."""
    from goc_rates.cpi.bulk import bulk_link_url

    with pytest.raises(ValueError, match="8 digit"):
        bulk_link_url(1810000401)
    assert bulk_link_url(18100004).endswith("/18100004/en")


def test_published_old_keys_rejected() -> None:
    """Old YoY published keys fail closed in favour of index pins."""
    import copy

    import yaml

    raw = yaml.safe_load(CPI_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    tampered = copy.deepcopy(raw)
    assert isinstance(tampered, dict)
    published = tampered["published"]
    assert isinstance(published, dict)
    published["trim_yoy_vector_id"] = published.pop("trim_index_vector_id")
    import tempfile
    from pathlib import Path

    from goc_rates.config import load_cpi_config

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
        yaml.safe_dump(tampered, handle)
        temp_path = Path(handle.name)
    try:
        with pytest.raises(ValueError, match="published keys"):
            load_cpi_config(temp_path)
    finally:
        temp_path.unlink()
