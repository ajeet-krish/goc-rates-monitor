"""Phase 7 backfill command: Valet plus FRED plus StatCan bulk into a sealed history artifact.

The command fetches the Valet benchmark group history with label assertion,
FRED DGS histories when an API key is present with per series degrade, and
the three StatCan CPI bulk zips through the existing chunked extraction. The
Canadian legs hand to history.build_daily_rows on joint complete dates, the
CPI months hand to history.build_cpi_rows with trailing 12 month
compounding, and the sealed document writes atomically beside a sha256
manifest. Valet or config failure exits 2 with no write, fewer than 250
joint rows exits 1 with no write, and degraded FRED or CPI still exits 0.
The FRED key never reaches logs or disk.
"""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from goc_rates.breaks import BENCH_CDN_URL, load_switch_feed
from goc_rates.clients.base import BaseClient
from goc_rates.clients.fred import fetch_fred_series, read_api_key, redact_api_key_text
from goc_rates.clients.valet import VALET_GROUP, fetch_valet_group
from goc_rates.config import BenchmarkMap, CpiConfig, load_benchmark_map, load_cpi_config
from goc_rates.cpi.basket_map import check_basket_agreement
from goc_rates.cpi.bulk import (
    EXPECTED_BULK_PRODUCT_IDS,
    BulkTable,
    extract_basket_weights,
    extract_component_months,
    fetch_bulk_table,
)
from goc_rates.cpi.components import ComponentSpec, specs_from_config
from goc_rates.cpi.section import cpi_provenance_entry
from goc_rates.cpi.weights import WeightVintage, normalize_weights, vintage_from_config
from goc_rates.history import (
    BACKFILL_METHOD,
    BACKFILL_SCHEMA_VERSION,
    TENORS,
    build_backfill_document,
    build_cpi_rows,
    build_daily_rows,
)
from goc_rates.limits import (
    MAX_BACKFILL_BYTES,
    MAX_BACKFILL_CPI_MONTHS,
    MAX_BACKFILL_DAILY_ROWS,
    MAX_HISTORY_OBS,
    MIN_BACKFILL_DAILY_ROWS,
)
from goc_rates.live_snapshot import (
    FRED_SERIES_URL,
    VALET_GROUP_URL,
    _degraded_cpi_provenance,
    _retrieved_utc_now,
    resolve_target_date,
)
from goc_rates.snapshot import atomic_write_text, canonical_dumps, sha256_text

FRED_LOOKBACK_DAYS = 2190  # unit: days, about 6 years of daily DGS prints
CPI_INDEX_MONTHS_KEPT = MAX_BACKFILL_CPI_MONTHS + 1  # unit: months, 61 index months give 60 cores


def _observed_history(rows: list[Any], asof_text: str) -> dict[str, float]:
    """Map observed percent prints on or before asof to values, skipping gaps."""
    by_date: dict[str, float] = {}
    for row in rows:
        date_text = row.observation_date
        if date_text > asof_text:
            continue
        quantity = row.quantity
        if quantity.get("quality") != "observed":
            continue
        value = quantity.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            continue
        by_date[date_text] = number
    return by_date


def _trim_recent(history: dict[str, float], keep: int) -> dict[str, float]:
    """Keep the most recent keep entries so the joint row cap can never trip."""
    if len(history) <= keep:
        return dict(history)
    recent = sorted(history.keys())[-keep:]
    return {date_text: history[date_text] for date_text in recent}


def _fetch_fred_histories(
    client: BaseClient,
    benchmark_map: BenchmarkMap,
    api_key: str,
    asof_day: dt.date,
) -> tuple[dict[str, dict[str, float]], list[str], list[dict[str, str]]]:
    """Fetch per tenor FRED histories with per series degrade, never leaking the key."""
    start_text = (asof_day - dt.timedelta(days=FRED_LOOKBACK_DAYS)).isoformat()
    end_text = asof_day.isoformat()
    histories: dict[str, dict[str, float]] = {}
    warnings: list[str] = []
    exclusions: list[dict[str, str]] = []
    for tenor in TENORS:
        series_id = benchmark_map.benchmarks[tenor].fred_series_id
        try:
            rows = fetch_fred_series(
                series_id,
                client,
                api_key=api_key,
                observation_start=start_text,
                observation_end=end_text,
                limit=MAX_HISTORY_OBS,
                sort_order="asc",
            )
        except Exception as exc:
            detail = redact_api_key_text(str(exc))
            warnings.append(f"FRED fetch degraded for {series_id}, tenor spreads missing: {detail}")
            exclusions.append(
                {"scope": f"fred:{series_id}", "reason": f"FRED fetch failed: {detail}"}
            )
            histories[tenor] = {}
            continue
        histories[tenor] = _observed_history(rows, end_text)
    return histories, warnings, exclusions


def _fetch_bulk_tables(
    client: BaseClient,
    cpi_config: CpiConfig,
) -> tuple[dict[str, BulkTable], list[str], list[dict[str, str]]]:
    """Fetch the pinned CPI bulk zips with per product degrade, failing open to degraded CPI."""
    tables: dict[str, BulkTable] = {}
    warnings: list[str] = []
    exclusions: list[dict[str, str]] = []
    for bulk_name, product_id in cpi_config.product_ids.items():
        expected = EXPECTED_BULK_PRODUCT_IDS.get(bulk_name)
        if expected is not None and product_id != expected:
            warnings.append(
                f"CPI bulk {bulk_name!r} product id {product_id} "
                f"must pin {expected}, table skipped."
            )
            exclusions.append(
                {
                    "scope": f"bulk:{bulk_name}",
                    "reason": f"Product id {product_id} must pin {expected}, table skipped.",
                }
            )
            continue
        try:
            tables[bulk_name] = fetch_bulk_table(product_id, client)
        except Exception as exc:
            warnings.append(f"CPI bulk {bulk_name!r} unavailable, degrading: {exc}")
            exclusions.append(
                {"scope": f"bulk:{bulk_name}", "reason": f"CPI bulk fetch failed: {exc}"}
            )
    return tables, warnings, exclusions


def _present_vectors(zip_bytes: bytes) -> set[str]:
    """Return the distinct normalized VECTOR ids from the bulk data member.

    The member choice mirrors the bulk extractor: metadata companions are
    skipped in favor of the largest content CSV. A missing VECTOR column
    fails closed; a healthy member with other vectors simply yields its set.
    """
    import csv
    import io
    import zipfile

    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise ValueError("bulk payload is not a zip archive") from None
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        csv_infos = [info for info in infos if info.filename.lower().endswith(".csv")]
        if not csv_infos:
            raise ValueError("bulk zip holds no CSV member")
        content = [info for info in csv_infos if "meta" not in info.filename.lower()]
        pool = content if content else csv_infos
        picked = sorted(pool, key=lambda info: info.file_size, reverse=True)[0]
        try:
            raw = archive.open(picked.filename, "r")
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise ValueError(f"bulk data member is unreadable: {exc}") from None
        with raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text_stream:
            reader = csv.DictReader(text_stream)
            if reader.fieldnames is None:
                raise ValueError("bulk data member holds no header row")
            header_map = {name.strip().upper(): name for name in reader.fieldnames}
            if "VECTOR" not in header_map:
                raise ValueError("bulk data member is missing column VECTOR")
            vector_key = header_map["VECTOR"]
            found: set[str] = set()
            for row in reader:
                cleaned = str(row.get(vector_key, "")).strip()
                if cleaned[:1] in ("v", "V"):
                    cleaned = cleaned[1:].strip()
                if cleaned:
                    found.add(cleaned)
            return found


def _extract_table_months(
    zip_bytes: bytes, vectors: set[str]
) -> dict[str, list[tuple[str, float]]]:
    """Extract months for the wanted vectors, skipping tables that hold none.

    A table holding every wanted vector extracts in one pass. A table
    holding only some of them, like the core statistics zip beside the
    monthly CPI zip, contributes its present subset instead of failing the
    whole backfill. Any other extraction fault still fails closed.
    """
    try:
        return extract_component_months(zip_bytes, set(vectors))
    except ValueError as exc:
        if "missing requested vectors" not in str(exc):
            raise
        present = _present_vectors(zip_bytes) & set(vectors)
        if not present:
            return {}
        return extract_component_months(zip_bytes, present)


def _cpi_inputs(
    specs: tuple[ComponentSpec, ...],
    weights: Mapping[str, float],
    vintage: WeightVintage,
    bulk_tables: Mapping[str, BulkTable],
    asof_month: str,
) -> tuple[dict[str, list[tuple[str, float]]], dict[str, float], WeightVintage]:
    """Extract shared component months capped to the backfill window for the row builder."""
    wanted = {spec.vector_id: spec.component_id for spec in specs}
    merged: dict[str, dict[str, float]] = {}
    for key in ("cpi_monthly", "core_statistics"):
        table = bulk_tables.get(key)
        if table is None:
            continue
        by_vector = _extract_table_months(table.zip_bytes, set(wanted.keys()))
        for vector, months in by_vector.items():
            slot = merged.setdefault(vector, {})
            for month, index in months:
                slot.setdefault(month, index)
    missing = sorted(vector for vector in wanted if vector not in merged)
    if missing:
        raise ValueError(f"bulk zips are missing registry vectors: {missing}")
    shared = set.intersection(*[set(months.keys()) for months in merged.values()])
    use_months = sorted(month for month in shared if month <= asof_month)
    if len(use_months) < 2:
        raise ValueError("bulk history holds no months on or before the asof month")
    use_months = use_months[-CPI_INDEX_MONTHS_KEPT:]
    monthly_indexes = {
        component_id: [(month, merged[vector][month]) for month in use_months]
        for vector, component_id in wanted.items()
    }
    return monthly_indexes, dict(weights), vintage


def _fred_vintage(
    us_histories: dict[str, dict[str, float]] | None, asof_text: str
) -> str:
    """Return the latest US print on or before asof, else asof itself."""
    if not us_histories:
        return asof_text
    dates = [date for history in us_histories.values() for date in history if date <= asof_text]
    return max(dates) if dates else asof_text


def _assemble_degraded_document(
    asof_day: dt.date,
    daily_rows: list[dict[str, Any]],
    provenance: dict[str, Any],
    exclusions: list[dict[str, str]],
    retrieved_utc: str,
) -> dict[str, Any]:
    """Assemble the degraded backfill document with no CPI months but the sealed shape.

    The metadata, daily, provenance, exclusion, and timestamp keys match
    history.build_backfill_document exactly with cpi_count zero, so readers
    parse one shape. The canonical bytes must fit the backfill byte cap.
    """
    if not isinstance(retrieved_utc, str) or not retrieved_utc.strip():
        raise ValueError("retrieved_utc must be a non empty string")
    document: dict[str, Any] = {
        "metadata": {
            "asof": asof_day.isoformat(),
            "schema_version": BACKFILL_SCHEMA_VERSION,
            "method": BACKFILL_METHOD,
            "retrieved_utc": retrieved_utc.strip(),
            "daily_count": len(daily_rows),
            "daily_count_unit": "count",
            "cpi_count": 0,
            "cpi_count_unit": "count",
        },
        "daily": daily_rows,
        "cpi": [],
        "provenance": dict(provenance),
        "exclusions": list(exclusions),
        "retrieved_utc": retrieved_utc.strip(),
    }
    payload_bytes = len(canonical_dumps(document).encode("utf-8"))
    if payload_bytes > MAX_BACKFILL_BYTES:
        raise ValueError(
            f"degraded backfill of {payload_bytes} bytes exceeds the {MAX_BACKFILL_BYTES} byte cap"
        )
    return document


def run_backfill(
    asof_text: str | None,
    out_path: str | None,
    config_path: str | None = "config/benchmark_map.yaml",
) -> int:
    """Fetch histories and write the sealed backfill artifact plus manifest, failing closed."""
    try:
        asof_day = resolve_target_date(asof_text)
    except ValueError as exc:
        print(f"backfill failed: {exc}", file=sys.stderr)
        return 2
    asof_iso = asof_day.isoformat()
    out_file = Path(out_path) if out_path else Path("history/backfill.json")
    if out_file.suffix != ".json":
        print(f"backfill failed: out path must name a .json artifact: {out_file}", file=sys.stderr)
        return 2
    if out_file.is_symlink():
        print(f"backfill failed: out path must not be a symlink: {out_file}", file=sys.stderr)
        return 2
    config_file = Path(config_path) if config_path else Path("config/benchmark_map.yaml")
    try:
        benchmark_map = load_benchmark_map(config_file)
    except (ValueError, OSError) as exc:
        print(f"backfill failed: {exc}", file=sys.stderr)
        return 2
    try:
        switch_feed = load_switch_feed(config_file.parent / "benchmark_switches.yaml")
    except (ValueError, OSError) as exc:
        print(f"backfill failed: {exc}", file=sys.stderr)
        return 2
    try:
        cpi_config = load_cpi_config(config_file.parent / "cpi_components.yaml")
        cpi_specs = specs_from_config(cpi_config)
        cpi_weights = normalize_weights(cpi_specs)
        cpi_vintage = vintage_from_config(cpi_config)
    except (ValueError, OSError) as exc:
        print(f"backfill failed: {exc}", file=sys.stderr)
        return 2

    expected_labels = {
        entry.valet_series_id: entry.valet_label for entry in benchmark_map.benchmarks.values()
    }
    warnings: list[str] = []
    exclusions: list[dict[str, str]] = []
    with BaseClient() as client:
        try:
            valet_by_series = fetch_valet_group(
                VALET_GROUP,
                client,
                expected_labels=expected_labels,
                recent_limit=MAX_HISTORY_OBS,
            )
        except Exception as exc:
            print(
                f"backfill failed: live Valet fetch unavailable: {redact_api_key_text(str(exc))}",
                file=sys.stderr,
            )
            return 2
        api_key = read_api_key()
        if api_key is not None and api_key.strip():
            try:
                fred_result = _fetch_fred_histories(client, benchmark_map, api_key, asof_day)
            except Exception as exc:
                detail = redact_api_key_text(str(exc))
                fred_histories: dict[str, dict[str, float]] | None = None
                warnings.append(f"FRED degraded, US leg unavailable: {detail}")
                exclusions.append({"scope": "fred:us_leg", "reason": f"US leg failed: {detail}"})
            else:
                fred_histories, fred_warnings, fred_exclusions = fred_result
                warnings.extend(fred_warnings)
                exclusions.extend(fred_exclusions)
        else:
            fred_histories = None
            warnings.append("FRED degraded: API key absent, US leg unavailable.")
            exclusions.append(
                {"scope": "fred:us_leg", "reason": "FRED API key absent, US leg unavailable."}
            )
        try:
            bulk_result = _fetch_bulk_tables(client, cpi_config)
        except Exception as exc:
            cpi_bulk: dict[str, BulkTable] = {}
            warnings.append(f"CPI bulk unavailable, degrading: {exc}")
            exclusions.append({"scope": "cpi:bulk", "reason": f"CPI bulk fetch failed: {exc}"})
        else:
            cpi_bulk, cpi_warnings, cpi_exclusions = bulk_result
            warnings.extend(cpi_warnings)
            exclusions.extend(cpi_exclusions)

    ca_histories: dict[str, dict[str, float]] = {}
    for tenor in TENORS:
        series_id = benchmark_map.benchmarks[tenor].valet_series_id
        observed = _observed_history(valet_by_series.get(series_id, []), asof_iso)
        ca_histories[tenor] = _trim_recent(observed, MAX_BACKFILL_DAILY_ROWS)
    try:
        daily_rows = build_daily_rows(ca_histories, fred_histories, asof_day, switch_feed)
    except ValueError as exc:
        print(f"backfill failed: {exc}", file=sys.stderr)
        return 1
    if len(daily_rows) < MIN_BACKFILL_DAILY_ROWS:
        print(
            f"backfill failed: only {len(daily_rows)} joint rows, "
            f"need {MIN_BACKFILL_DAILY_ROWS}",
            file=sys.stderr,
        )
        return 1

    retrieved_utc = _retrieved_utc_now()
    provenance: dict[str, Any] = {
        "valet": {
            "source_url": VALET_GROUP_URL,
            "retrieved_utc": retrieved_utc,
            "vintage": daily_rows[-1]["date"],
        },
        "fred": {
            "source_url": FRED_SERIES_URL,
            "retrieved_utc": retrieved_utc,
            "vintage": _fred_vintage(fred_histories, asof_iso),
        },
        "benchmark_switches": {
            "source_url": BENCH_CDN_URL,
            "retrieved_utc": retrieved_utc,
            "vintage": switch_feed.feed_vintage.isoformat(),
            "sha256": switch_feed.feed_sha256,
        },
    }
    cpi_rows: list[dict[str, Any]] = []
    try:
        monthly_indexes, weights, vintage = _cpi_inputs(
            cpi_specs, cpi_weights, cpi_vintage, cpi_bulk, asof_iso[:7]
        )
        if "basket_weights" in cpi_bulk:
            try:
                basket = extract_basket_weights(
                    cpi_bulk["basket_weights"].zip_bytes,
                    expenditure_year=vintage.expenditure_year,
                    link_month=vintage.link_month,
                )
                check_basket_agreement(cpi_config, basket)
            except ValueError as exc:
                warnings.append(f"CPI basket agreement degraded, registry weights reused: {exc}")
                exclusions.append(
                    {
                        "scope": "basket:18100007",
                        "reason": f"Basket agreement failed, registry weights reused: {exc}",
                    }
                )
        else:
            warnings.append(
                "CPI basket weights bulk unavailable, agreement unchecked, registry weights reused."
            )
            exclusions.append(
                {
                    "scope": "basket:18100007",
                    "reason": "Basket weights bulk unavailable, agreement unchecked.",
                }
            )
        cpi_rows = build_cpi_rows(monthly_indexes, weights, vintage)
        provenance["statcan_cpi"] = cpi_provenance_entry(dict(cpi_bulk), vintage, retrieved_utc)
    except ValueError as exc:
        warnings.append(f"CPI degraded, backfill carries no CPI months: {exc}")
        exclusions.append({"scope": "cpi:months", "reason": f"CPI months unavailable: {exc}"})
        provenance["statcan_cpi"] = _degraded_cpi_provenance(cpi_config, asof_day, str(exc))

    try:
        if cpi_rows:
            document = build_backfill_document(
                asof_day, daily_rows, cpi_rows, provenance, exclusions, retrieved_utc
            )
        else:
            document = _assemble_degraded_document(
                asof_day, daily_rows, provenance, exclusions, retrieved_utc
            )
    except ValueError as exc:
        print(f"backfill failed: {exc}", file=sys.stderr)
        return 1

    text = canonical_dumps(document)
    if "api_key=" in text:
        print("backfill failed: artifact must not contain API key material", file=sys.stderr)
        return 1
    try:
        atomic_write_text(out_file, text)
    except OSError as exc:
        print(f"backfill failed: {exc}", file=sys.stderr)
        return 1
    manifest = {
        "files": {
            out_file.name: {
                "sha256": sha256_text(text),
                "bytes_utf8": len(text.encode("utf-8")),
            }
        }
    }
    manifest_path = out_file.with_name(out_file.stem + "-manifest.json")
    try:
        atomic_write_text(manifest_path, canonical_dumps(manifest))
    except OSError as exc:
        print(f"backfill failed: {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"backfill warning: {warning}", file=sys.stderr)
    print(f"BACKFILL_ASOF={asof_iso}")
    print(f"wrote sealed backfill to {out_file}", file=sys.stderr)
    return 0
