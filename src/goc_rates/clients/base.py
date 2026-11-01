"""Shared HTTP client with timeout, retries, and injectable transport."""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Sequence
from email.utils import parsedate_to_datetime
from types import TracebackType

import httpx

USER_AGENT = "goc-rates-monitor/0.1.0 (+https://github.com/goc-rates-monitor)"
TIMEOUT_SECONDS = 15.0
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (0.5, 1.0, 2.0)
RETRY_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})

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
