"""Client tests with recorded sanitized fixtures. No live network."""

import json
from pathlib import Path

import httpx
import pytest

from goc_rates.clients.base import BaseClient
from goc_rates.clients.fred import fetch_fred_series
from goc_rates.clients.statcan import fetch_statcan_vectors
from goc_rates.clients.valet import fetch_valet_group, fetch_valet_series

FIXTURES = Path(__file__).parent / "fixtures"


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_valet_series_parses_fixture() -> None:
    """Valet series fetch parses fixture observations with units."""
    body = _read_fixture("valet_group_bond_yields.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "bankofcanada.ca" in str(request.url)
        return httpx.Response(200, text=body)

    client = BaseClient(transport=httpx.MockTransport(handler))
    try:
        rows = fetch_valet_series(
            "BD.CDN.10YR.DQ.YLD",
            client,
            label="10-year benchmark bond yield",
        )
    finally:
        client.close()
    assert len(rows) == 2
    assert rows[0].observation_date == "2026-10-30"
    assert rows[0].quantity["value"] == pytest.approx(3.85)
    assert rows[0].quantity["unit"] == "percent"


def test_valet_label_drift_fails_closed() -> None:
    """Valet label drift raises instead of passing silently."""
    body = _read_fixture("valet_group_bond_yields.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    client = BaseClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ValueError, match="label drift"):
            fetch_valet_series("BD.CDN.10YR.DQ.YLD", client, label="Wrong label")
    finally:
        client.close()


def test_valet_group_asserts_labels() -> None:
    """Valet group fetch asserts every expected label."""
    body = _read_fixture("valet_group_bond_yields.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    client = BaseClient(transport=httpx.MockTransport(handler))
    try:
        groups = fetch_valet_group(
            "bond_yields_benchmark",
            client,
            expected_labels={
                "BD.CDN.10YR.DQ.YLD": "10-year benchmark bond yield",
                "BD.CDN.2YR.DQ.YLD": "2-year benchmark bond yield",
            },
        )
    finally:
        client.close()
    assert set(groups.keys()) == {"BD.CDN.10YR.DQ.YLD", "BD.CDN.2YR.DQ.YLD"}


def test_base_client_retries_then_succeeds() -> None:
    """Base client retries a 503 once and returns the next response."""
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"ok": True})

    client = BaseClient(transport=httpx.MockTransport(handler))
    try:
        response = client.get("https://www.bankofcanada.ca/health")
    finally:
        client.close()
    assert response.status_code == 200
    assert calls["count"] == 2


def test_fred_missing_key_yields_missing_quality() -> None:
    """A missing FRED key returns missing quality without crashing."""
    client = BaseClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="{}"))
    )
    try:
        rows = fetch_fred_series("DGS10", client, api_key=None)
    finally:
        client.close()
    assert len(rows) == 1
    assert rows[0].quantity["quality"] == "missing"
    assert rows[0].quantity["value"] is None


def test_fred_parses_fixture_with_key() -> None:
    """FRED fetch parses recorded observations."""
    body = _read_fixture("fred_dgs10.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.stlouisfed.org" in str(request.url)
        return httpx.Response(200, text=body)

    client = BaseClient(transport=httpx.MockTransport(handler))
    try:
        rows = fetch_fred_series("DGS10", client, api_key="test-key")
    finally:
        client.close()
    assert [row.observation_date for row in rows] == ["2026-10-28", "2026-10-29"]
    assert rows[0].quantity["value"] == pytest.approx(5.05)
    assert rows[0].quantity["unit"] == "percent"


def test_statcan_reuses_values_as_published() -> None:
    """StatCan WDS fetch reuses values with no transformation."""
    body = _read_fixture("statcan_vectors.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload[0]["vectorId"] == 41690973
        return httpx.Response(200, text=body)

    client = BaseClient(transport=httpx.MockTransport(handler))
    try:
        results = fetch_statcan_vectors(["41690973"], client, latest_n=2)
    finally:
        client.close()
    assert results["41690973"][1].reference_period == "2026-10-01"
    assert results["41690973"][1].quantity["value"] == pytest.approx(165.5)


def test_base_client_rejects_non_allowlisted_host() -> None:
    """Hosts outside the three upstreams are rejected before any request."""
    client = BaseClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="{}"))
    )
    try:
        with pytest.raises(ValueError, match="not allowlisted"):
            client.get("https://example.invalid/health")
        with pytest.raises(ValueError, match="not allowlisted"):
            client.post_json("https://example.invalid/submit", {})
    finally:
        client.close()


def test_base_client_rejects_plain_http() -> None:
    """Plain HTTP is rejected even for an allowlisted host."""
    client = BaseClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="{}"))
    )
    try:
        with pytest.raises(ValueError, match="must use https"):
            client.get("http://www.bankofcanada.ca/valet")
    finally:
        client.close()
