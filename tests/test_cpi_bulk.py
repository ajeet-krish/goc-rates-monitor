"""CPI bulk tests: two step fetch, caps, hashes, and month extraction."""

import hashlib
import io
import zipfile

import httpx
import pytest

from goc_rates.clients.base import BaseClient
from goc_rates.cpi.bulk import (
    assemble_bulk_table,
    bulk_link_url,
    extract_basket_weights,
    extract_component_months,
    fetch_bulk_table,
)
from goc_rates.limits import MAX_BULK_BYTES

ZIP_URL = "https://www150.statcan.gc.ca/n1/tbl/fulltable.zip"
CSV_TEXT = (
    "REF_DATE,VECTOR,VALUE\n"
    "2026-07,v101,100.0\n"
    "2026-08,v101,100.2\n"
    "2026-09,v101,100.5\n"
    "2026-07,102,200.0\n"
    "2026-08,102,200.4\n"
    "2026-09,102,199.8\n"
)


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    """Build an in memory zip archive from member bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _client_for(link_payload: object, zip_payload: bytes) -> BaseClient:
    """Build a BaseClient whose transport serves the link then the zip."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("en"):
            import json

            return httpx.Response(200, content=json.dumps(link_payload).encode("utf-8"))
        return httpx.Response(200, content=zip_payload)

    return BaseClient(transport=httpx.MockTransport(handler))


def test_bulk_link_url_shape() -> None:
    """Link URL embeds the product id with the en suffix."""
    assert bulk_link_url(18100004).endswith("/getFullTableDownloadCSV/18100004/en")
    with pytest.raises(ValueError):
        bulk_link_url(0)
    with pytest.raises(ValueError, match="8 digit"):
        bulk_link_url(1810000401)


def test_two_step_fetch_hashes_members() -> None:
    """Link JSON plus zip bytes yield hashed members with no extraction."""
    payload = _zip_bytes({"table-Data.csv": CSV_TEXT.encode("utf-8")})
    client = _client_for({"status": "SUCCESS", "object": ZIP_URL}, payload)
    table = fetch_bulk_table(18100004, client)
    assert table.product_id == 18100004
    assert table.zip_url == ZIP_URL
    assert table.zip_sha256 == hashlib.sha256(payload).hexdigest()
    assert len(table.members) == 1
    assert table.members[0].sha256 == hashlib.sha256(CSV_TEXT.encode("utf-8")).hexdigest()
    assert table.members[0].size_bytes == len(CSV_TEXT.encode("utf-8"))
    client.close()


def test_non_success_status_fails() -> None:
    """An ERROR link status fails closed."""
    payload = _zip_bytes({"table-Data.csv": CSV_TEXT.encode("utf-8")})
    client = _client_for({"status": "ERROR", "object": ZIP_URL}, payload)
    with pytest.raises(ValueError, match="failed"):
        fetch_bulk_table(18100004, client)
    client.close()


def test_non_https_zip_url_fails() -> None:
    """A plain http zip URL fails closed."""
    payload = _zip_bytes({"table-Data.csv": CSV_TEXT.encode("utf-8")})
    client = _client_for({"status": "SUCCESS", "object": "http://example.com/a.zip"}, payload)
    with pytest.raises(ValueError, match="https"):
        fetch_bulk_table(18100004, client)
    client.close()


def test_declared_content_length_cap_fails() -> None:
    """An oversize declared length fails before buffering the body."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": str(MAX_BULK_BYTES + 1)},
            content=b"x",
        )

    client = BaseClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="cap"):
        client.get_bytes(ZIP_URL, MAX_BULK_BYTES)
    client.close()


def test_buffered_body_cap_fails() -> None:
    """A body over a small cap fails closed."""
    client = _client_for({"status": "SUCCESS", "object": ZIP_URL}, b"x" * 20)
    with pytest.raises(ValueError, match="cap"):
        client.get_bytes(ZIP_URL, 10)
    client.close()


def test_non_zip_payload_fails() -> None:
    """A non zip payload fails closed."""
    with pytest.raises(ValueError, match="not a zip"):
        assemble_bulk_table(18100004, ZIP_URL, b"not a zip", "2026-10-01T00:00:00Z")


def test_member_cap_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A member over a patched byte cap fails instead of allocating."""
    import goc_rates.cpi.bulk as bulk_mod

    monkeypatch.setattr(bulk_mod, "MAX_BULK_MEMBER_BYTES", 10)
    payload = _zip_bytes({"table-Data.csv": CSV_TEXT.encode("utf-8")})
    with pytest.raises(ValueError, match="cap"):
        assemble_bulk_table(18100004, ZIP_URL, payload, "2026-10-01T00:00:00Z")


def test_member_count_cap_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """More members than a patched cap fails instead of listing freely."""
    import goc_rates.cpi.bulk as bulk_mod

    monkeypatch.setattr(bulk_mod, "MAX_BULK_MEMBERS", 1)
    payload = _zip_bytes({"a.csv": b"x", "b.csv": b"y"})
    with pytest.raises(ValueError, match="member cap"):
        assemble_bulk_table(18100004, ZIP_URL, payload, "2026-10-01T00:00:00Z")


def test_members_stream_without_single_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Members hash by streaming archive.open, never by a single archive.read."""
    expected = CSV_TEXT.encode("utf-8")
    payload = _zip_bytes({"table-Data.csv": expected})

    def _forbid_single_read(self: object, name: object) -> bytes:
        raise AssertionError("assemble must stream via archive.open, not archive.read")

    monkeypatch.setattr(zipfile.ZipFile, "read", _forbid_single_read)
    table = assemble_bulk_table(18100004, ZIP_URL, payload, "2026-10-01T00:00:00Z")
    assert len(table.members) == 1
    assert table.members[0].size_bytes == len(expected)
    assert table.members[0].sha256 == hashlib.sha256(expected).hexdigest()


def test_streaming_cap_enforced_during_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Member bytes hash in fixed chunks, so no single read holds the member."""
    from typing import Any

    expected = CSV_TEXT.encode("utf-8")
    payload = _zip_bytes({"table-Data.csv": expected})
    original_read = zipfile.ZipExtFile.read
    chunk_sizes: list[int] = []

    def _spy_read(self: Any, size: int = -1) -> bytes:
        chunk = original_read(self, size)
        if chunk:
            chunk_sizes.append(len(chunk))
        return chunk

    monkeypatch.setattr(zipfile.ZipExtFile, "read", _spy_read)
    table = assemble_bulk_table(18100004, ZIP_URL, payload, "2026-10-01T00:00:00Z")
    assert chunk_sizes, "expected at least one streamed chunk"
    assert max(chunk_sizes) <= 65536
    assert sum(chunk_sizes) == len(expected)
    assert table.members[0].size_bytes == len(expected)


def test_extract_component_months_parses_vectors() -> None:
    """REF_DATE plus VECTOR plus VALUE rows map to trailing month lists."""
    payload = _zip_bytes({"table-Data.csv": CSV_TEXT.encode("utf-8")})
    result = extract_component_months(payload, {"101", "102"})
    assert [month for month, _ in result["101"]] == ["2026-07", "2026-08", "2026-09"]
    assert result["102"][-1] == ("2026-09", pytest.approx(199.8))


def test_extract_truncates_to_max_months() -> None:
    """Only the trailing max_months are kept."""
    payload = _zip_bytes({"table-Data.csv": CSV_TEXT.encode("utf-8")})
    result = extract_component_months(payload, {"101"}, max_months=2)
    assert [month for month, _ in result["101"]] == ["2026-08", "2026-09"]


def test_extract_missing_vectors_fail() -> None:
    """Vectors absent from the zip fail closed with their ids."""
    payload = _zip_bytes({"table-Data.csv": CSV_TEXT.encode("utf-8")})
    with pytest.raises(ValueError, match="missing requested vectors"):
        extract_component_months(payload, {"999"})


def test_extract_bad_header_fails() -> None:
    """A CSV without the required columns fails closed."""
    payload = _zip_bytes({"table-Data.csv": b"foo,bar\n1,2\n"})
    with pytest.raises(ValueError, match="REF_DATE"):
        extract_component_months(payload, {"101"})


def test_extract_bad_value_fails() -> None:
    """A garbage VALUE token fails closed instead of skipping."""
    bad = "REF_DATE,VECTOR,VALUE\n2026-09,101,abc\n"
    payload = _zip_bytes({"table-Data.csv": bad.encode("utf-8")})
    with pytest.raises(ValueError, match="non numeric VALUE"):
        extract_component_months(payload, {"101"})


def test_no_files_written_to_disk(tmp_path: object) -> None:
    """Bulk assembly and extraction leave the working tree untouched."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    before = set(tmp_path.iterdir())
    payload = _zip_bytes({"table-Data.csv": CSV_TEXT.encode("utf-8")})
    assemble_bulk_table(18100004, ZIP_URL, payload, "2026-10-01T00:00:00Z")
    extract_component_months(payload, {"101"})
    assert set(tmp_path.iterdir()) == before


BASKET_HEADER = (
    "REF_DATE,GEO,DGUID,Products and product groups,"
    "Price period of weight,Geographic distribution of weight,"
    "UOM,UOM_ID,SCALAR_FACTOR,SCALAR_ID,VECTOR,COORDINATE,"
    "VALUE,STATUS,SYMBOL,TERMINATED,DECIMALS"
)


def _basket_row(
    vector: str,
    value: str,
    year: str = "2024",
    geo: str = "Canada",
    price: str = "Weight at basket link month prices",
    geodist: str = "Distribution to selected geographies",
    uom: str = "Percent",
    product: str | None = None,
    coordinate: str | None = None,
) -> str:
    """Build one live shaped 18100007 basket CSV row."""
    label = product if product is not None else f"Product {vector}"
    if coordinate is not None:
        coord = coordinate
    else:
        digits = "".join(ch for ch in vector if ch.isdigit())
        suffix = digits[-4:].lstrip("0") or "10"
        coord = f"1.{suffix}.1.1"
    return (
        f"{year},{geo},2016A000011124,{label},{price},{geodist},"
        f"{uom},239,units,0,{vector},{coord},{value},,,,"
    )


def _basket_payload(rows: list[str], header: str = BASKET_HEADER) -> bytes:
    """Build an in memory basket weights zip from CSV rows."""
    return _zip_bytes({"18100007.csv": ("\n".join([header, *rows])).encode("utf-8")})


def test_basket_parse_live_schema_filters_vintage_slice() -> None:
    """Only the Canada link month slice of the requested year is parsed."""
    rows = [
        _basket_row("41690973", "2.40"),
        _basket_row("41691004", "3.40", product="Other product"),
        _basket_row("1592274355", "0.06", product="Fine product"),
        _basket_row("41690973", "9.99", year="2023", product="Old vintage"),
        _basket_row("41690974", "0.70", geo="Ontario"),
        _basket_row(
            "41690975",
            "1.70",
            price="Weight at basket reference period prices",
        ),
        _basket_row("v41690976", "1.80", product="Prefixed vector"),
    ]
    basket = extract_basket_weights(
        _basket_payload(rows), expenditure_year=2024, link_month="2025-05"
    )
    assert basket.expenditure_year == 2024
    assert basket.link_month == "2025-05"
    assert basket.weights_percent == {
        "41690973": pytest.approx(2.40),
        "41691004": pytest.approx(3.40),
        "1592274355": pytest.approx(0.06),
        "41690976": pytest.approx(1.80),
    }


def test_basket_missing_column_fails() -> None:
    """A basket member without the VALUE column fails closed."""
    header = BASKET_HEADER.replace(",VALUE", ",WEIGHTX")
    rows = [_basket_row("41690973", "2.40")]
    with pytest.raises(ValueError, match="missing column"):
        extract_basket_weights(
            _basket_payload(rows, header=header),
            expenditure_year=2024,
            link_month="2025-05",
        )


def test_basket_empty_vintage_slice_fails() -> None:
    """Requesting a year absent from the member fails closed."""
    rows = [_basket_row("41690973", "2.40", year="2023")]
    with pytest.raises(ValueError, match="expenditure year 2024"):
        extract_basket_weights(_basket_payload(rows), expenditure_year=2024, link_month="2025-05")


def test_basket_non_percent_unit_fails() -> None:
    """A non percent unit in the vintage slice fails closed."""
    rows = [_basket_row("41690973", "2.40", uom="Index")]
    with pytest.raises(ValueError, match="not a percent"):
        extract_basket_weights(_basket_payload(rows), expenditure_year=2024, link_month="2025-05")


def test_basket_missing_weight_fails() -> None:
    """A missing VALUE token in the vintage slice fails instead of skipping."""
    rows = [_basket_row("41690973", "..")]
    with pytest.raises(ValueError, match="missing weight"):
        extract_basket_weights(_basket_payload(rows), expenditure_year=2024, link_month="2025-05")


def test_basket_bad_weight_fails() -> None:
    """A garbage weight token fails closed instead of skipping."""
    rows = [_basket_row("41690973", "abc")]
    with pytest.raises(ValueError, match="non numeric weight"):
        extract_basket_weights(_basket_payload(rows), expenditure_year=2024, link_month="2025-05")


def test_basket_short_vector_fails() -> None:
    """A vector outside the 8 digit classic grammar fails closed."""
    rows = [_basket_row("1234567", "2.40")]
    with pytest.raises(ValueError, match="8 digit"):
        extract_basket_weights(_basket_payload(rows), expenditure_year=2024, link_month="2025-05")


def test_basket_duplicate_vector_fails() -> None:
    """A repeated basket vector fails closed."""
    rows = [
        _basket_row("41690973", "2.40"),
        _basket_row("41690973", "2.40", product="Same vector again"),
    ]
    with pytest.raises(ValueError, match="repeats vector"):
        extract_basket_weights(_basket_payload(rows), expenditure_year=2024, link_month="2025-05")


def test_basket_bad_params_fail() -> None:
    """Non 4 digit years and non YYYY-MM link months fail closed."""
    rows = [_basket_row("41690973", "2.40")]
    payload = _basket_payload(rows)
    with pytest.raises(ValueError, match="link_month"):
        extract_basket_weights(payload, expenditure_year=2024, link_month="2025-13")
    with pytest.raises(ValueError, match="4 digit"):
        extract_basket_weights(payload, expenditure_year=24, link_month="2025-05")
