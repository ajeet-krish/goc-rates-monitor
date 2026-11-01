"""Verification checks V01 to V12 with a 1.0 basis point tolerance."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from goc_rates.models import ALLOWED_UNITS
from goc_rates.snapshot import MAX_SNAPSHOT_BYTES, atomic_write_text, canonical_dumps

TOLERANCE_BP = 1.0
MIN_SECRET_KEY_SCAN_LENGTH = 4


@dataclass(frozen=True)
class CheckResult:
    """One verification check outcome."""

    check_id: str
    passed: bool
    detail: str


def _get_path(payload: dict[str, Any], *keys: str) -> Any:
    """Walk nested dict keys, returning None when any key is absent."""
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _parse_date(text: Any) -> dt.date | None:
    """Parse a YYYY-MM-DD date string, returning None on failure."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return dt.date.fromisoformat(text.strip())
    except ValueError:
        return None


def _manifest_digest(manifest: Any) -> str | None:
    """Extract the snapshot.json sha256 from either manifest shape."""
    if not isinstance(manifest, dict):
        return None
    direct = manifest.get("snapshot.json")
    if isinstance(direct, dict) and isinstance(direct.get("sha256"), str):
        text = direct["sha256"].strip()
        return text if text else None
    files = manifest.get("files")
    if isinstance(files, dict):
        entry = files.get("snapshot.json")
        if isinstance(entry, dict) and isinstance(entry.get("sha256"), str):
            text = entry["sha256"].strip()
            return text if text else None
    return None


def _quantities(observations: Any) -> list[dict[str, Any]]:
    """Collect quantity dicts from an observations mapping."""
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if {"value", "unit", "quality", "source_id"} <= set(node.keys()):
                found.append(node)
                return
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(observations)
    return found


def _snapshot_text_contains_secret(
    snapshot_text: str,
    manifest_text: str,
    fred_api_key: str | None,
) -> bool:
    """Return True when secret material appears in snapshot or manifest text.

    Flags a literal api_key= query fragment and, when a configured key is
    known, the key value itself. The finding detail never includes the key.
    """
    if "api_key=" in snapshot_text or "api_key=" in manifest_text:
        return True
    key = fred_api_key.strip() if isinstance(fred_api_key, str) else ""
    if len(key) >= MIN_SECRET_KEY_SCAN_LENGTH and (key in snapshot_text or key in manifest_text):
        return True
    return False


def run_checks(
    snapshot: dict[str, Any],
    tolerance_bp: float = TOLERANCE_BP,
    expected_labels: dict[str, str] | None = None,
    fred_api_key: str | None = None,
) -> list[CheckResult]:
    """Run checks V01 to V12 against a snapshot document."""
    results: list[CheckResult] = []
    metadata = snapshot.get("metadata")
    observations = snapshot.get("observations")
    provenance = snapshot.get("provenance")

    try:
        canonical_dumps(snapshot)
        results.append(CheckResult("V01", True, "canonical JSON round trip succeeded"))
    except (ValueError, TypeError) as exc:
        results.append(CheckResult("V01", False, f"canonical JSON failed: {exc}"))

    snapshot_date = _get_path(snapshot, "metadata", "snapshot_date")
    parsed_snapshot_date = _parse_date(snapshot_date)
    if isinstance(metadata, dict) and parsed_snapshot_date is not None:
        results.append(
            CheckResult("V02", True, f"snapshot_date {parsed_snapshot_date.isoformat()} parses")
        )
    else:
        results.append(
            CheckResult("V02", False, "metadata.snapshot_date is missing or unparseable")
        )

    quantities = _quantities(observations) if isinstance(observations, dict) else []
    if observations is None:
        results.append(CheckResult("V03", False, "observations section is missing"))
    elif not quantities:
        results.append(CheckResult("V03", False, "no quantity records found in observations"))
    else:
        bad_units = [
            q
            for q in quantities
            if not str(q.get("unit", "")).strip()
            or str(q.get("unit", "")).strip() not in ALLOWED_UNITS
        ]
        if bad_units:
            results.append(
                CheckResult("V03", False, f"{len(bad_units)} quantities lack a closed set unit")
            )
        else:
            results.append(
                CheckResult("V03", True, f"all {len(quantities)} quantities carry a unit")
            )

    if isinstance(observations, dict) and "benchmarks" in observations:
        benchmarks = observations["benchmarks"]
        if not isinstance(benchmarks, dict) or not benchmarks:
            results.append(CheckResult("V04", False, "benchmark label section is empty"))
        else:
            drift = []
            if expected_labels is not None:
                if set(benchmarks.keys()) != set(expected_labels.keys()):
                    drift.append(
                        f"tenor set {sorted(benchmarks.keys())} != {sorted(expected_labels.keys())}"
                    )
                for tenor, expected in expected_labels.items():
                    entry = benchmarks.get(tenor)
                    if not isinstance(entry, dict):
                        drift.append(str(tenor))
                    elif str(entry.get("valet_label", "")).strip() != expected.strip():
                        drift.append(str(tenor))
            else:
                for tenor, entry in benchmarks.items():
                    if not isinstance(entry, dict) or not str(entry.get("valet_label", "")).strip():
                        drift.append(str(tenor))
            results.append(
                CheckResult(
                    "V04",
                    not drift,
                    "benchmark labels asserted" if not drift else f"label drift: {drift}",
                )
            )
    else:
        results.append(CheckResult("V04", False, "benchmark label section is missing"))

    tbill = _get_path(snapshot, "observations", "tbill_check")
    if isinstance(tbill, dict) and {"yield_percent", "price", "days_to_maturity"} <= set(
        tbill.keys()
    ):
        try:
            recovered = tbill_price_from_yield(
                float(str(tbill["yield_percent"])), int(str(tbill["days_to_maturity"]))
            )
            diff_bp = abs(recovered - float(str(tbill["price"]))) * 100.0
            results.append(
                CheckResult(
                    "V05",
                    diff_bp <= tolerance_bp,
                    f"T-bill price inversion diff {diff_bp:.4f} bp (unit: bp)",
                )
            )
        except (ValueError, TypeError) as exc:
            results.append(CheckResult("V05", False, f"T-bill check failed: {exc}"))
    else:
        results.append(CheckResult("V05", False, "tbill_check section is missing"))

    corra = _get_path(snapshot, "observations", "corra")
    if isinstance(corra, dict):
        value_date = _parse_date(corra.get("value_date"))
        pub_date = _parse_date(corra.get("pub_date"))
        date_role = corra.get("date_role")
        role_ok = isinstance(date_role, str) and bool(date_role.strip())
        ordered = (
            value_date is not None and pub_date is not None and role_ok and value_date <= pub_date
        )
        if ordered:
            assert value_date is not None and pub_date is not None
            results.append(
                CheckResult(
                    "V06", True, f"CORRA {value_date.isoformat()} to {pub_date.isoformat()}"
                )
            )
        else:
            results.append(
                CheckResult("V06", False, "CORRA dates are empty, unparseable, or unordered")
            )
    else:
        results.append(CheckResult("V06", False, "CORRA value_date, pub_date, date_role missing"))

    fred = _get_path(snapshot, "observations", "fred_lag")
    if isinstance(fred, dict):
        observation_date = _parse_date(fred.get("observation_date"))
        note = fred.get("expected_lag_note")
        note_ok = isinstance(note, str) and bool(note.strip())
        lag_ok = True
        if observation_date is not None and parsed_snapshot_date is not None:
            lag_ok = observation_date <= parsed_snapshot_date
        if observation_date is not None and note_ok and lag_ok:
            results.append(CheckResult("V07", True, "FRED T+1 lag note is recorded"))
        else:
            results.append(
                CheckResult("V07", False, "FRED lag note is empty, unparseable, or unordered")
            )
    else:
        results.append(CheckResult("V07", False, "FRED lag note is missing"))

    statcan = _get_path(snapshot, "observations", "statcan")
    if isinstance(statcan, dict) and statcan.get("seasonally_adjusted_reused_as_is") is True:
        results.append(CheckResult("V08", True, "StatCan SA values reused as published"))
    else:
        results.append(CheckResult("V08", False, "StatCan SA reuse flag is missing"))

    if isinstance(provenance, dict) and provenance:
        missing = [
            key
            for key, entry in provenance.items()
            if not isinstance(entry, dict)
            or not str(entry.get("source_url", "")).strip()
            or not str(entry.get("retrieved_utc", "")).strip()
            or not str(entry.get("vintage", "")).strip()
        ]
        results.append(
            CheckResult(
                "V09",
                not missing,
                "vintage markers present" if not missing else f"vintage gaps: {missing}",
            )
        )
    else:
        results.append(CheckResult("V09", False, "provenance section is missing"))

    manifest = snapshot.get("manifest")
    digest = _manifest_digest(manifest)
    if digest is not None:
        results.append(CheckResult("V10", True, "manifest sha256 entry is present"))
    else:
        results.append(CheckResult("V10", False, "manifest sha256 entry is missing"))

    cross = _get_path(snapshot, "observations", "cross_source_diff_bp")
    try:
        snapshot_text = canonical_dumps(snapshot)
    except (ValueError, TypeError):
        snapshot_text = ""
    try:
        manifest_text = canonical_dumps(snapshot.get("manifest", {}))
    except (ValueError, TypeError):
        manifest_text = ""
    if _snapshot_text_contains_secret(snapshot_text, manifest_text, fred_api_key):
        results.append(
            CheckResult(
                "V11",
                False,
                "snapshot or manifest contains API key material; "
                "remove secrets before publishing (unit: none)",
            )
        )
    elif isinstance(cross, dict) and "value_bp" in cross and "unit" in cross:
        try:
            if str(cross["unit"]).strip() != "basis_points":
                results.append(
                    CheckResult(
                        "V11",
                        False,
                        f"cross source unit must be basis_points, got {cross['unit']!r}",
                    )
                )
            else:
                diff = abs(float(str(cross["value_bp"])))
                results.append(
                    CheckResult(
                        "V11",
                        diff <= tolerance_bp,
                        f"cross source diff {diff:.4f} bp within {tolerance_bp} bp (unit: bp)",
                    )
                )
        except (ValueError, TypeError):
            results.append(CheckResult("V11", False, "cross_source_diff_bp is not numeric"))
    else:
        results.append(CheckResult("V11", False, "cross_source_diff_bp section is missing"))

    staleness = _get_path(snapshot, "observations", "staleness")
    if isinstance(staleness, dict) and "max_age_business_days" in staleness:
        try:
            age = int(str(staleness["max_age_business_days"]))
            unit_ok = str(staleness.get("unit", "")).strip() == "business_days"
            passed = 0 <= age <= 5 and unit_ok
            detail = f"max age {age} business days (unit: business_days)"
            if not unit_ok:
                detail = f"staleness unit must be business_days, got {staleness.get('unit')!r}"
            results.append(CheckResult("V12", passed, detail))
        except (ValueError, TypeError):
            results.append(CheckResult("V12", False, "staleness age is not an integer"))
    else:
        results.append(CheckResult("V12", False, "staleness section is missing"))

    return results


def tbill_price_from_yield(yield_percent: float, days_to_maturity: int) -> float:
    """Recover the add-on price P = F / (1 + Y * t / 365) with F = 100.

    Returns price in price_units_per_100_face. Used as a verify cross-check.
    """
    if days_to_maturity <= 0:
        raise ValueError("days_to_maturity must be positive")
    rate = yield_percent / 100.0
    return 100.0 / (1.0 + rate * float(days_to_maturity) / 365.0)


def summarize(results: list[CheckResult], tolerance_bp: float = TOLERANCE_BP) -> dict[str, Any]:
    """Summarize check results into a report dict."""
    passed = sum(1 for item in results if item.passed)
    return {
        "checked_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "tolerance_bp": tolerance_bp,
        "tolerance_unit": "basis_points",
        "passed_count": passed,
        "failed_count": len(results) - passed,
        "passed": passed == len(results),
        "checks": [
            {"id": item.check_id, "passed": item.passed, "detail": item.detail} for item in results
        ],
    }


def verify_snapshot(
    snapshot: dict[str, Any],
    tolerance_bp: float = TOLERANCE_BP,
    expected_labels: dict[str, str] | None = None,
    fred_api_key: str | None = None,
) -> dict[str, Any]:
    """Run all checks and return the report dict."""
    return summarize(
        run_checks(snapshot, tolerance_bp, expected_labels, fred_api_key), tolerance_bp
    )


def _resolve_sibling(value: str | Path) -> Path:
    """Resolve a path without requiring it to exist."""
    return Path(value).resolve()


def verify_file(
    snapshot_path: str | Path,
    out_path: str | Path | None = None,
    tolerance_bp: float = TOLERANCE_BP,
    benchmark_map_path: str | Path | None = None,
    fred_api_key: str | None = None,
) -> int:
    """Verify a snapshot file, write verify.json beside it, return exit code.

    The out_path destination is operator trusted but must not resolve to the
    snapshot or manifest input itself, so verification never overwrites them.
    """
    from goc_rates.clients.fred import read_api_key
    from goc_rates.config import load_benchmark_map

    snapshot_file = Path(snapshot_path)
    if not snapshot_file.is_file():
        raise ValueError(f"snapshot file not found: {snapshot_file}")
    raw = snapshot_file.read_bytes()
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ValueError(
            f"snapshot file of {len(raw)} bytes exceeds the {MAX_SNAPSHOT_BYTES} byte cap"
        )
    try:
        snapshot = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"snapshot file is not valid JSON: {exc}") from None
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot root must be an object")
    effective_key = fred_api_key if fred_api_key is not None else read_api_key()
    expected_labels: dict[str, str] | None = None
    if benchmark_map_path is not None:
        benchmark_map = load_benchmark_map(benchmark_map_path)
        expected_labels = {
            tenor: entry.valet_label for tenor, entry in benchmark_map.benchmarks.items()
        }
    results = run_checks(snapshot, tolerance_bp, expected_labels, effective_key)
    raw_digest = hashlib.sha256(raw).hexdigest()
    manifest_path = snapshot_file.parent / "manifest.json"
    v10_index = next((i for i, item in enumerate(results) if item.check_id == "V10"), None)
    v10_result = CheckResult("V10", False, "manifest sha256 entry is missing")
    manifest_text = ""
    if not manifest_path.is_file():
        v10_result = CheckResult("V10", False, "sibling manifest.json is missing")
    else:
        try:
            manifest_raw = manifest_path.read_bytes()
        except OSError as exc:
            v10_result = CheckResult("V10", False, f"sibling manifest.json unreadable: {exc}")
        else:
            if len(manifest_raw) > MAX_SNAPSHOT_BYTES:
                v10_result = CheckResult("V10", False, "sibling manifest.json exceeds size cap")
            else:
                try:
                    manifest_text = manifest_raw.decode("utf-8")
                    manifest_doc = json.loads(manifest_text)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    v10_result = CheckResult(
                        "V10", False, f"sibling manifest.json unreadable: {exc}"
                    )
                else:
                    expected_digest = _manifest_digest(manifest_doc)
                    if expected_digest is None:
                        v10_result = CheckResult("V10", False, "sibling manifest entry is missing")
                    elif expected_digest != raw_digest:
                        v10_result = CheckResult("V10", False, "manifest sha256 mismatch")
                    else:
                        v10_result = CheckResult("V10", True, "manifest sha256 matches raw bytes")
    if v10_index is not None:
        results[v10_index] = v10_result
    else:
        results.append(v10_result)
    try:
        raw_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raw_text = ""
    if _snapshot_text_contains_secret(raw_text, manifest_text, effective_key):
        v11_index = next((i for i, item in enumerate(results) if item.check_id == "V11"), None)
        secret_result = CheckResult(
            "V11",
            False,
            "snapshot or manifest contains API key material; "
            "remove secrets before publishing (unit: none)",
        )
        if v11_index is not None:
            results[v11_index] = secret_result
        else:
            results.append(secret_result)
    report = summarize(results, tolerance_bp)
    report["snapshot_sha256"] = raw_digest
    destination = Path(out_path) if out_path is not None else snapshot_file.parent / "verify.json"
    resolved_destination = _resolve_sibling(destination)
    if resolved_destination in (
        _resolve_sibling(snapshot_file),
        _resolve_sibling(manifest_path),
    ):
        raise ValueError("verify out_path must not overwrite the snapshot or manifest input")
    atomic_write_text(destination, canonical_dumps(report))
    return 0 if bool(report["passed"]) else 1
