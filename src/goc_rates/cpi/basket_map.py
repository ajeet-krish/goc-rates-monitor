"""Basket mapping: aggregate 18100007 product groups per registry component.

The 55 registry index vectors (41690973 and friends) never appear in the
18100007 basket member. The basket member carries its own product vectors
(91858744 classic 8 digit plus 10 digit extended ids) with product group
names, coordinates, and percent weights at link month prices. This module
sums the mapped basket groups per component, validates the partition as an
antichain, and compares each aggregate against the pinned registry weight.
"""

from __future__ import annotations

import unicodedata

from goc_rates.config import CpiConfig
from goc_rates.cpi.bulk import BasketWeights

BASKET_TOLERANCE_SLOPE = 0.005
BASKET_TOLERANCE_CAP = 0.03
BASKET_TOTAL_TOLERANCE_PP = 0.05


def normalize_product_group(name: str) -> str:
    """Return the canonical basket product group key.

    NFKC normalizes compatibility forms, casefold handles case, and
    whitespace collapses so registry pins match bulk CSV cells.
    """
    if not isinstance(name, str):
        raise ValueError("product group name must be a string")
    normalized = unicodedata.normalize("NFKC", name)
    collapsed = " ".join(normalized.casefold().split())
    if not collapsed:
        raise ValueError("product group name must be non empty")
    return collapsed


def component_tolerance(num_groups: int) -> float:
    """Return the per component tolerance in percentage points.

    Tolerance grows as 0.005 times (n plus 1) with a 0.03 cap, so a
    single group allows 0.01, two groups allow 0.015, and wide
    partitions cap at 0.03.
    """
    if isinstance(num_groups, bool) or not isinstance(num_groups, int):
        raise ValueError("num_groups must be an integer")
    if num_groups < 1:
        raise ValueError("num_groups must be at least one")
    return min(BASKET_TOLERANCE_SLOPE * float(num_groups + 1), BASKET_TOLERANCE_CAP)


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    """Return true when one coordinate is a dot boundary prefix of the other."""
    if ancestor == descendant:
        return True
    ancestor_parts = ancestor.split(".")
    descendant_parts = descendant.split(".")
    if len(ancestor_parts) >= len(descendant_parts):
        return False
    return descendant_parts[: len(ancestor_parts)] == ancestor_parts


def aggregate_basket_weights(
    config: CpiConfig,
    basket: BasketWeights,
) -> dict[str, float]:
    """Sum mapped basket groups per component, validating the partition.

    Every mapped product group must exist in the basket slice, every mapped
    vector must match the basket vector for that product, coordinates must
    form an antichain with no ancestor or descendant pair, and no basket
    product may map twice. Exclusions are not summed here. Any drift fails
    closed.
    """
    by_product: dict[str, tuple[str, str, float]] = {}
    for row in basket.rows:
        key = normalize_product_group(row.product)
        if key in by_product:
            raise ValueError(f"basket slice repeats product group {row.product!r}")
        by_product[key] = (row.vector, row.coordinate, row.weight_percent)
    aggregated: dict[str, float] = {}
    used_coordinates: list[tuple[str, str, str]] = []
    for component in config.components:
        groups = list(component.basket_product_groups)
        vectors = list(component.basket_vector_ids)
        if len(groups) != len(vectors) or not groups:
            raise ValueError(
                f"basket mapping for {component.component_id!r} must be "
                "parallel equal length and non empty"
            )
        total = 0.0
        for group, expected_vector in zip(groups, vectors, strict=True):
            key = normalize_product_group(group)
            if key not in by_product:
                raise ValueError(
                    f"basket mapping for {component.component_id!r} "
                    f"is missing product group {group!r}"
                )
            actual_vector, coordinate, weight = by_product[key]
            if actual_vector != expected_vector.strip():
                raise ValueError(
                    f"basket vector for {group!r} {actual_vector!r} "
                    f"must pin {expected_vector.strip()!r}"
                )
            total += float(weight)
            used_coordinates.append((coordinate, component.component_id, group))
        aggregated[component.component_id] = total
    for coordinate, component_id, group in used_coordinates:
        for other_coordinate, other_component, other_group in used_coordinates:
            if coordinate == other_coordinate and (component_id, group) != (
                other_component,
                other_group,
            ):
                raise ValueError(
                    f"basket coordinates repeat {coordinate!r} for {group!r} and {other_group!r}"
                )
    for i, (coordinate, component_id, group) in enumerate(used_coordinates):
        for j, (other_coordinate, other_component, other_group) in enumerate(used_coordinates):
            if i == j:
                continue
            if _is_ancestor(coordinate, other_coordinate) or _is_ancestor(
                other_coordinate, coordinate
            ):
                if coordinate != other_coordinate:
                    raise ValueError(
                        f"basket mapping for {component_id!r} group {group!r} "
                        f"overlaps ancestor or descendant {other_group!r} "
                        f"in {other_component!r}"
                    )
    return aggregated


def check_basket_agreement(
    config: CpiConfig,
    basket: BasketWeights,
) -> dict[str, float]:
    """Validate the full basket agreement across seven fail closed rules.

    Rules: vintage matches the registry, every mapped group exists with its
    pinned vector, coordinates form an antichain, each per component sum
    matches the registry within 0.005 times (n plus 1) capped at 0.03, every
    unmapped basket product is a pinned exclusion, every exclusion exists in
    the basket slice, and the component aggregates total 100 within 0.05.
    Returns the per component aggregates on success and raises otherwise.
    """
    if basket.expenditure_year != config.weight_vintage.expenditure_year:
        raise ValueError(
            f"basket expenditure year {basket.expenditure_year} "
            f"must pin {config.weight_vintage.expenditure_year}"
        )
    if basket.link_month != config.weight_vintage.link_month:
        raise ValueError(
            f"basket link month {basket.link_month!r} must pin {config.weight_vintage.link_month!r}"
        )
    aggregated = aggregate_basket_weights(config, basket)
    for component in config.components:
        expected = float(component.weight_percent)
        actual = float(aggregated[component.component_id])
        tolerance = component_tolerance(len(component.basket_product_groups))
        if abs(actual - expected) > tolerance:
            raise ValueError(
                f"basket aggregate for {component.component_id!r} {actual:.4f} "
                f"disagrees with registry {expected:.4f} "
                f"beyond {tolerance:.4f} pp"
            )
    by_product: dict[str, str] = {}
    for row in basket.rows:
        by_product[normalize_product_group(row.product)] = row.product
    mapped_keys = {
        normalize_product_group(group)
        for component in config.components
        for group in component.basket_product_groups
    }
    exclusion_keys: dict[str, str] = {}
    for exclusion in config.basket_exclusions:
        key = normalize_product_group(exclusion.product_group)
        if key in exclusion_keys:
            raise ValueError(f"basket exclusion repeats product group {exclusion.product_group!r}")
        exclusion_keys[key] = exclusion.product_group
    for key in mapped_keys:
        if key not in by_product:
            raise ValueError(f"basket slice is missing mapped product group {key!r}")
    for key in exclusion_keys:
        if key not in by_product:
            raise ValueError(
                f"basket exclusion {exclusion_keys[key]!r} is stale: absent from the basket slice"
            )
    unexplained = sorted(
        original
        for key, original in by_product.items()
        if key not in mapped_keys and key not in exclusion_keys
    )
    if unexplained:
        raise ValueError(
            f"basket slice holds {len(unexplained)} unexplained product groups, "
            f"first is {unexplained[0]!r}"
        )
    total = sum(aggregated.values())
    if abs(total - 100.0) > BASKET_TOTAL_TOLERANCE_PP:
        raise ValueError(
            f"basket component aggregates sum to {total:.4f}, "
            f"expected 100.00 within {BASKET_TOTAL_TOLERANCE_PP}"
        )
    return aggregated
