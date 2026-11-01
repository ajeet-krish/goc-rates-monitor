"""Snapshot writer tests: canonical form, atomic writes, manifest, retention."""

import json
from pathlib import Path

import pytest

from goc_rates.snapshot import (
    build_snapshot,
    canonical_dumps,
    prune_raw_cache,
    write_snapshot,
)


def _sample_snapshot() -> dict[str, object]:
    return build_snapshot(
        "2026-10-30",
        {"benchmarks": {"10Y": {"valet_label": "10-year benchmark bond yield"}}},
        {
            "valet": {
                "source_url": "https://www.bankofcanada.ca/valet/",
                "retrieved_utc": "2026-10-31T00:00:00Z",
                "vintage": "2026-10-30",
            }
        },
    )


def test_canonical_dumps_is_sorted_with_lf() -> None:
    """Canonical dumps sorts keys, indents by 2, and ends with LF."""
    text = canonical_dumps({"b": 1, "a": 2})
    assert text == '{\n  "a": 2,\n  "b": 1\n}\n'
    assert text.endswith("\n")
    assert "\r" not in text


def test_canonical_dumps_rejects_nan() -> None:
    """Non finite floats are rejected instead of serialized."""
    with pytest.raises(ValueError):
        canonical_dumps({"value": float("nan")})


def test_write_snapshot_produces_manifest(tmp_path: Path) -> None:
    """Snapshot writes produce a manifest with a matching sha256."""
    snapshot = _sample_snapshot()
    digests = write_snapshot(tmp_path / "2026-10-30", snapshot)
    snapshot_text = (tmp_path / "2026-10-30" / "snapshot.json").read_text(encoding="utf-8")
    manifest = json.loads((tmp_path / "2026-10-30" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"]["snapshot.json"]["sha256"] == digests["snapshot.json"]
    assert snapshot_text == canonical_dumps(snapshot)


def test_build_snapshot_fails_closed_on_empty_sections() -> None:
    """Empty observations or provenance raise."""
    with pytest.raises(ValueError):
        build_snapshot("2026-10-30", {}, {"a": {"x": 1}})
    with pytest.raises(ValueError):
        build_snapshot("2026-10-30", {"a": 1}, {})


def test_write_snapshot_rejects_symlink_directory(tmp_path: Path) -> None:
    """A symlinked snapshot directory is rejected instead of followed."""
    snapshot = _sample_snapshot()
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "2026-10-30"
    link.symlink_to(real_dir, target_is_directory=True)
    with pytest.raises(ValueError, match="must not be a symlink"):
        write_snapshot(link, snapshot)


def test_prune_raw_cache_keeps_most_recent_only(tmp_path: Path) -> None:
    """Raw retention prunes old cache files and leaves snapshots alone."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    for name in ("a.raw.json", "b.raw.json", "c.raw.json"):
        target = raw_dir / name
        target.write_text("{}", encoding="utf-8")
    removed = prune_raw_cache(raw_dir, keep_most_recent=1)
    assert len(removed) == 2
    assert len(list(raw_dir.iterdir())) == 1
