"""StatCan bulk table fetch: two step WDS download with in memory caps.

Step one asks getFullTableDownloadCSV for the product zip URL. Step two
fetches the zip bytes under a byte cap, hashes them, lists the members
without extracting anything to disk, and streams each member through
archive.open in fixed chunks so only the digest and size are retained.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from goc_rates.clients.base import BaseClient, parse_json_capped
from goc_rates.limits import (
    MAX_BULK_BYTES,
    MAX_BULK_MEMBER_BYTES,
    MAX_BULK_MEMBERS,
    MAX_CPI_MONTHS,
)

STATCAN_WDS_BASE_URL = "https://www150.statcan.gc.ca/t1/wds/rest"

EXPECTED_BULK_PRODUCT_IDS: dict[str, int] = {
    "cpi_monthly": 18100004,
    "core_statistics": 18100256,
    "basket_weights": 18100007,
}

_PRODUCT_ID_PATTERN = re.compile(r"^[1-9][0-9]{7}$")
_VECTOR_ID_PATTERN = re.compile(r"^[0-9]{8}$")
_BASKET_VECTOR_PATTERN = re.compile(r"^[0-9]{8}(?:[0-9]{2})?$")
_BASKET_YEAR_PATTERN = re.compile(r"^(\d{4})(?:-\d{2}(?:-\d{2})?)?$")
_MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])(?:-(\d{2}))?$")
_BASKET_COORDINATE_PATTERN = re.compile(r"^[0-9]+(\.[0-9]+)*$")
_MISSING_TOKENS = frozenset({"", ".", "..", "...", "na", "null"})
_MAX_CSV_ROWS = 2_000_000
_MEMBER_HASH_CHUNK_BYTES = 65536

BASKET_WEIGHT_TOLERANCE_PP = 0.01

BASKET_GEO_CANADA = "Canada"
BASKET_PRICE_LINK_MONTH = "Weight at basket link month prices"
BASKET_GEODIST_SELECTED = "Distribution to selected geographies"
BASKET_UOM_PERCENT = "percent"


@dataclass(frozen=True)
class BulkMember:
    """One hashed zip member: name, uncompressed bytes, and sha256."""

    name: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class BulkTable:
    """A fetched bulk product: link, zip bytes, hashes, and member hashes."""

    product_id: int
    zip_url: str
    zip_sha256: str
    retrieved_utc: str
    members: tuple[BulkMember, ...]
    zip_bytes: bytes


@dataclass(frozen=True)
class BasketRow:
    """One retained basket vintage row: product group, vector, coordinate, weight."""

    product: str
    vector: str
    coordinate: str
    weight_percent: float


@dataclass(frozen=True)
class BasketWeights:
    """Parsed basket weights: vintage plus vector weights and retained rows."""

    expenditure_year: int
    link_month: str
    weights_percent: dict[str, float]
    rows: tuple[BasketRow, ...]


def _check_product_id(product_id: int) -> int:
    """Return an 8 digit bulk product id, else raise."""
    if isinstance(product_id, bool) or not isinstance(product_id, int):
        raise ValueError("product_id must be an integer")
    if not _PRODUCT_ID_PATTERN.match(str(product_id)):
        raise ValueError(f"product_id must be an 8 digit id, got {product_id!r}")
    return product_id


def bulk_link_url(product_id: int) -> str:
    """Return the WDS full table download endpoint for a product id."""
    _check_product_id(product_id)
    return f"{STATCAN_WDS_BASE_URL}/getFullTableDownloadCSV/{product_id}/en"


def fetch_bulk_table(product_id: int, client: BaseClient) -> BulkTable:
    """Fetch a bulk product zip in two steps, failing closed on drift."""
    import datetime as dt

    _check_product_id(product_id)
    response = client.get(bulk_link_url(product_id))
    body = parse_json_capped(response)
    if not isinstance(body, dict):
        raise ValueError(f"bulk link response for {product_id} must be an object")
    status = body.get("status")
    if status != "SUCCESS":
        raise ValueError(f"bulk link request for {product_id} failed: {status!r}")
    zip_url = body.get("object", "")
    if not isinstance(zip_url, str) or not zip_url.strip():
        raise ValueError(f"bulk link response for {product_id} is missing its zip URL")
    cleaned_url = zip_url.strip()
    if not cleaned_url.startswith("https://"):
        raise ValueError(f"bulk zip URL for {product_id} must use https")
    zip_bytes = client.get_bytes(cleaned_url, MAX_BULK_BYTES)
    retrieved_utc = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    return assemble_bulk_table(product_id, cleaned_url, zip_bytes, retrieved_utc)


def assemble_bulk_table(
    product_id: int,
    zip_url: str,
    zip_bytes: bytes,
    retrieved_utc: str,
) -> BulkTable:
    """Hash zip bytes and members by streaming each member in fixed chunks."""
    _check_product_id(product_id)
    if len(zip_bytes) > MAX_BULK_BYTES:
        raise ValueError(
            f"bulk zip for {product_id} of {len(zip_bytes)} bytes "
            f"exceeds the {MAX_BULK_BYTES} byte cap"
        )
    if len(zip_bytes) < 4 or not zip_bytes.startswith(b"PK\x03\x04"):
        raise ValueError(f"bulk payload for {product_id} is not a zip archive")
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise ValueError(f"bulk payload for {product_id} is not a zip archive") from None
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if not infos:
            raise ValueError(f"bulk zip for {product_id} holds no files")
        if len(infos) > MAX_BULK_MEMBERS:
            raise ValueError(
                f"bulk zip for {product_id} holds {len(infos)} members, "
                f"over the {MAX_BULK_MEMBERS} member cap"
            )
        total_uncompressed = 0
        for info in infos:
            if info.file_size > MAX_BULK_MEMBER_BYTES:
                raise ValueError(
                    f"bulk member {info.filename!r} of {info.file_size} bytes "
                    f"exceeds the {MAX_BULK_MEMBER_BYTES} byte cap"
                )
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_BULK_BYTES:
                raise ValueError(
                    f"bulk zip for {product_id} expands past the {MAX_BULK_BYTES} byte cap"
                )
        members: list[BulkMember] = []
        for info in infos:
            try:
                member_stream = archive.open(info.filename, "r")
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
                raise ValueError(f"bulk member {info.filename!r} is unreadable: {exc}") from None
            digest = hashlib.sha256()
            size_bytes = 0
            try:
                with member_stream:
                    while True:
                        chunk = member_stream.read(_MEMBER_HASH_CHUNK_BYTES)
                        if not chunk:
                            break
                        size_bytes += len(chunk)
                        if size_bytes > MAX_BULK_MEMBER_BYTES:
                            raise ValueError(
                                f"bulk member {info.filename!r} of over "
                                f"{MAX_BULK_MEMBER_BYTES} bytes "
                                "exceeds the member byte cap"
                            )
                        digest.update(chunk)
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
                raise ValueError(f"bulk member {info.filename!r} is unreadable: {exc}") from None
            members.append(
                BulkMember(
                    name=info.filename,
                    size_bytes=size_bytes,
                    sha256=digest.hexdigest(),
                )
            )
    members.sort(key=lambda item: item.name)
    zip_digest = hashlib.sha256()
    for offset in range(0, len(zip_bytes), 65536):
        zip_digest.update(zip_bytes[offset : offset + 65536])
    return BulkTable(
        product_id=product_id,
        zip_url=zip_url,
        zip_sha256=zip_digest.hexdigest(),
        retrieved_utc=retrieved_utc,
        members=tuple(members),
        zip_bytes=zip_bytes,
    )


def _normalize_month(text: str, row_number: int) -> str:
    """Return the YYYY-MM month for a REF_DATE cell, else raise."""
    cleaned = text.strip()
    match = _MONTH_PATTERN.match(cleaned)
    if match is None:
        raise ValueError(f"bulk CSV row {row_number} has an invalid REF_DATE: {text!r}")
    return f"{match.group(1)}-{match.group(2)}"


def _normalize_vector(text: str) -> str:
    """Strip StatCan vector prefixes so v41690973 matches 41690973."""
    cleaned = text.strip()
    if cleaned[:1] in ("v", "V"):
        cleaned = cleaned[1:].strip()
    return cleaned


def _pick_data_member(
    infos: list[zipfile.ZipInfo],
) -> zipfile.ZipInfo:
    """Pick the data CSV member: a name containing data wins, else the largest CSV."""
    csv_infos = [info for info in infos if info.filename.lower().endswith(".csv")]
    if not csv_infos:
        raise ValueError("bulk zip holds no CSV member")
    data_infos = [info for info in csv_infos if "data" in info.filename.lower()]
    if data_infos:
        return sorted(data_infos, key=lambda info: info.file_size, reverse=True)[0]
    return sorted(csv_infos, key=lambda info: info.file_size, reverse=True)[0]


def _pick_basket_member(
    infos: list[zipfile.ZipInfo],
) -> zipfile.ZipInfo:
    """Pick the basket weights CSV member without extracting to disk."""
    csv_infos = [info for info in infos if info.filename.lower().endswith(".csv")]
    if not csv_infos:
        raise ValueError("basket zip holds no CSV member")
    basket_infos = [
        info
        for info in csv_infos
        if "basket" in info.filename.lower() or "weight" in info.filename.lower()
    ]
    pool = basket_infos if basket_infos else csv_infos
    return sorted(pool, key=lambda info: info.file_size, reverse=True)[0]


def _resolve_header_key(
    header_map: dict[str, str],
    candidates: Sequence[str],
    what: str,
) -> str:
    """Return the actual header name for the first matching candidate, else raise."""
    for candidate in candidates:
        if candidate in header_map:
            return header_map[candidate]
    raise ValueError(f"bulk member is missing column {what} (tried {list(candidates)})")


def _assert_index_unit_metadata(
    header_map: dict[str, str],
    row: dict[str, str],
    row_number: int,
) -> None:
    """Assert bulk unit metadata marks the row as an index level when present.

    The registry pins index levels (not precomputed YoY), so when the bulk
    member carries a UOM or UNIT column the value must name an index. A
    missing unit column is tolerated for older shapes; a present but
    non index unit fails closed before any derive step consumes the value.
    """
    for candidate in ("UOM", "UOM_EN", "UNIT", "UOM_FR"):
        if candidate in header_map:
            actual = header_map[candidate]
            unit_text = str(row.get(actual, "")).strip().lower()
            if unit_text and "index" not in unit_text and unit_text not in ("number", "index"):
                raise ValueError(
                    f"bulk CSV row {row_number} unit {unit_text!r} "
                    "is not an index level: published pins are index, not YoY"
                )
    return None


def extract_component_months(
    zip_bytes: bytes,
    wanted_vectors: Sequence[str] | set[str],
    max_months: int = MAX_CPI_MONTHS,
) -> dict[str, list[tuple[str, float]]]:
    """Extract trailing monthly index values per vector from a bulk zip.

    The data member streams through a chunked CSV reader (no full decode
    into one string), unit metadata is asserted before any value is
    consumed, and missing vectors fail closed. Nothing is written to disk.
    """
    wanted = {str(item).strip() for item in wanted_vectors if str(item).strip()}
    if not wanted:
        raise ValueError("wanted_vectors must contain at least one id")
    if not isinstance(max_months, int) or isinstance(max_months, bool):
        raise ValueError("max_months must be an int")
    if max_months < 1 or max_months > MAX_CPI_MONTHS:
        raise ValueError(f"max_months must sit within [1, {MAX_CPI_MONTHS}]")
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise ValueError("bulk payload is not a zip archive") from None
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        try:
            picked = _pick_data_member(infos)
        except ValueError:
            raise
        if picked.file_size > MAX_BULK_MEMBER_BYTES:
            raise ValueError(
                f"bulk data member {picked.filename!r} exceeds the {MAX_BULK_MEMBER_BYTES} byte cap"
            )
        try:
            raw = archive.open(picked.filename, "r")
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise ValueError(f"bulk data member is unreadable: {exc}") from None
        with raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text_stream:
            reader = csv.DictReader(text_stream)
            if reader.fieldnames is None:
                raise ValueError("bulk data member holds no header row")
            header_map = {name.strip().upper(): name for name in reader.fieldnames}
            for required in ("REF_DATE", "VECTOR", "VALUE"):
                if required not in header_map:
                    raise ValueError(f"bulk data member is missing column {required}")
            ref_key = header_map["REF_DATE"]
            vector_key = header_map["VECTOR"]
            value_key = header_map["VALUE"]
            collected: dict[str, dict[str, float]] = {vector: {} for vector in wanted}
            row_number = 0
            for row in reader:
                row_number += 1
                if row_number > _MAX_CSV_ROWS:
                    raise ValueError(f"bulk data member exceeds the {_MAX_CSV_ROWS} row cap")
                if not isinstance(row, dict):
                    raise ValueError(f"bulk CSV row {row_number} must be a mapping")
                _assert_index_unit_metadata(header_map, row, row_number)
                vector = _normalize_vector(str(row.get(vector_key, "")))
                if vector not in collected:
                    continue
                month = _normalize_month(str(row.get(ref_key, "")), row_number)
                raw_value = str(row.get(value_key, "")).strip()
                if raw_value.lower() in _MISSING_TOKENS:
                    continue
                try:
                    value = float(raw_value)
                except ValueError:
                    raise ValueError(
                        f"bulk CSV row {row_number} has a non numeric VALUE: {raw_value!r}"
                    ) from None
                if value != value or value in (float("inf"), float("-inf")):
                    raise ValueError(f"bulk CSV row {row_number} VALUE must be finite")
                if value <= 0.0:
                    raise ValueError(f"bulk CSV row {row_number} index must be positive")
                collected[vector][month] = value
    missing = sorted(vector for vector, months in collected.items() if not months)
    if missing:
        raise ValueError(f"bulk zip is missing requested vectors: {missing}")
    result: dict[str, list[tuple[str, float]]] = {}
    for vector, months in collected.items():
        ordered = sorted(months.items())
        result[vector] = ordered[-max_months:]
    return result


def _basket_row_year(text: str, row_number: int) -> int:
    """Return the expenditure year for a basket REF_DATE cell, else raise."""
    cleaned = text.strip()
    match = _BASKET_YEAR_PATTERN.match(cleaned)
    if match is None:
        raise ValueError(f"basket CSV row {row_number} has an invalid REF_DATE year: {text!r}")
    return int(match.group(1))


def _check_basket_vintage_params(expenditure_year: int, link_month: str) -> str:
    """Validate the requested basket vintage, returning the link month."""
    if isinstance(expenditure_year, bool) or not isinstance(expenditure_year, int):
        raise ValueError("expenditure_year must be an integer")
    if expenditure_year < 1000 or expenditure_year > 9999:
        raise ValueError(f"expenditure_year must be a 4 digit year, got {expenditure_year!r}")
    match = _MONTH_PATTERN.match(link_month.strip())
    if match is None:
        raise ValueError(f"link_month must be YYYY-MM, got {link_month!r}")
    return f"{match.group(1)}-{match.group(2)}"


def extract_basket_weights(
    zip_bytes: bytes,
    *,
    expenditure_year: int,
    link_month: str,
) -> BasketWeights:
    """Parse the basket weights member from a bulk zip, streaming rows.

    Live table 18100007 carries no EXPENDITURE_YEAR or LINK_MONTH columns.
    Its actual columns are REF_DATE, GEO, DGUID, Products and product groups,
    Price period of weight, Geographic distribution of weight, UOM, UOM_ID,
    SCALAR_FACTOR, SCALAR_ID, VECTOR, COORDINATE, VALUE, STATUS, SYMBOL,
    TERMINATED, and DECIMALS. REF_DATE holds the expenditure year (YYYY),
    VALUE holds the weight in percent, and the requested vintage slice is
    GEO Canada at basket link month prices. The link month itself is not
    recorded in the member, so the caller passes the pinned link month
    (registry vintage) and it is carried on the result for provenance.
    Every kept row must use a percent unit, every weight must be a present
    positive finite percent, every basket vector must be an 8 digit classic
    id or a 10 digit extended StatCan id, every coordinate must match
    ^[0-9]+(\\.[0-9]+)*$, and nothing is written to disk. Duplicate
    products, vectors, or coordinates each fail closed. Rows are retained
    with product, vector, coordinate, and weight for basket mapping.
    An empty vintage slice or any drift fails closed.
    """
    normalized_link = _check_basket_vintage_params(expenditure_year, link_month)
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise ValueError("basket payload is not a zip archive") from None
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        try:
            picked = _pick_basket_member(infos)
        except ValueError:
            raise
        if picked.file_size > MAX_BULK_MEMBER_BYTES:
            raise ValueError(
                f"basket member {picked.filename!r} exceeds the {MAX_BULK_MEMBER_BYTES} byte cap"
            )
        try:
            raw = archive.open(picked.filename, "r")
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
            raise ValueError(f"basket member is unreadable: {exc}") from None
        with raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text_stream:
            reader = csv.DictReader(text_stream)
            if reader.fieldnames is None:
                raise ValueError("basket member holds no header row")
            header_map = {name.strip().upper(): name for name in reader.fieldnames}
            ref_key = _resolve_header_key(
                header_map,
                ("REF_DATE", "REFERENCE_DATE", "REFERENCE_PERIOD"),
                "REF_DATE",
            )
            geo_key = _resolve_header_key(
                header_map,
                ("GEO", "GEOGRAPHY", "REGION"),
                "GEO",
            )
            product_key = _resolve_header_key(
                header_map,
                ("PRODUCTS AND PRODUCT GROUPS", "PRODUCT", "PRODUCT_GROUP"),
                "PRODUCTS AND PRODUCT GROUPS",
            )
            price_key = _resolve_header_key(
                header_map,
                ("PRICE PERIOD OF WEIGHT", "PRICE_PERIOD", "WEIGHT_TYPE"),
                "PRICE PERIOD OF WEIGHT",
            )
            geodist_key = _resolve_header_key(
                header_map,
                ("GEOGRAPHIC DISTRIBUTION OF WEIGHT", "GEOGRAPHY_DISTRIBUTION"),
                "GEOGRAPHIC DISTRIBUTION OF WEIGHT",
            )
            uom_key = _resolve_header_key(
                header_map,
                ("UOM", "UOM_EN", "UNIT"),
                "UOM",
            )
            vector_key = _resolve_header_key(
                header_map, ("VECTOR", "VECTOR_ID", "VECTORID"), "VECTOR"
            )
            coordinate_key = _resolve_header_key(header_map, ("COORDINATE", "COORD"), "COORDINATE")
            weight_key = _resolve_header_key(
                header_map,
                ("VALUE", "VALEUR", "WEIGHT_PERCENT", "WEIGHT", "BASKET_WEIGHT"),
                "VALUE",
            )
            weights: dict[str, float] = {}
            rows: list[BasketRow] = []
            seen_products: set[str] = set()
            seen_vectors: set[str] = set()
            seen_coordinates: set[str] = set()
            seen_years: set[str] = set()
            row_number = 0
            for row in reader:
                row_number += 1
                if row_number > _MAX_CSV_ROWS:
                    raise ValueError(f"basket member exceeds the {_MAX_CSV_ROWS} row cap")
                if not isinstance(row, dict):
                    raise ValueError(f"basket CSV row {row_number} must be a mapping")
                year = _basket_row_year(str(row.get(ref_key, "")), row_number)
                seen_years.add(str(row.get(ref_key, "")).strip())
                if year != expenditure_year:
                    continue
                if str(row.get(geo_key, "")).strip().casefold() != BASKET_GEO_CANADA.casefold():
                    continue
                if (
                    str(row.get(price_key, "")).strip().casefold()
                    != BASKET_PRICE_LINK_MONTH.casefold()
                ):
                    continue
                if (
                    str(row.get(geodist_key, "")).strip().casefold()
                    != BASKET_GEODIST_SELECTED.casefold()
                ):
                    continue
                product = str(row.get(product_key, "")).strip()
                if not product:
                    raise ValueError(f"basket CSV row {row_number} is missing its product group")
                if product in seen_products:
                    raise ValueError(
                        f"basket CSV row {row_number} repeats product group {product!r}"
                    )
                unit_text = str(row.get(uom_key, "")).strip()
                if unit_text.casefold() != BASKET_UOM_PERCENT:
                    raise ValueError(
                        f"basket CSV row {row_number} unit {unit_text!r} is not a percent weight"
                    )
                vector = _normalize_vector(str(row.get(vector_key, "")))
                if not vector:
                    raise ValueError(f"basket CSV row {row_number} is missing its vector")
                if not _BASKET_VECTOR_PATTERN.match(vector):
                    raise ValueError(
                        f"basket CSV row {row_number} vector {vector!r} "
                        "must be an 8 digit classic id or a 10 digit extended id"
                    )
                if vector in weights:
                    raise ValueError(f"basket CSV row {row_number} repeats vector {vector!r}")
                coordinate = str(row.get(coordinate_key, "")).strip()
                if not coordinate:
                    raise ValueError(f"basket CSV row {row_number} is missing its coordinate")
                if not _BASKET_COORDINATE_PATTERN.match(coordinate):
                    raise ValueError(
                        f"basket CSV row {row_number} coordinate {coordinate!r} "
                        "must match ^[0-9]+(\\.[0-9]+)*$"
                    )
                if coordinate in seen_coordinates:
                    raise ValueError(
                        f"basket CSV row {row_number} repeats coordinate {coordinate!r}"
                    )
                raw_weight = str(row.get(weight_key, "")).strip()
                if raw_weight.lower() in _MISSING_TOKENS:
                    raise ValueError(
                        f"basket CSV row {row_number} has a missing weight for {product!r}"
                    )
                try:
                    weight = float(raw_weight)
                except ValueError:
                    raise ValueError(
                        f"basket CSV row {row_number} has a non numeric weight: {raw_weight!r}"
                    ) from None
                if weight != weight or weight in (float("inf"), float("-inf")):
                    raise ValueError(f"basket CSV row {row_number} weight must be finite")
                if weight <= 0.0:
                    raise ValueError(f"basket CSV row {row_number} weight must be positive")
                weights[vector] = weight
                seen_products.add(product)
                seen_vectors.add(vector)
                seen_coordinates.add(coordinate)
                rows.append(
                    BasketRow(
                        product=product,
                        vector=vector,
                        coordinate=coordinate,
                        weight_percent=weight,
                    )
                )
            if not weights:
                sample = sorted(seen_years)[:10]
                raise ValueError(
                    f"basket member holds no rows for expenditure year {expenditure_year} "
                    f"(saw REF_DATE values {sample})"
                )
            return BasketWeights(
                expenditure_year=expenditure_year,
                link_month=normalized_link,
                weights_percent=dict(weights),
                rows=tuple(rows),
            )


def bulk_tables_for_snapshot(
    tables: Mapping[str, BulkTable],
) -> dict[str, dict[str, Any]]:
    """Render bulk hashes for the snapshot: full sha256 plus short sha12."""
    rendered: dict[str, dict[str, Any]] = {}
    for name, table in tables.items():
        digest = table.zip_sha256.strip().lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"bulk table {name!r} has an invalid sha256")
        rendered[str(name)] = {
            "product_id": table.product_id,
            "zip_sha256": digest,
            "zip_sha12": digest[:12],
        }
    return rendered
