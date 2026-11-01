"""Basket mapping tests: one to many pass with seven fail closed rules."""

from __future__ import annotations

import io
import zipfile

import pytest

from goc_rates.config import BasketExclusion, CpiComponent, CpiConfig, CpiWeightVintage
from goc_rates.cpi.basket_map import (
    aggregate_basket_weights,
    check_basket_agreement,
    component_tolerance,
    normalize_product_group,
)
from goc_rates.cpi.bulk import BasketRow, BasketWeights


def _basket_weights(rows: list[tuple[str, str, str, float]]) -> BasketWeights:
    """Build a basket slice from product, vector, coordinate, weight rows."""
    weights = {vector: weight for _, vector, _, weight in rows}
    return BasketWeights(
        expenditure_year=2024,
        link_month="2025-05",
        weights_percent=dict(weights),
        rows=tuple(
            BasketRow(product=product, vector=vector, coordinate=coord, weight_percent=weight)
            for product, vector, coord, weight in rows
        ),
    )


def _config(
    components: list[tuple[str, float, list[tuple[str, str]]]],
    exclusions: list[tuple[str, str, str]] | None = None,
) -> CpiConfig:
    """Build a minimal registry with basket mappings for tests."""
    comps = tuple(
        CpiComponent(
            component_id=cid,
            label=cid,
            vector_id=f"{90000000 + idx:08d}",
            weight_percent=weight,
            seasonally_adjusted=True,
            basket_product_groups=tuple(group for group, _ in groups),
            basket_vector_ids=tuple(vector for _, vector in groups),
        )
        for idx, (cid, weight, groups) in enumerate(components)
    )
    excl = tuple(
        BasketExclusion(product_group=prod, vector_id=vec, reason=reason)
        for prod, vec, reason in (exclusions or [])
    )
    return CpiConfig(
        schema_version=2,
        weight_vintage=CpiWeightVintage(2024, "2025-05", True),
        product_ids={
            "cpi_monthly": 18100004,
            "core_statistics": 18100256,
            "basket_weights": 18100007,
        },
        components=comps,
        published={
            "trim_index_vector_id": "41691028",
            "median_index_vector_id": "41691029",
        },
        basket_exclusions=excl,
    )


def test_normalize_product_group() -> None:
    """NFKC plus casefold plus whitespace collapse canonicalizes names."""
    assert normalize_product_group("  Fresh   Beef ") == "fresh beef"
    assert normalize_product_group("Caf\u00e9") == normalize_product_group("caf\u00e9")
    with pytest.raises(ValueError):
        normalize_product_group("   ")


def test_tolerance_n1_n2_and_cap() -> None:
    """Single group allows 0.01, two groups allow 0.015, wide maps cap at 0.03."""
    assert component_tolerance(1) == pytest.approx(0.01)
    assert component_tolerance(2) == pytest.approx(0.015)
    assert component_tolerance(5) == pytest.approx(0.03)
    assert component_tolerance(20) == pytest.approx(0.03)


def test_one_many_pass() -> None:
    """Six meat cuts summing to the registry weight pass agreement."""
    groups = [
        ("Fresh or frozen beef", "91858748", "1.6.1.1", 0.50),
        ("Fresh or frozen pork", "91858750", "1.7.1.1", 0.19),
        ("Other fresh or frozen meat", "91858752", "1.8.1.1", 0.06),
        ("Fresh or frozen chicken", "91858756", "1.10.1.1", 0.38),
        ("Other fresh or frozen poultry", "91858758", "1.11.1.1", 0.06),
        ("Processed meat", "91858760", "1.12.1.1", 0.21),
    ]
    assert sum(weight for _, _, _, weight in groups) == pytest.approx(1.40)
    config = _config(
        [
            ("C01", 1.40, [(prod, vec) for prod, vec, _, _ in groups]),
            ("C02", 98.60, [("Rest", "99999999")]),
        ],
        exclusions=[],
    )
    basket = _basket_weights(
        [(prod, vec, coord, weight) for prod, vec, coord, weight in groups]
        + [("Rest", "99999999", "1.200.1.1", 98.60)]
    )
    aggregated = aggregate_basket_weights(config, basket)
    assert aggregated["C01"] == pytest.approx(1.40)
    assert check_basket_agreement(config, basket)["C01"] == pytest.approx(1.40)


def test_shortfall_057_fails() -> None:
    """A single Meat aggregate at 1.83 against registry 2.40 fails closed."""
    config = _config([("C01", 2.40, [("Meat", "91858744")])], exclusions=[])
    basket = _basket_weights([("Meat", "91858744", "1.4.1.1", 1.83)])
    with pytest.raises(ValueError, match="disagrees"):
        check_basket_agreement(config, basket)


def test_ancestor_child_fails() -> None:
    """Mapping both an ancestor coordinate and its child fails closed."""
    config = _config(
        [("C01", 1.00, [("Parent", "11111111"), ("Child", "22222222")])],
        exclusions=[],
    )
    basket = _basket_weights(
        [("Parent", "11111111", "1", 0.50), ("Child", "22222222", "1.1", 0.50)]
    )
    with pytest.raises(ValueError, match="ancestor|descendant"):
        aggregate_basket_weights(config, basket)


def test_missing_fails() -> None:
    """A mapped product group absent from the slice fails closed."""
    config = _config([("C01", 1.00, [("Ghost", "11111111")])], exclusions=[])
    basket = _basket_weights([("Other", "22222222", "1.2.1.1", 1.00)])
    with pytest.raises(ValueError, match="missing"):
        aggregate_basket_weights(config, basket)


def test_unexplained_fails() -> None:
    """A basket product neither mapped nor excluded fails closed."""
    config = _config([("C01", 1.00, [("Mapped", "11111111")])], exclusions=[])
    basket = _basket_weights(
        [("Mapped", "11111111", "1.2.1.1", 1.00), ("Rogue", "22222222", "1.3.1.1", 0.50)]
    )
    with pytest.raises(ValueError, match="unexplained"):
        check_basket_agreement(config, basket)


def test_stale_exclusion_fails() -> None:
    """An exclusion absent from the slice fails closed."""
    config = _config(
        [("C01", 100.00, [("Mapped", "11111111")])],
        exclusions=[("Ghost", "22222222", "aggregate")],
    )
    basket = _basket_weights([("Mapped", "11111111", "1.2.1.1", 100.00)])
    with pytest.raises(ValueError, match="stale"):
        check_basket_agreement(config, basket)


def test_total_100_fails() -> None:
    """Ten components each 0.006 under pass per component but fail the total."""
    components: list[tuple[str, float, list[tuple[str, str]]]] = []
    rows: list[tuple[str, str, str, float]] = []
    for idx in range(10):
        prod = f"Group {idx}"
        vec = f"{50000000 + idx:08d}"
        components.append((f"C{idx:02d}", 10.00, [(prod, vec)]))
        rows.append((prod, vec, f"1.{idx + 10}.1.1", 9.994))
    config = _config(components, exclusions=[])
    basket = _basket_weights(rows)
    with pytest.raises(ValueError, match="sum to"):
        check_basket_agreement(config, basket)


def _basket_zip_bytes(rows: list[tuple[str, str, str, str]]) -> bytes:
    """Build a basket zip from product, vector, coordinate, value strings."""
    header = (
        "REF_DATE,GEO,DGUID,Products and product groups,"
        "Price period of weight,Geographic distribution of weight,"
        "UOM,UOM_ID,SCALAR_FACTOR,SCALAR_ID,VECTOR,COORDINATE,"
        "VALUE,STATUS,SYMBOL,TERMINATED,DECIMALS"
    )
    lines = [header]
    for product, vector, coordinate, value in rows:
        lines.append(
            f"2024,Canada,2016A000011124,{product},"
            "Weight at basket link month prices,"
            "Distribution to selected geographies,"
            f"Percent,239,units,0,{vector},{coordinate},{value},,,,"
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("basket.csv", "\n".join(lines).encode("utf-8"))
    return buffer.getvalue()


def test_bulk_rejects_duplicate_products() -> None:
    """Two rows sharing one product group fail closed."""
    from goc_rates.cpi.bulk import extract_basket_weights

    payload = _basket_zip_bytes(
        [
            ("Meat", "91858744", "1.4.1.1", "1.87"),
            ("Meat", "91858748", "1.6.1.1", "0.50"),
        ]
    )
    with pytest.raises(ValueError, match="repeats product"):
        extract_basket_weights(payload, expenditure_year=2024, link_month="2025-05")


def test_bulk_rejects_duplicate_coordinates() -> None:
    """Two rows sharing one coordinate fail closed."""
    from goc_rates.cpi.bulk import extract_basket_weights

    payload = _basket_zip_bytes(
        [
            ("Meat", "91858744", "1.4.1.1", "1.87"),
            ("Beef", "91858748", "1.4.1.1", "0.50"),
        ]
    )
    with pytest.raises(ValueError, match="repeats coordinate"):
        extract_basket_weights(payload, expenditure_year=2024, link_month="2025-05")


def test_bulk_rejects_bad_coordinate() -> None:
    """A coordinate outside the dotted numeric grammar fails closed."""
    from goc_rates.cpi.bulk import extract_basket_weights

    payload = _basket_zip_bytes([("Meat", "91858744", "1..a", "1.87")])
    with pytest.raises(ValueError, match="coordinate"):
        extract_basket_weights(payload, expenditure_year=2024, link_month="2025-05")
