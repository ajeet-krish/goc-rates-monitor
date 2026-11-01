"""Snapshot writer: canonical JSON, atomic writes, manifest, raw retention."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

MAX_SNAPSHOT_BYTES = 10 * 1024 * 1024

RAW_CACHE_FILENAME_SUFFIX = ".raw.json"


def canonical_dumps(payload: dict[str, Any]) -> str:
    """Serialize with sorted keys, indent 2, LF ending, and strict floats."""
    text = json.dumps(
        payload,
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    )
    return text + "\n"


def sha256_text(text: str) -> str:
    """Return the hex sha256 of UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically with a temp file plus rename.

    The temp file is fsynced before the rename and the parent directory
    is fsynced after the rename so a crash cannot leave a half written
    snapshot behind on a loss of power.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        _fsync_dir(path.parent)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _fsync_dir(directory: Path) -> None:
    """Fsync a directory so the rename above is durable. Best effort."""
    flags = getattr(os, "O_DIRECTORY", 0)
    try:
        dir_fd = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def build_snapshot(
    snapshot_date: str,
    observations: dict[str, Any],
    provenance: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build the snapshot document, failing closed on missing sections."""
    if not isinstance(snapshot_date, str) or not snapshot_date.strip():
        raise ValueError("snapshot_date must be a non empty string")
    try:
        normalized_date = dt.date.fromisoformat(snapshot_date.strip()).isoformat()
    except ValueError:
        raise ValueError(f"snapshot_date must be ISO YYYY-MM-DD: {snapshot_date!r}") from None
    if not isinstance(observations, dict) or not observations:
        raise ValueError("observations must be a non empty mapping")
    if not isinstance(provenance, dict) or not provenance:
        raise ValueError("provenance must be a non empty mapping")
    provenance_text = canonical_dumps(provenance)
    if "api_key=" in provenance_text:
        raise ValueError("provenance must not contain API key material")
    return {
        "metadata": {
            "snapshot_date": normalized_date,
            "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "schema_version": 1,
        },
        "observations": observations,
        "provenance": provenance,
        "warnings": list(warnings) if warnings is not None else [],
    }


def write_snapshot(snapshot_dir: str | Path, snapshot: dict[str, Any]) -> dict[str, str]:
    """Write snapshot.json plus manifest.json and return their sha256 digests."""
    from goc_rates.dates import parse_strict_iso_date

    directory = Path(snapshot_dir)
    if directory.is_symlink():
        raise ValueError(f"snapshot directory must not be a symlink: {directory}")
    metadata = snapshot.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("snapshot metadata must be a mapping")
    date_text = metadata.get("snapshot_date")
    if not isinstance(date_text, str):
        raise ValueError("metadata.snapshot_date must be a string")
    normalized = parse_strict_iso_date(date_text).isoformat()
    if directory.name != normalized:
        raise ValueError(
            f"snapshot directory {directory.name!r} must match snapshot_date {normalized!r}"
        )
    directory.mkdir(parents=True, exist_ok=True)
    if directory.resolve().name != normalized:
        raise ValueError(
            f"resolved snapshot directory {directory.resolve().name!r} "
            f"must match snapshot_date {normalized!r}"
        )
    snapshot_text = canonical_dumps(snapshot)
    snapshot_digest = sha256_text(snapshot_text)
    atomic_write_text(directory / "snapshot.json", snapshot_text)
    manifest = {
        "files": {
            "snapshot.json": {
                "sha256": snapshot_digest,
                "bytes_utf8": len(snapshot_text.encode("utf-8")),
            }
        }
    }
    manifest_text = canonical_dumps(manifest)
    atomic_write_text(directory / "manifest.json", manifest_text)
    return {
        "snapshot.json": snapshot_digest,
        "manifest.json": sha256_text(manifest_text),
    }


def prune_raw_cache(raw_dir: str | Path, keep_most_recent: int = 5) -> list[str]:
    """Prune raw cache files, keeping only the most recent N. Retention is raw only.

    Only regular files named *.raw.json directly inside raw_dir are pruned.
    Symlinked directories and symlinked files are never followed or removed.
    """
    if keep_most_recent < 0:
        raise ValueError("keep_most_recent must be non negative")
    directory = Path(raw_dir)
    if directory.is_symlink():
        raise ValueError(f"raw cache directory must not be a symlink: {directory}")
    if not directory.is_dir():
        return []
    stamped: list[tuple[Path, float]] = []
    for path in directory.iterdir():
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        if path.name != path.name.strip() or not path.name.endswith(RAW_CACHE_FILENAME_SUFFIX):
            continue
        stamped.append((path, path.stat().st_mtime))
    stamped.sort(key=lambda item: item[1])
    files = [path for path, _mtime in stamped]
    excess = len(files) - keep_most_recent
    removed: list[str] = []
    for index in range(excess):
        files[index].unlink()
        removed.append(files[index].name)
    return removed
