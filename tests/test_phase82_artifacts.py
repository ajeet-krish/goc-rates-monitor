"""Phase 8.2 re-sealed artifact acceptance: backfill, manifest, merged history.

Phase 8.2 re-sealed history/backfill.json with the raised 3653 day window
and published the regenerated snapshot triples through the merge. These
tests accept that re-seal: the backfill keeps between 2400 and 2750 daily
rows spanning at least 9.5 calendar years with every row unverified and
null snapshot sha, the manifest binds the file bytes, the sealed document
roundtrips through the Python builder, and the merged history.json count
equals backfill rows plus snapshot-only dates minus overlaps with exactly
the four re-sealed verified dates and 60 CPI months.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from goc_rates.history import build_backfill_document
from goc_rates.limits import MAX_BACKFILL_BYTES, MAX_BACKFILL_CPI_MONTHS, MAX_BACKFILL_DAILY_ROWS

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKFILL_PATH = REPO_ROOT / "history" / "backfill.json"
MANIFEST_PATH = REPO_ROOT / "history" / "backfill-manifest.json"
HISTORY_PATH = REPO_ROOT / "web" / "public" / "data" / "history.json"
INDEX_PATH = REPO_ROOT / "web" / "public" / "data" / "index.json"

MIN_DAILY_ROWS = 2400  # unit: count, re-seal floor under the raised daily cap
SPAN_FLOOR_DAYS = 3469  # unit: days, 9.5 calendar years of sealed history
FIRST_DATE_PIN = "2016-12-05"  # date, ten year window start for this re-seal
ASOF_TOLERANCE_DAYS = 3  # unit: days, last print within 3 days of the asof
EXPECTED_CPI_MONTHS = 60  # unit: count, sealed trailing CPI window
EXPECTED_VERIFIED_DATES = ("2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04")


def _load(path: Path) -> dict[str, Any]:
    """Read one committed JSON artifact as a mapping."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"{path.name} must hold a JSON object"
    return payload


BACKFILL = _load(BACKFILL_PATH)
MANIFEST = _load(MANIFEST_PATH)
HISTORY = _load(HISTORY_PATH)
INDEX = _load(INDEX_PATH)


def test_backfill_daily_rows_sit_between_floor_and_cap() -> None:
    """The re-sealed backfill keeps 2400 to 2750 daily rows with matching metadata."""
    rows = BACKFILL["daily"]
    assert MIN_DAILY_ROWS <= len(rows) <= MAX_BACKFILL_DAILY_ROWS
    assert BACKFILL["metadata"]["daily_count"] == len(rows)
    assert BACKFILL["metadata"]["daily_count_unit"] == "count"
    assert BACKFILL["metadata"]["method"] == "backfill_v1"
    assert BACKFILL["metadata"]["schema_version"] == 1


def test_backfill_span_covers_ten_years_ending_at_the_asof() -> None:
    """The daily span starts on or before the pinned date and ends at the asof."""
    dates = [row["date"] for row in BACKFILL["daily"]]
    first = dt.date.fromisoformat(dates[0])
    last = dt.date.fromisoformat(dates[-1])
    asof = dt.date.fromisoformat(BACKFILL["metadata"]["asof"])
    assert dates[0] <= FIRST_DATE_PIN, "window must reach back ten calendar years"
    assert abs((last - asof).days) <= ASOF_TOLERANCE_DAYS, "last print must sit at the asof"
    assert (last - first).days >= SPAN_FLOOR_DAYS, "span must cover at least 9.5 calendar years"


def test_backfill_rows_all_unverified_with_null_snapshot_sha() -> None:
    """Every sealed backfill row stays unverified with a null snapshot sha."""
    for row in BACKFILL["daily"]:
        date_text = row["date"]
        assert row["verified"] is False, f"{date_text} must not claim verification"
        assert row["snapshot_sha256"] is None, f"{date_text} must carry a null snapshot sha"
        assert row["input_digest_sha256"] is None
        assert row["source"] == "derived:backfill_v1"
    for row in BACKFILL["cpi"]:
        assert row["verified"] is False
        assert row["source"] == "derived:backfill_v1"


def test_backfill_dates_strictly_ascending_and_unique() -> None:
    """Daily dates increase strictly with no duplicates."""
    dates = [row["date"] for row in BACKFILL["daily"]]
    assert dates == sorted(dates)
    assert len(set(dates)) == len(dates)
    for previous, current in zip(dates, dates[1:], strict=False):
        assert previous < current, "daily dates must increase strictly"
    months = [row["month"] for row in BACKFILL["cpi"]]
    assert months == sorted(months)
    assert len(set(months)) == len(months)


def test_backfill_manifest_binds_the_file_bytes() -> None:
    """The manifest sha256 and byte count match the committed backfill bytes."""
    raw = BACKFILL_PATH.read_bytes()
    entry = MANIFEST["files"]["backfill.json"]
    assert entry["sha256"] == hashlib.sha256(raw).hexdigest()
    assert entry["bytes_utf8"] == len(raw)
    assert len(raw) <= MAX_BACKFILL_BYTES, "backfill must stay under the 5 MiB byte cap"


def test_backfill_document_roundtrips_through_the_sealer() -> None:
    """The sealed document rebuilds byte for byte through build_backfill_document."""
    rebuilt = build_backfill_document(
        BACKFILL["metadata"]["asof"],
        BACKFILL["daily"],
        BACKFILL["cpi"],
        BACKFILL["provenance"],
        BACKFILL["exclusions"],
        BACKFILL["retrieved_utc"],
    )
    assert rebuilt == BACKFILL, "every row digest, count, and cap must reseal identically"


def test_merged_history_count_matches_backfill_plus_snapshot_only_dates() -> None:
    """history.json daily count equals backfill rows plus snapshot-only dates."""
    backfill_dates = {row["date"] for row in BACKFILL["daily"]}
    snapshot_dates = list(INDEX["dates"])
    snapshot_only = [date for date in snapshot_dates if date not in backfill_dates]
    overlaps = [date for date in snapshot_dates if date in backfill_dates]
    assert len(overlaps) + len(snapshot_only) == len(snapshot_dates)
    expected = len(BACKFILL["daily"]) + len(snapshot_only)
    assert HISTORY["metadata"]["daily_count"] == expected
    assert len(HISTORY["daily"]) == expected
    assert MIN_DAILY_ROWS <= expected <= MAX_BACKFILL_DAILY_ROWS
    history_dates = [row["date"] for row in HISTORY["daily"]]
    assert history_dates == sorted(history_dates)
    assert len(set(history_dates)) == len(history_dates)
    assert backfill_dates <= set(history_dates), "every backfill date survives the merge"


def test_merged_history_pins_the_four_resealed_verified_dates() -> None:
    """Exactly the four re-sealed snapshots promote to verified rows."""
    verified = [row for row in HISTORY["daily"] if row["verified"]]
    assert tuple(row["date"] for row in verified) == EXPECTED_VERIFIED_DATES
    index_shas = {INDEX["entries"][date]["snapshot_sha256"] for date in EXPECTED_VERIFIED_DATES}
    row_shas = {row["snapshot_sha256"] for row in verified}
    assert row_shas == index_shas, "verified rows must carry the committed snapshot shas"
    for row in verified:
        assert row["source"] == "derived:history_verified_v1"
        assert isinstance(row["snapshot_sha256"], str)
    backfill_only = [row for row in HISTORY["daily"] if row["date"] not in EXPECTED_VERIFIED_DATES]
    assert backfill_only, "the merged history must keep backfill rows beside the verified ones"
    for row in backfill_only:
        assert row["verified"] is False
        assert row["snapshot_sha256"] is None
        assert row["source"] == "derived:backfill_v1"


def test_merged_history_keeps_the_sixty_cpi_months() -> None:
    """The merge keeps all 60 sealed CPI months with zero verified promotions."""
    assert HISTORY["metadata"]["cpi_count"] == EXPECTED_CPI_MONTHS
    assert len(HISTORY["cpi"]) == EXPECTED_CPI_MONTHS
    assert len(BACKFILL["cpi"]) == EXPECTED_CPI_MONTHS
    assert EXPECTED_CPI_MONTHS <= MAX_BACKFILL_CPI_MONTHS
    assert [row["month"] for row in HISTORY["cpi"]] == [row["month"] for row in BACKFILL["cpi"]]
    for row in HISTORY["cpi"]:
        assert row["verified"] is False


def test_merged_history_metadata_and_exclusions_match_the_seal() -> None:
    """The merged document keeps the backfill method, asof, and exclusion list."""
    assert HISTORY["metadata"]["method"] == "history_merge_v1"
    assert HISTORY["metadata"]["schema_version"] == 1
    assert HISTORY["metadata"]["asof"] == BACKFILL["metadata"]["asof"]
    assert HISTORY["exclusions"] == BACKFILL["exclusions"]
    assert sorted(HISTORY["provenance"]) == sorted(BACKFILL["provenance"])


def test_index_history_entry_binds_the_published_history_bytes() -> None:
    """index.json history entry sha, byte count, and trim count bind history.json."""
    raw = HISTORY_PATH.read_bytes()
    entry = INDEX["history"]
    assert entry["sha256"] == hashlib.sha256(raw).hexdigest()
    assert entry["bytes_utf8"] == len(raw)
    assert entry["daily_count"] == len(HISTORY["daily"])
    assert entry["cpi_count"] == len(HISTORY["cpi"])
    assert entry["trimmed_backfilled_count"] == 0, "the re-seal must publish with zero trims"
    assert len(raw) <= MAX_BACKFILL_BYTES, "history.json must stay under the 5 MiB byte cap"


def test_index_latest_and_dates_cover_the_resealed_snapshots() -> None:
    """The index lists the four re-sealed dates with verify passing on each."""
    assert INDEX["latest"] == EXPECTED_VERIFIED_DATES[-1]
    assert tuple(INDEX["dates"]) == EXPECTED_VERIFIED_DATES
    for date in EXPECTED_VERIFIED_DATES:
        entry = INDEX["entries"][date]
        assert entry["verify_passed"] is True
        manifest_path = REPO_ROOT / "snapshots" / date / "manifest.json"
        manifest = _load(manifest_path)
        assert entry["snapshot_sha256"] == manifest["files"]["snapshot.json"]["sha256"]
