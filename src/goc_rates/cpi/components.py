"""Pinned 55 component registry: every SA flag must be true."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from goc_rates.config import CpiConfig, load_cpi_config

EXPECTED_COMPONENT_COUNT = 55

DEFAULT_CPI_REGISTRY_PATH = Path("config/cpi_components.yaml")


@dataclass(frozen=True)
class ComponentSpec:
    """One pinned CPI component with its basket weight and SA assertion."""

    component_id: str
    label: str
    vector_id: str
    weight_percent: float
    seasonally_adjusted: bool
    basket_product_groups: tuple[str, ...]
    basket_vector_ids: tuple[str, ...]


def specs_from_config(config: CpiConfig) -> tuple[ComponentSpec, ...]:
    """Assert the registry shape and return frozen component specs.

    The engine reuses StatCan seasonally adjusted values as published, so
    every registry row must assert seasonally_adjusted true and the count
    must pin exactly 55 components. Basket product groups and vector ids
    must be parallel equal length and globally unique. Any drift fails closed.
    """
    if len(config.components) != EXPECTED_COMPONENT_COUNT:
        raise ValueError(
            f"CPI registry holds {len(config.components)} components, "
            f"expected exactly {EXPECTED_COMPONENT_COUNT}"
        )
    specs: list[ComponentSpec] = []
    seen_ids: set[str] = set()
    seen_vectors: set[str] = set()
    seen_basket_products: set[str] = set()
    seen_basket_vectors: set[str] = set()
    for component in config.components:
        if not component.seasonally_adjusted:
            raise ValueError(
                f"CPI component {component.component_id!r} must be "
                "seasonally adjusted: engine reuses StatCan SA values"
            )
        if component.component_id in seen_ids:
            raise ValueError(f"duplicate CPI component_id: {component.component_id!r}")
        if component.vector_id in seen_vectors:
            raise ValueError(f"duplicate CPI vector_id: {component.vector_id!r}")
        seen_ids.add(component.component_id)
        seen_vectors.add(component.vector_id)
        groups = tuple(component.basket_product_groups)
        vectors = tuple(component.basket_vector_ids)
        if not groups or not vectors:
            raise ValueError(f"CPI basket lists for {component.component_id!r} must be non empty")
        if len(groups) != len(vectors):
            raise ValueError(
                f"CPI basket lists for {component.component_id!r} must be parallel equal length"
            )
        for group, vector in zip(groups, vectors, strict=True):
            if not isinstance(group, str) or not group.strip():
                raise ValueError(
                    f"CPI basket product group for {component.component_id!r} "
                    "must be a non empty string"
                )
            if not isinstance(vector, str) or not vector.strip():
                raise ValueError(
                    f"CPI basket vector for {component.component_id!r} must be a non empty string"
                )
            if group in seen_basket_products:
                raise ValueError(f"duplicate CPI basket product group: {group!r}")
            if vector in seen_basket_vectors:
                raise ValueError(f"duplicate CPI basket vector id: {vector!r}")
            seen_basket_products.add(group)
            seen_basket_vectors.add(vector)
        specs.append(
            ComponentSpec(
                component_id=component.component_id,
                label=component.label,
                vector_id=component.vector_id,
                weight_percent=component.weight_percent,
                seasonally_adjusted=True,
                basket_product_groups=groups,
                basket_vector_ids=vectors,
            )
        )
    return tuple(specs)


def load_component_specs(
    path: str | Path = DEFAULT_CPI_REGISTRY_PATH,
) -> tuple[ComponentSpec, ...]:
    """Load the registry file and return asserted component specs."""
    return specs_from_config(load_cpi_config(path))
