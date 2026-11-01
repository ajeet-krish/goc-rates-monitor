"""Benchmark map loading with label assertion support."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

EXPECTED_SCHEMA_VERSION = 1

SERIES_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class BenchmarkEntry:
    """One benchmark tenor with Valet and FRED identifiers."""

    tenor: str
    valet_series_id: str
    valet_label: str
    fred_series_id: str
    comparator_label: str
    legacy_v_code: str | None


@dataclass(frozen=True)
class BenchmarkMap:
    """Parsed benchmark map with schema version and entries."""

    schema_version: int
    benchmarks: dict[str, BenchmarkEntry]
    statcan_indicators: list[str]


def load_benchmark_map(path: str | Path) -> BenchmarkMap:
    """Load and validate the benchmark map, failing closed on drift."""
    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError(f"benchmark map not found: {file_path}")
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("benchmark map root must be a mapping")
    schema_version = raw.get("schema_version")
    if schema_version != EXPECTED_SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {schema_version!r}")
    raw_benchmarks = raw.get("benchmarks")
    if not isinstance(raw_benchmarks, dict) or not raw_benchmarks:
        raise ValueError("benchmark map needs a non empty benchmarks mapping")
    benchmarks: dict[str, BenchmarkEntry] = {}
    for tenor, item in raw_benchmarks.items():
        if not isinstance(item, dict):
            raise ValueError(f"benchmark entry for {tenor!r} must be a mapping")
        for key in ("valet_series_id", "fred_series_id"):
            if key not in item or not isinstance(item[key], str) or not item[key].strip():
                raise ValueError(f"benchmark entry for {tenor!r} needs a non empty {key}")
            if not SERIES_ID_PATTERN.match(item[key].strip()):
                raise ValueError(
                    f"benchmark entry for {tenor!r} has an invalid {key}: {item[key]!r}"
                )
        for key in ("valet_label", "comparator_label"):
            if key not in item or not isinstance(item[key], str) or not item[key].strip():
                raise ValueError(f"benchmark entry for {tenor!r} needs a non empty {key}")
        legacy = item.get("legacy_v_code")
        if legacy is not None and not isinstance(legacy, str):
            raise ValueError(f"legacy_v_code for {tenor!r} must be a string or null")
        benchmarks[str(tenor)] = BenchmarkEntry(
            tenor=str(tenor),
            valet_series_id=item["valet_series_id"].strip(),
            valet_label=item["valet_label"].strip(),
            fred_series_id=item["fred_series_id"].strip(),
            comparator_label=item["comparator_label"].strip(),
            legacy_v_code=legacy.strip() if isinstance(legacy, str) and legacy.strip() else None,
        )
    raw_indicators = raw.get("statcan_indicators", [])
    if not isinstance(raw_indicators, list):
        raise ValueError("statcan_indicators must be a list")
    indicators: list[str] = []
    for indicator in raw_indicators:
        if not isinstance(indicator, str) or not indicator.strip():
            raise ValueError("statcan_indicators entries must be non empty strings")
        cleaned_indicator = indicator.strip()
        try:
            int(cleaned_indicator)
        except ValueError:
            raise ValueError(
                f"statcan_indicators entries must be integer vector ids: {indicator!r}"
            ) from None
        indicators.append(cleaned_indicator)
    return BenchmarkMap(
        schema_version=int(schema_version),
        benchmarks=benchmarks,
        statcan_indicators=indicators,
    )
