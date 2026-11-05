"""Bidirectional cap drift tests between limits.py and the web mirrors.

The pipeline caps live in src/goc_rates/limits.py while the web build
script and the web validator carry their own literal copies of the same
numbers. Each test parses those literals with anchored declaration
patterns, so a cap raised on one side must be raised on the mirror in the
same change. A final test seals a synthetic 2490 row backfill document to
prove the raised daily cap still fits the 5 MiB byte budget with
headroom. The repo root resolves from this file so the suite runs from
any working directory.
"""

from __future__ import annotations

import ast
import datetime as dt
import re
from pathlib import Path
from typing import Any

from goc_rates.history import _row_digest, build_backfill_document
from goc_rates.limits import (
    MAX_BACKFILL_BYTES,
    MAX_BACKFILL_CPI_MONTHS,
    MAX_BACKFILL_DAILY_ROWS,
    MAX_HISTORY_OBS,
    MIN_BACKFILL_DAILY_ROWS,
)
from goc_rates.snapshot import canonical_dumps

REPO_ROOT = Path(__file__).resolve().parent.parent
LIMITS_PATH = REPO_ROOT / "src" / "goc_rates" / "limits.py"
BUILD_DATA_PATH = REPO_ROOT / "web" / "scripts" / "build-data.mjs"
VALIDATE_PATH = REPO_ROOT / "web" / "src" / "lib" / "validate.ts"
SNAPSHOT_PATH = REPO_ROOT / "web" / "src" / "lib" / "snapshot.ts"

SYNTHETIC_DAILY_ROWS = 2490  # unit: count, synthetic rows under the raised daily cap
MIB = 1024 * 1024  # unit: bytes, one mebibyte

LIMITS_DAILY = r"^MAX_BACKFILL_DAILY_ROWS: int = (\d+)$"
LIMITS_CPI = r"^MAX_BACKFILL_CPI_MONTHS: int = (\d+)$"
LIMITS_OBS = r"^MAX_HISTORY_OBS: int = (\d+)$"
LIMITS_BYTES = r"^MAX_BACKFILL_BYTES: int = (.+)$"
BUILD_DAILY = r"^const MAX_HISTORY_DAILY = (\d+);$"
BUILD_CPI = r"^const MAX_HISTORY_CPI = (\d+);$"
BUILD_BYTES = r"^const MAX_HISTORY_BYTES = (.+);$"
VALIDATE_DAILY = r"^export const MAX_HISTORY_DAILY = (\d+);$"
VALIDATE_CPI = r"^export const MAX_HISTORY_CPI = (\d+);$"
VALIDATE_OBS = r"^export const MAX_HISTORY_OBS = (\d+);$"
VALIDATE_BYTES = r"^export const MAX_HISTORY_BYTES = (.+);$"
SNAPSHOT_BYTES = r"^export const MAX_JSON_BYTES = (.+);$"

_PROVENANCE: dict[str, Any] = {
    "valet": {
        "source_url": "https://example.invalid/valet/group",
        "retrieved_utc": "2026-11-02T22:15:39+00:00",
        "vintage": "2026-10-30",
    }
}


def _read(path: Path) -> str:
    """Return the UTF8 text of one repo file."""
    return path.read_text(encoding="utf-8")


def _eval_int_expression(text: str) -> int:
    """Evaluate an integer expression built from int constants, *, and +."""

    def evaluate(node: ast.AST) -> int:
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Add)):
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Mult):
                return left * right
            return left + right
        raise AssertionError(f"unsupported cap expression node: {ast.dump(node)}")

    return evaluate(ast.parse(text.strip(), mode="eval").body)


def _const_int(source: str, pattern: str, label: str) -> int:
    """Parse one anchored integer declaration from a source file."""
    match = re.search(pattern, source, flags=re.MULTILINE)
    assert match is not None, f"missing {label} declaration"
    return int(match.group(1))


def _const_expr_int(source: str, pattern: str, label: str) -> int:
    """Parse one anchored integer expression declaration from a source file."""
    match = re.search(pattern, source, flags=re.MULTILINE)
    assert match is not None, f"missing {label} declaration"
    return _eval_int_expression(match.group(1))


def test_daily_cap_matches_web_mirrors() -> None:
    """MAX_BACKFILL_DAILY_ROWS equals MAX_HISTORY_DAILY in both web files."""
    limits_text = _read(LIMITS_PATH)
    build_text = _read(BUILD_DATA_PATH)
    validate_text = _read(VALIDATE_PATH)
    assert _const_int(limits_text, LIMITS_DAILY, "limits MAX_BACKFILL_DAILY_ROWS") == (
        MAX_BACKFILL_DAILY_ROWS
    )
    assert MAX_BACKFILL_DAILY_ROWS == _const_int(
        build_text, BUILD_DAILY, "build-data MAX_HISTORY_DAILY"
    )
    assert MAX_BACKFILL_DAILY_ROWS == _const_int(
        validate_text, VALIDATE_DAILY, "validate MAX_HISTORY_DAILY"
    )


def test_cpi_cap_matches_web_mirrors() -> None:
    """MAX_BACKFILL_CPI_MONTHS equals MAX_HISTORY_CPI in both web files."""
    limits_text = _read(LIMITS_PATH)
    build_text = _read(BUILD_DATA_PATH)
    validate_text = _read(VALIDATE_PATH)
    assert _const_int(limits_text, LIMITS_CPI, "limits MAX_BACKFILL_CPI_MONTHS") == (
        MAX_BACKFILL_CPI_MONTHS
    )
    assert MAX_BACKFILL_CPI_MONTHS == _const_int(
        build_text, BUILD_CPI, "build-data MAX_HISTORY_CPI"
    )
    assert MAX_BACKFILL_CPI_MONTHS == _const_int(
        validate_text, VALIDATE_CPI, "validate MAX_HISTORY_CPI"
    )


def test_history_obs_mirrors_in_validate() -> None:
    """MAX_HISTORY_OBS equals the validate.ts breaks history_count cap."""
    limits_text = _read(LIMITS_PATH)
    validate_text = _read(VALIDATE_PATH)
    assert _const_int(limits_text, LIMITS_OBS, "limits MAX_HISTORY_OBS") == MAX_HISTORY_OBS
    assert MAX_HISTORY_OBS == _const_int(validate_text, VALIDATE_OBS, "validate MAX_HISTORY_OBS")


def test_daily_rows_fit_inside_history_obs_cap() -> None:
    """The daily row cap never exceeds the observation cap it feeds."""
    assert MIN_BACKFILL_DAILY_ROWS <= MAX_BACKFILL_DAILY_ROWS
    assert MAX_BACKFILL_DAILY_ROWS <= MAX_HISTORY_OBS


def test_byte_caps_agree_across_mirrors() -> None:
    """The 5 MiB byte budget agrees in limits.py, the build, and the web libs."""
    limits_text = _read(LIMITS_PATH)
    build_text = _read(BUILD_DATA_PATH)
    validate_text = _read(VALIDATE_PATH)
    snapshot_text = _read(SNAPSHOT_PATH)
    assert _const_expr_int(limits_text, LIMITS_BYTES, "limits MAX_BACKFILL_BYTES") == (
        MAX_BACKFILL_BYTES
    )
    assert MAX_BACKFILL_BYTES == _const_expr_int(
        build_text, BUILD_BYTES, "build-data MAX_HISTORY_BYTES"
    )
    assert MAX_BACKFILL_BYTES == _const_expr_int(
        validate_text, VALIDATE_BYTES, "validate MAX_HISTORY_BYTES"
    )
    assert MAX_BACKFILL_BYTES == _const_expr_int(
        snapshot_text, SNAPSHOT_BYTES, "snapshot MAX_JSON_BYTES"
    )


def _dates_ending(asof_text: str, count: int) -> list[str]:
    """Return count consecutive calendar dates ending at asof_text."""
    asof_day = dt.date.fromisoformat(asof_text)
    return [(asof_day - dt.timedelta(days=offset)).isoformat() for offset in reversed(range(count))]


def _months_ending(end_month: str, count: int) -> list[str]:
    """Return count consecutive YYYY-MM months ending at end_month."""
    year, month = int(end_month[0:4]), int(end_month[5:7])
    months: list[str] = []
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return sorted(months)


def _daily_row(date_text: str) -> dict[str, Any]:
    """Build one daily backfill row in the sealed row shape."""
    body: dict[str, Any] = {
        "date": date_text,
        "yields_percent": {"2Y": 3.28, "5Y": 3.51, "10Y": 3.78, "30Y": 4.11},
        "yields_unit": "percent",
        "slopes_bp": {"2Y_5Y": 23.0, "2Y_10Y": 50.0, "5Y_30Y": 60.0, "10Y_30Y": 33.0},
        "slopes_unit": "basis_points",
        "spreads_bp": {"2Y": -128.0, "5Y": -120.0, "10Y": -116.0, "30Y": -120.0},
        "spreads_unit": "basis_points",
        "spreads_status": "ok",
        "switch_in_window": False,
        "switch_by_tenor": {"2Y": False, "5Y": False, "10Y": False, "30Y": False},
        "calendar_gap": False,
        "verified": False,
        "source": "derived:backfill_v1",
        "snapshot_sha256": None,
        "input_digest_sha256": None,
    }
    return {**body, "row_digest": _row_digest(body)}


def _cpi_row(month: str) -> dict[str, Any]:
    """Build one CPI backfill row in the sealed row shape."""
    body: dict[str, Any] = {
        "month": month,
        "trim_mom_percent": 0.2,
        "median_mom_percent": 0.2,
        "trim_yoy_percent": 2.4,
        "median_yoy_percent": 2.4,
        "mom_unit": "percent_per_month",
        "yoy_unit": "percent",
        "median_component": "C27",
        "verified": False,
        "source": "derived:backfill_v1",
    }
    return {**body, "row_digest": _row_digest(body)}


def test_synthetic_backfill_document_fits_byte_budget() -> None:
    """A 2490 row daily document stays under 5 MiB with real headroom."""
    asof_text = "2026-10-30"
    daily = [_daily_row(day) for day in _dates_ending(asof_text, SYNTHETIC_DAILY_ROWS)]
    cpi = [_cpi_row(month) for month in _months_ending("2026-09", MAX_BACKFILL_CPI_MONTHS)]
    document = build_backfill_document(
        asof_text,
        daily,
        cpi,
        _PROVENANCE,
        [],
        "2026-11-02T22:15:39+00:00",
    )
    assert len(document["daily"]) == SYNTHETIC_DAILY_ROWS
    size_bytes = len(canonical_dumps(document).encode("utf-8"))
    assert size_bytes < MAX_BACKFILL_BYTES, "document must stay under the 5 MiB byte cap"
    assert size_bytes <= 3 * MIB, "document must keep at least 2 MiB of headroom"
    assert size_bytes >= 2 * MIB, "document must be about 2.5 MB, not trivially small"
