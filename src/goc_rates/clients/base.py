"""Shared HTTP client with timeout, retries, and injectable transport."""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Sequence
from email.utils import parsedate_to_datetime
from types import TracebackType
from urllib.parse import urlparse

import httpx

USER_AGENT = "goc-rates-monitor/0.1.0 (+https://github.com/goc-rates-monitor)"
TIMEOUT_SECONDS = 15.0
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (0.5, 1.0, 2.0)
RETRY_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})

ALLOWED_HOSTS = frozenset(
    {
        "www.bankofcanada.ca",
        "www150.statcan.gc.ca",
        "api.stlouisfed.org",
    }
)

MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_OBSERVATIONS = 10000


def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    """Return the delay before the next attempt, honoring Retry-After."""
    retry_after = response.headers.get("retry-after")
    if retry_after is not None:
        text = retry_after.strip()
        try:
            parsed = float(text)
            if parsed >= 0:
                return min(parsed, 30.0)
        except ValueError:
            pass
        try:
            when = parsedate_to_datetime(text)
        except (ValueError, TypeError):
            when = None
        if when is not None:
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.UTC)
            now = dt.datetime.now(dt.UTC)
            delta = (when - now).total_seconds()
            return min(max(delta, 0.0), 30.0)
    index = min(attempt, len(BACKOFF_SECONDS) - 1)
    return BACKOFF_SECONDS[index]


def assert_response_size_ok(response: httpx.Response) -> None:
    """Fail closed when a response exceeds the byte cap.

    Checks the declared Content-Length header when present and the
    buffered body length, so a compromised upstream cannot exhaust memory.
    """
    declared = response.headers.get("content-length")
    if declared is not None:
        try:
            declared_bytes = int(declared.strip())
        except ValueError:
            raise ValueError("upstream sent an unparseable Content-Length") from None
        if declared_bytes < 0:
            raise ValueError("upstream sent a negative Content-Length")
        if declared_bytes > MAX_RESPONSE_BYTES:
            raise ValueError(
                f"upstream response declares {declared_bytes} bytes, "
                f"over the {MAX_RESPONSE_BYTES} byte cap"
            )
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ValueError(
            f"upstream response of {len(response.content)} bytes "
            f"exceeds the {MAX_RESPONSE_BYTES} byte cap"
        )


def parse_json_capped(response: httpx.Response) -> object:
    """Parse a response body as JSON after enforcing the byte cap."""
    assert_response_size_ok(response)
    return response.json()


def ensure_bounded_list(items: Sequence[object], what: str, limit: int = MAX_OBSERVATIONS) -> None:
    """Fail closed when an upstream list exceeds the observation cap."""
    if len(items) > limit:
        raise ValueError(f"{what} has {len(items)} entries, over the cap of {limit}")


def _check_url_allowed(url: str) -> str:
    """Reject URLs outside the HTTPS allowlist of the three upstream hosts."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"upstream URL must use https: {url!r}")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"upstream host is not allowlisted: {host!r}")
    return url


class BaseClient:
    """Thin wrapper over httpx with retry and a fixed User-Agent."""

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        """Create a client, optionally with an injectable test transport."""
        self._client = httpx.Client(
            timeout=TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            transport=transport,
        )

    def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        """GET a URL with retries on 429 and 5xx responses."""
        _check_url_allowed(url)
        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._client.get(url, params=params)
            except httpx.TransportError as exc:
                last_error = exc
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                    continue
                raise
            if response.status_code not in RETRY_STATUS_CODES or attempt == MAX_ATTEMPTS - 1:
                response.raise_for_status()
                return response
            delay = _retry_after_seconds(response, attempt)
            response.close()
            time.sleep(delay)
        if last_error is not None:
            raise last_error
        raise RuntimeError("request retry loop exited without a response")

    def post_json(self, url: str, payload: object) -> httpx.Response:
        """POST a JSON payload with the same retry policy."""
        _check_url_allowed(url)
        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._client.post(url, json=payload)
            except httpx.TransportError as exc:
                last_error = exc
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                    continue
                raise
            if response.status_code not in RETRY_STATUS_CODES or attempt == MAX_ATTEMPTS - 1:
                response.raise_for_status()
                return response
            delay = _retry_after_seconds(response, attempt)
            response.close()
            time.sleep(delay)
        if last_error is not None:
            raise last_error
        raise RuntimeError("request retry loop exited without a response")

    def get_bytes(self, url: str, max_bytes: int) -> bytes:
        """GET a URL and return raw bytes, enforcing a hard streaming byte cap.

        The URL must use https and an allowlisted host, like get. Both the
        declared Content-Length and the streamed body are capped at
        max_bytes with chunked reads, so a compromised upstream cannot
        exhaust memory before the cap trips. Chunks hash incrementally on
        the caller side via hashlib when needed.
        """
        _check_url_allowed(url)
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool):
            raise ValueError("max_bytes must be an int")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                with self._client.stream("GET", url) as response:
                    if response.status_code in RETRY_STATUS_CODES and attempt < MAX_ATTEMPTS - 1:
                        delay = _retry_after_seconds(response, attempt)
                        response.close()
                        time.sleep(delay)
                        continue
                    if response.status_code >= 400:
                        response.read()
                        response.raise_for_status()
                    declared = response.headers.get("content-length")
                    if declared is not None:
                        try:
                            declared_bytes = int(declared.strip())
                        except ValueError:
                            raise ValueError(
                                "upstream sent an unparseable Content-Length"
                            ) from None
                        if declared_bytes < 0:
                            raise ValueError("upstream sent a negative Content-Length")
                        if declared_bytes > max_bytes:
                            raise ValueError(
                                f"upstream response declares {declared_bytes} bytes, "
                                f"over the {max_bytes} byte cap"
                            )
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes(chunk_size=65536):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError(
                                f"upstream response of over {max_bytes} bytes "
                                f"exceeds the {max_bytes} byte cap"
                            )
                        chunks.append(chunk)
                    return b"".join(chunks)
            except httpx.TransportError as exc:
                last_error = exc
                if attempt < MAX_ATTEMPTS - 1:
                    time.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("request retry loop exited without a response")

    def close(self) -> None:
        """Close the underlying connection pool."""
        self._client.close()

    def __enter__(self) -> BaseClient:
        """Enter the context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Exit the context manager and close the client."""
        self.close()
