"""Verification checks V01 to V23 with a 1.0 basis point tolerance."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from goc_rates.curve import (
    CURVE_METHOD,
    Curve,
    CurveKnot,
    bill_price_from_yield,
    build_par_curve,
    discount_factor,
    reprice_par_yield_bp,
    zero_yield,
)
from goc_rates.dates import parse_strict_iso_date
from goc_rates.limits import MAX_BACKTEST_OBS, MAX_QUANTITIES, MAX_SPREAD_RECORDS
from goc_rates.models import ALLOWED_UNITS, validate_source_id
from goc_rates.snapshot import MAX_SNAPSHOT_BYTES, atomic_write_text, canonical_dumps

TOLERANCE_BP = 1.0
MIN_SECRET_KEY_SCAN_LENGTH = 4

__all__ = [
    "TOLERANCE_BP",
    "CheckResult",
    "bill_price_from_yield",
    "tbill_price_from_yield",
    "run_checks",
    "summarize",
    "verify_snapshot",
    "verify_file",
]


def tbill_price_from_yield(yield_percent: float, days_to_maturity: int) -> float:
    """Legacy verify entry point, delegated to the curve engine."""
    return bill_price_from_yield(yield_percent, days_to_maturity)


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
    """Parse an exact YYYY-MM-DD date string, returning None on failure."""
    if not isinstance(text, str):
        return None
    try:
        return parse_strict_iso_date(text)
    except ValueError:
        return None


def _require_float(value: Any, name: str) -> float:
    """Require a finite int or float without string coercion."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric without string coercion")
    result = float(value)
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be finite")
    return result


def _require_int(value: Any, name: str) -> int:
    """Require an int without string coercion."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int without string coercion")
    return value


def _require_str(value: Any, name: str) -> str:
    """Require a non empty string without coercion."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non empty string")
    return value


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
    """Run checks V01 to V23 against a snapshot document."""
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
            if len(_quantities(snapshot.get("observations"))) > MAX_QUANTITIES:
                raise ValueError("quantity count exceeds the cap before recompute")
            recovered = tbill_price_from_yield(
                _require_float(tbill["yield_percent"], "yield_percent"),
                _require_int(tbill["days_to_maturity"], "days_to_maturity"),
            )
            diff_bp = abs(recovered - _require_float(tbill["price"], "price")) * 100.0
            results.append(
                CheckResult(
                    "V05",
                    diff_bp <= tolerance_bp,
                    f"T-bill price inversion diff {diff_bp:.4f} bp (unit: bp)",
                )
            )
        except (ValueError, TypeError, ArithmeticError) as exc:
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
                diff = abs(_require_float(cross["value_bp"], "value_bp"))
                results.append(
                    CheckResult(
                        "V11",
                        diff <= tolerance_bp,
                        f"cross source diff {diff:.4f} bp within {tolerance_bp} bp (unit: bp)",
                    )
                )
        except (ValueError, TypeError, ArithmeticError):
            results.append(CheckResult("V11", False, "cross_source_diff_bp is not numeric"))
    else:
        results.append(CheckResult("V11", False, "cross_source_diff_bp section is missing"))

    staleness = _get_path(snapshot, "observations", "staleness")
    if isinstance(staleness, dict) and "max_age_business_days" in staleness:
        try:
            age = _require_int(staleness["max_age_business_days"], "max_age_business_days")
            unit_ok = str(staleness.get("unit", "")).strip() == "business_days"
            passed = 0 <= age <= 5 and unit_ok
            detail = f"max age {age} business days (unit: business_days)"
            if not unit_ok:
                detail = f"staleness unit must be business_days, got {staleness.get('unit')!r}"
            results.append(CheckResult("V12", passed, detail))
        except (ValueError, TypeError, ArithmeticError):
            results.append(CheckResult("V12", False, "staleness age is not an integer"))
    else:
        results.append(CheckResult("V12", False, "staleness section is missing"))

    results.extend(_run_phase2_checks(snapshot, tolerance_bp, fred_api_key))
    results.extend(_run_phase4_checks(snapshot))
    results.extend(_run_phase5_checks(snapshot, tolerance_bp))

    return results


def _curve_section(snapshot: dict[str, Any]) -> Any:
    """Return the curve section dict or None."""
    return _get_path(snapshot, "observations", "curve")


def _derived_quantities(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect Quantity dicts under curve, derived, spreads, risk, backtest."""
    observations = snapshot.get("observations")
    if not isinstance(observations, dict):
        return []
    collected: list[dict[str, Any]] = []
    for key in (
        "curve",
        "derived",
        "spreads",
        "canada_us_spreads",
        "carry",
        "risk",
        "backtest",
        "breaks",
    ):
        section = observations.get(key)
        if isinstance(section, (dict, list)):
            collected.extend(_quantities(section))
    return collected


def _spreads_envelope(snapshot: dict[str, Any]) -> Any:
    """Return the spreads envelope mapping from any known section, else None.

    The envelope is the typed mapping with status, reason, and records.
    Legacy arrays are returned as is so V16 can fail closed with an
    explicit envelope message instead of passing vacuously.
    """
    observations = snapshot.get("observations")
    if not isinstance(observations, dict):
        return None
    for key in ("spreads", "canada_us_spreads"):
        if key in observations:
            return observations.get(key)
    derived = observations.get("derived")
    if isinstance(derived, dict):
        for key in ("spreads", "canada_us_spreads"):
            if key in derived:
                return derived.get(key)
    return None


def _carry_section(snapshot: dict[str, Any]) -> Any:
    """Return the carry section dict or None."""
    carry = _get_path(snapshot, "observations", "carry")
    if isinstance(carry, dict):
        return carry
    return _get_path(snapshot, "observations", "derived", "carry")


def _risk_section(snapshot: dict[str, Any]) -> Any:
    """Return the risk section dict or None."""
    return _get_path(snapshot, "observations", "risk")


def _backtest_section(snapshot: dict[str, Any]) -> Any:
    """Return the backtest section dict or None."""
    return _get_path(snapshot, "observations", "backtest")


def _is_degraded_missing(section: Any, fred_api_key: str | None) -> bool:
    """Return True when a section is an explicit FRED degraded missing marker.

    Degraded passes are narrow: the FRED key must be absent, the section
    must be a mapping with status missing, and the reason must be non empty.
    A configured key never takes the degraded path so missing data with a
    live US leg still fails closed.
    """
    if fred_api_key is not None and str(fred_api_key).strip():
        return False
    if not isinstance(section, dict):
        return False
    if section.get("status") != "missing":
        return False
    reason = section.get("reason")
    return isinstance(reason, str) and bool(reason.strip())


def _run_phase2_checks(
    snapshot: dict[str, Any],
    tolerance_bp: float,
    fred_api_key: str | None = None,
) -> list[CheckResult]:
    """Run checks V13 to V18 for the Phase 2 curve engine."""
    from goc_rates.analytics import canada_us_spread_bp, carry_roll_bp
    from goc_rates.backtest import BACKTEST_RULE, run_backtest
    from goc_rates.live_snapshot import FRED_DEGRADED_REASON
    from goc_rates.live_snapshot import TENORS as SPREAD_TENORS
    from goc_rates.risk import dv01_per_million, modified_duration, par_bond_price

    results: list[CheckResult] = []

    curve_section = _curve_section(snapshot)
    curve: Curve | None = None
    if not isinstance(curve_section, dict):
        results.append(CheckResult("V13", False, "curve section is missing"))
        results.append(CheckResult("V14", False, "curve section is missing"))
        results.append(CheckResult("V15", False, "derived curve quantities are missing"))
    else:
        try:
            if curve_section.get("method") != CURVE_METHOD:
                raise ValueError(f"curve method must be {CURVE_METHOD}")
            if curve_section.get("is_par_approx") is not True:
                raise ValueError("curve is_par_approx must be true")
            if curve_section.get("is_zero") is not False:
                raise ValueError("curve is_zero must be false")
            knots_raw = curve_section.get("knots")
            if not isinstance(knots_raw, list) or not knots_raw:
                raise ValueError("curve knots are missing")
            if len(knots_raw) > MAX_QUANTITIES:
                raise ValueError("knot count exceeds the cap before recompute")
            knots: list[CurveKnot] = []
            for row in knots_raw:
                if not isinstance(row, dict):
                    raise ValueError("curve knot rows must be mappings")
                label_raw = row.get("tenor", "")
                if not isinstance(label_raw, str) or not label_raw.strip():
                    raise ValueError("curve knot tenor is missing")
                label = label_raw.strip()
                tenor_years = _require_float(row.get("tenor_years", ""), "tenor_years")
                yield_percent = _require_float(row.get("yield_percent", ""), "yield_percent")
                knots.append(
                    CurveKnot(
                        tenor_label=label, tenor_years=tenor_years, yield_percent=yield_percent
                    )
                )
            curve = build_par_curve(knots)
            labels = [knot.tenor_label for knot in curve.knots]
            if labels != ["2Y", "5Y", "10Y", "30Y"]:
                raise ValueError(f"curve tenor set must be 2Y 5Y 10Y 30Y, got {labels}")
            worst = 0.0
            for knot in curve.knots:
                error = abs(reprice_par_yield_bp(curve, knot.tenor_years))
                worst = max(worst, error)
            stored_rows = knots_raw
            assert isinstance(stored_rows, list)
            for row, knot in zip(stored_rows, curve.knots, strict=False):
                assert isinstance(row, dict)
                stored_discount = _require_float(row.get("discount", ""), "discount")
                recomputed = discount_factor(curve, knot.tenor_years)
                if stored_discount <= 0.0:
                    raise ValueError("stored discount must be positive")
                yield_error_bp = (
                    abs(zero_yield(curve, knot.tenor_years) - knot.yield_percent) * 100.0
                )
                discount_implied_bp = abs(recomputed - stored_discount) / stored_discount * 10000.0
                worst = max(worst, yield_error_bp, discount_implied_bp)
            stored_discounts = curve_section.get("discounts")
            stored_zeros = curve_section.get("zero_yields")
            if not isinstance(stored_discounts, dict) or not isinstance(stored_zeros, dict):
                raise ValueError("stored discounts and zero_yields mappings are missing")
            for label in ("2Y", "5Y", "10Y", "30Y"):
                knot = next(item for item in curve.knots if item.tenor_label == label)
                discount_entry = stored_discounts.get(label)
                zero_entry = stored_zeros.get(label)
                if not isinstance(discount_entry, dict) or not isinstance(zero_entry, dict):
                    raise ValueError(f"stored mapping for {label} must be a Quantity")
                stored_d = _require_float(discount_entry.get("value", ""), "discount value")
                stored_z = _require_float(zero_entry.get("value", ""), "zero value")
                recomputed_d = discount_factor(curve, knot.tenor_years)
                recomputed_z = zero_yield(curve, knot.tenor_years)
                if stored_d <= 0.0:
                    raise ValueError(f"stored discount for {label} must be positive")
                discount_bp = abs(recomputed_d - stored_d) / stored_d * 10000.0
                zero_bp = abs(recomputed_z - stored_z) * 100.0
                worst = max(worst, discount_bp, zero_bp)
            results.append(
                CheckResult(
                    "V13",
                    worst <= tolerance_bp,
                    f"curve reprice worst {worst:.4f} bp within {tolerance_bp} bp (unit: bp)",
                )
            )
        except (ValueError, TypeError, ArithmeticError) as exc:
            results.append(CheckResult("V13", False, f"curve reprice failed: {exc}"))
            curve = None
        try:
            knots_raw = curve_section.get("knots")
            if not isinstance(knots_raw, list) or not knots_raw:
                raise ValueError("curve knots are missing")
            if len(knots_raw) > MAX_QUANTITIES:
                raise ValueError("knot count exceeds the cap before recompute")
            tenors: list[float] = []
            discounts: list[float] = []
            for row in knots_raw:
                if not isinstance(row, dict):
                    raise ValueError("curve knot rows must be mappings")
                tenors.append(_require_float(row.get("tenor_years", ""), "tenor_years"))
                discounts.append(_require_float(row.get("discount", ""), "discount"))
            in_range = all(0.0 < item <= 1.0 for item in discounts)
            increasing = all(
                second > first for first, second in zip(tenors, tenors[1:], strict=False)
            )
            decreasing = all(
                first > second for first, second in zip(discounts, discounts[1:], strict=False)
            )
            passed = in_range and increasing and decreasing and len(tenors) >= 3
            detail = (
                "discounts in (0, 1] and strictly decreasing "
                "with increasing tenors (unit: unitless_ratio)"
            )
            if not passed:
                detail = "discount monotonicity or range failed (unit: unitless_ratio)"
            results.append(CheckResult("V14", passed, detail))
        except (ValueError, TypeError, ArithmeticError) as exc:
            results.append(CheckResult("V14", False, f"discount check failed: {exc}"))
        try:
            derived = _derived_quantities(snapshot)
            if len(derived) > MAX_QUANTITIES:
                raise ValueError("derived quantity count exceeds the cap before recompute")
            if not derived:
                raise ValueError("no derived quantities found")
            bad_units = [
                item for item in derived if str(item.get("unit", "")).strip() not in ALLOWED_UNITS
            ]
            bad_source: list[Any] = []
            for item in derived:
                source = item.get("source_id", "")
                try:
                    validate_source_id(source)
                except ValueError:
                    bad_source.append(item)
                    continue
                if not str(source).startswith("derived:"):
                    bad_source.append(item)
            if bad_units or bad_source:
                raise ValueError(f"{len(bad_units)} bad units, {len(bad_source)} bad sources")
            results.append(
                CheckResult(
                    "V15",
                    True,
                    f"all {len(derived)} derived quantities carry units "
                    "and a derived source (unit: mixed)",
                )
            )
        except (ValueError, TypeError, ArithmeticError) as exc:
            results.append(CheckResult("V15", False, f"derived check failed: {exc}"))

    envelope = _spreads_envelope(snapshot)
    if not isinstance(envelope, dict):
        if isinstance(envelope, list):
            results.append(
                CheckResult(
                    "V16",
                    False,
                    "spread envelope must be a mapping with "
                    "status, reason, and records, got legacy array (unit: bp)",
                )
            )
        else:
            results.append(
                CheckResult(
                    "V16",
                    False,
                    "spread envelope section is missing, expected typed "
                    "status, reason, and records (unit: bp)",
                )
            )
    elif envelope.get("status") == "ok":
        reason = envelope.get("reason")
        records = envelope.get("records")
        if reason is not None:
            results.append(
                CheckResult("V16", False, "spread ok envelope reason must be null (unit: bp)")
            )
        elif not isinstance(records, list) or not records:
            results.append(
                CheckResult(
                    "V16",
                    False,
                    "spread ok envelope needs at least one recomputing record (unit: bp)",
                )
            )
        else:
            try:
                if len(records) > MAX_SPREAD_RECORDS:
                    raise ValueError("spread record count exceeds the cap before recompute")
                worst = 0.0
                seen_tenors: list[str] = []
                for record in records:
                    if not isinstance(record, dict):
                        raise ValueError("spread records must be mappings, no filtering")
                    tenor = record.get("tenor")
                    if tenor not in SPREAD_TENORS:
                        raise ValueError(
                            "spread records must carry a tenor "
                            f"in {list(SPREAD_TENORS)}, no positional reads"
                        )
                    assert isinstance(tenor, str)
                    seen_tenors.append(tenor)
                    if "ca_date" not in record or "us_date" not in record:
                        raise ValueError("spread legs must carry explicit ca_date and us_date")
                    ca_yield = _require_float(record.get("ca_yield_percent", ""), "ca_yield")
                    us_yield = _require_float(record.get("us_yield_percent", ""), "us_yield")
                    stored = _require_float(record.get("spread_bp", ""), "spread_bp")
                    expected = canada_us_spread_bp(ca_yield, us_yield)
                    worst = max(worst, abs(expected - stored))
                    record_date = _parse_date(record.get("date"))
                    if record_date is None:
                        raise ValueError("spread record date is unparseable")
                    ca_date = _parse_date(record.get("ca_date"))
                    us_date = _parse_date(record.get("us_date"))
                    if ca_date != record_date or us_date != record_date:
                        raise ValueError("spread legs must share the record date")
                expected_tenors = set(SPREAD_TENORS)
                if len(seen_tenors) != 4 or set(seen_tenors) != expected_tenors:
                    raise ValueError(
                        "spread ok envelope needs the complete tenor set "
                        f"{sorted(expected_tenors)} with no duplicates, "
                        f"got {seen_tenors} (unit: bp)"
                    )
                results.append(
                    CheckResult(
                        "V16",
                        worst <= tolerance_bp,
                        f"spreads recompute worst {worst:.4f} bp "
                        f"within {tolerance_bp} bp on same dates (unit: bp)",
                    )
                )
            except (ValueError, TypeError, ArithmeticError) as exc:
                results.append(CheckResult("V16", False, f"spread recompute failed: {exc}"))
    elif envelope.get("status") == "missing":
        reason = envelope.get("reason")
        records = envelope.get("records")
        if not isinstance(records, list) or len(records) != 0:
            results.append(
                CheckResult("V16", False, "spread missing records must be empty (unit: bp)")
            )
        elif not isinstance(reason, str) or not reason.strip():
            results.append(
                CheckResult(
                    "V16", False, "spread missing envelope reason must be non empty (unit: bp)"
                )
            )
        elif _is_degraded_missing(envelope, fred_api_key) and (
            envelope.get("reason") == FRED_DEGRADED_REASON
        ):
            results.append(
                CheckResult(
                    "V16",
                    True,
                    "spreads missing, FRED degraded without key (unit: bp)",
                )
            )
        else:
            results.append(
                CheckResult("V16", False, "spreads missing without FRED degraded marker (unit: bp)")
            )
    else:
        results.append(
            CheckResult("V16", False, "spread envelope status must be ok or missing (unit: bp)")
        )

    carry = _carry_section(snapshot)
    risk = _risk_section(snapshot)
    if not isinstance(carry, dict) or not isinstance(risk, dict):
        results.append(CheckResult("V17", False, "carry or risk section is missing"))
    else:
        try:
            long_yield = _require_float(
                carry.get("yield_at_maturity_percent", ""), "yield_at_maturity"
            )
            rolled = _require_float(
                carry.get("yield_at_rolled_tenor_percent", ""), "yield_at_rolled"
            )
            horizon = _require_float(carry.get("horizon_years", ""), "horizon_years")
            stored_carry = _require_float(carry.get("carry_roll_bp", ""), "carry_roll_bp")
            expected_carry = carry_roll_bp(long_yield, rolled, horizon)
            carry_diff = abs(expected_carry - stored_carry)
            risk_yield = _require_float(risk.get("yield_percent", ""), "yield_percent")
            risk_tenor = _require_float(risk.get("tenor_years", ""), "tenor_years")
            stored_price = _require_float(risk.get("price", ""), "price")
            stored_duration = _require_float(
                risk.get("modified_duration_years", ""), "modified_duration"
            )
            stored_dv01 = _require_float(risk.get("dv01_per_million", ""), "dv01")
            expected_price = par_bond_price(risk_yield, risk_tenor)
            expected_duration = modified_duration(risk_yield, risk_tenor)
            expected_dv01 = dv01_per_million(expected_price, expected_duration)
            # Tolerances below are not in basis points: price in price units
            # per 100 face (0.01), duration in years (0.0001), and DV01 in
            # currency units per million (1.0). Only the carry leg uses the
            # shared tolerance_bp of 1.0 bp.
            price_ok = abs(expected_price - stored_price) <= 0.01
            duration_ok = abs(expected_duration - stored_duration) <= 0.0001
            dv01_ok = abs(expected_dv01 - stored_dv01) <= 1.0
            carry_ok = carry_diff <= tolerance_bp
            passed = price_ok and duration_ok and dv01_ok and carry_ok
            results.append(
                CheckResult(
                    "V17",
                    passed,
                    f"carry diff {carry_diff:.4f} bp within {tolerance_bp} bp; "
                    f"price tol 0.01 per 100, duration tol 0.0001 years, "
                    f"DV01 tol 1.0 per million "
                    f"(price {expected_price:.4f}, duration {expected_duration:.4f} "
                    f"years, DV01 {expected_dv01:.2f} per million; unit: mixed)",
                )
            )
        except (ValueError, TypeError, ArithmeticError) as exc:
            results.append(CheckResult("V17", False, f"carry risk recompute failed: {exc}"))

    backtest = _backtest_section(snapshot)
    if not isinstance(backtest, dict):
        results.append(CheckResult("V18", False, "backtest section is missing"))
    elif _is_degraded_missing(backtest, fred_api_key):
        results.append(
            CheckResult(
                "V18",
                True,
                "backtest missing, FRED degraded without key (unit: bp)",
            )
        )
    else:
        try:
            rule_raw = backtest.get("rule", "")
            if not isinstance(rule_raw, str):
                raise ValueError("backtest rule must be a string without coercion")
            rule = rule_raw
            dates = backtest.get("dates")
            slopes = backtest.get("slopes_bp")
            stored_raw = backtest.get("total_pnl_bp", "")
            stored_total = _require_float(stored_raw, "total_pnl_bp")
            if rule != BACKTEST_RULE:
                raise ValueError(f"backtest rule must be {BACKTEST_RULE}")
            if not isinstance(dates, list) or not isinstance(slopes, list):
                raise ValueError("backtest dates and slopes_bp must be lists")
            if len(dates) > MAX_BACKTEST_OBS or len(slopes) > MAX_BACKTEST_OBS:
                raise ValueError("backtest count exceeds the cap before recompute")
            if len(dates) < 254 or len(slopes) < 254:
                raise ValueError("backtest needs at least 254 joined observations")
            if len(dates) != len(slopes):
                raise ValueError("backtest dates and slopes_bp must have equal length")
            for item in dates:
                if not isinstance(item, str):
                    raise ValueError("backtest dates must be strings without coercion")
                parse_strict_iso_date(item)
            clean_slopes: list[float] = []
            for item in slopes:
                clean_slopes.append(_require_float(item, "slopes_bp"))
            recomputed_backtest = run_backtest(list(dates), clean_slopes)
            recomputed_raw = recomputed_backtest["total_pnl_bp"]
            if isinstance(recomputed_raw, bool) or not isinstance(recomputed_raw, (int, float)):
                raise ValueError("recomputed total_pnl_bp must be numeric")
            recomputed_value = float(recomputed_raw)
            if recomputed_value != recomputed_value or recomputed_value in (
                float("inf"),
                float("-inf"),
            ):
                raise ValueError("recomputed total_pnl_bp must be finite")
            expected_total = recomputed_value
            diff = abs(expected_total - stored_total)
            results.append(
                CheckResult(
                    "V18",
                    diff <= tolerance_bp,
                    f"backtest {rule} with {len(dates)} obs, "
                    f"next day recompute diff {diff:.4f} bp (unit: bp)",
                )
            )
        except (ValueError, TypeError, ArithmeticError) as exc:
            results.append(CheckResult("V18", False, f"backtest check failed: {exc}"))
    return results


def _run_phase4_checks(snapshot: dict[str, Any]) -> list[CheckResult]:
    """Run checks V19 to V22 for the Phase 4 experimental CPI engine.

    A missing inflation section is a per module degraded skip, not a
    failure, so curve deploys are not blocked when the CPI bulk
    agreement fails. A present section still recomputes strictly.
    """
    from goc_rates.cpi.components import EXPECTED_COMPONENT_COUNT
    from goc_rates.cpi.trim_median import TRIM_METHOD, ComponentRate, compute_trim_median
    from goc_rates.cpi.validation import (
        MAE_GATE_PP,
        MIN_VALIDATION_MONTHS,
        validation_flag,
    )
    from goc_rates.limits import MAX_CPI_COMPONENTS, MAX_CPI_MONTHS

    results: list[CheckResult] = []

    observations_raw = snapshot.get("observations")
    if not isinstance(observations_raw, dict):
        results.append(CheckResult("V19", False, "inflation section is missing"))
        results.append(CheckResult("V20", False, "inflation section is missing"))
        results.append(CheckResult("V21", False, "inflation section is missing"))
        results.append(CheckResult("V22", False, "inflation section is missing"))
        return results

    inflation = observations_raw.get("inflation")
    if inflation is None:
        for check_id in ("V19", "V20", "V21", "V22"):
            results.append(
                CheckResult(
                    check_id,
                    True,
                    f"{check_id} skipped, inflation missing with CPI degraded (unit: mixed)",
                )
            )
        return results
    if isinstance(inflation, dict) and inflation.get("status") == "missing":
        reason = inflation.get("reason")
        if isinstance(reason, str) and reason.strip():
            for check_id in ("V19", "V20", "V21", "V22"):
                results.append(
                    CheckResult(
                        check_id,
                        True,
                        f"{check_id} skipped, inflation missing with CPI degraded (unit: mixed)",
                    )
                )
            return results

    try:
        if inflation.get("method") != TRIM_METHOD:
            raise ValueError(f"inflation method must be {TRIM_METHOD}")
        if inflation.get("owns_seasonal_adjustment") is not False:
            raise ValueError("inflation owns_seasonal_adjustment must be false")
        if inflation.get("seasonally_adjusted_source") != "statcan":
            raise ValueError("inflation SA source must be statcan")
        vintage = inflation.get("weight_vintage")
        if not isinstance(vintage, dict):
            raise ValueError("weight_vintage section is missing")
        if vintage.get("expenditure_year") != 2024:
            raise ValueError("weight vintage expenditure year must pin 2024")
        if vintage.get("link_month") != "2025-05":
            raise ValueError("weight vintage link month must pin 2025-05")
        if not isinstance(vintage.get("provisional"), bool):
            raise ValueError("weight vintage provisional must be a bool")
        reference = inflation.get("reference_month", "")
        if not isinstance(reference, str):
            raise ValueError("reference_month must be a string without coercion")
        import re as _re

        if _re.match(r"^(\d{4})-(0[1-9]|1[0-2])$", reference.strip()) is None:
            raise ValueError("reference_month must be YYYY-MM")
        component_count = inflation.get("component_count")
        if isinstance(component_count, bool) or not isinstance(component_count, int):
            raise ValueError("component_count must be an int without coercion")
        if component_count != EXPECTED_COMPONENT_COUNT:
            raise ValueError(
                f"component_count {component_count} must pin {EXPECTED_COMPONENT_COUNT}"
            )
        if component_count > MAX_CPI_COMPONENTS:
            raise ValueError("component count exceeds the cap before recompute")
        contributions = inflation.get("contributions")
        if not isinstance(contributions, list) or len(contributions) != component_count:
            raise ValueError("contributions must list one row per component")
        weight_total = 0.0
        for row in contributions:
            if not isinstance(row, dict):
                raise ValueError("contribution rows must be mappings, no filtering")
            weight_total += _require_float(row.get("weight_percent", ""), "weight_percent")
        if abs(weight_total - 100.0) > 1e-6:
            raise ValueError(
                f"registry weights sum to {weight_total:.6f}, expected 100.0 within 1e-6"
            )
        bulk = inflation.get("bulk")
        if not isinstance(bulk, dict) or not bulk:
            raise ValueError("bulk hash section is missing")
        expected_products: dict[str, int] = {
            "cpi_monthly": 18100004,
            "core_statistics": 18100256,
            "basket_weights": 18100007,
        }
        if set(bulk.keys()) != set(expected_products.keys()):
            raise ValueError(f"bulk keys must pin {sorted(expected_products)}, got {sorted(bulk)}")
        for name, entry in bulk.items():
            if not isinstance(entry, dict):
                raise ValueError(f"bulk entry {name!r} must be a mapping")
            product_id = entry.get("product_id")
            if isinstance(product_id, bool) or not isinstance(product_id, int):
                raise ValueError(f"bulk entry {name!r} product_id must be an int")
            import re as _re_bulk

            if not _re_bulk.match(r"^[1-9][0-9]{7}$", str(product_id)):
                raise ValueError(f"bulk entry {name!r} product_id must be an 8 digit id")
            if product_id != expected_products[name]:
                raise ValueError(
                    f"bulk entry {name!r} product id {product_id} "
                    f"must pin {expected_products[name]}"
                )
            digest = entry.get("zip_sha256", "")
            if not isinstance(digest, str) or len(digest.strip()) != 64:
                raise ValueError(f"bulk entry {name!r} sha256 must be 64 hex chars")
            try:
                int(digest.strip(), 16)
            except ValueError:
                raise ValueError(f"bulk entry {name!r} sha256 must be hex") from None
            short = entry.get("zip_sha12", "")
            if not isinstance(short, str) or short.strip() != digest.strip()[:12]:
                raise ValueError(f"bulk entry {name!r} sha12 must prefix its sha256")
        history = inflation.get("history")
        if not isinstance(history, list) or not history:
            raise ValueError("inflation history is missing")
        if len(history) > MAX_CPI_MONTHS:
            raise ValueError("history exceeds the month cap before recompute")
        results.append(
            CheckResult(
                "V19",
                True,
                f"inflation inputs pinned: {component_count} components, "
                f"link month 2025-05, weights sum {weight_total:.6f}, "
                f"{len(bulk)} bulk hashes (unit: mixed)",
            )
        )
    except (ValueError, TypeError, ArithmeticError) as exc:
        results.append(CheckResult("V19", False, f"inflation inputs failed: {exc}"))

    try:
        contributions = inflation.get("contributions", [])
        if not isinstance(contributions, list) or not contributions:
            raise ValueError("contributions are missing")
        if len(contributions) > MAX_CPI_COMPONENTS:
            raise ValueError("contribution count exceeds the cap before recompute")
        rates: dict[str, float] = {}
        fractions: dict[str, float] = {}
        for row in contributions:
            if not isinstance(row, dict):
                raise ValueError("contribution rows must be mappings, no filtering")
            component_id = row.get("component_id", "")
            if not isinstance(component_id, str) or not component_id:
                raise ValueError("contribution component_id must be a non empty string")
            if component_id in rates:
                raise ValueError(f"duplicate contribution component_id: {component_id!r}")
            rates[component_id] = _require_float(
                row.get("monthly_rate_percent", ""), "monthly_rate_percent"
            )
            fractions[component_id] = (
                _require_float(row.get("weight_percent", ""), "weight_percent") / 100.0
            )
        recomputed = compute_trim_median(
            [
                ComponentRate(
                    component_id=component_id,
                    monthly_rate_percent=rates[component_id],
                    weight_fraction=fractions[component_id],
                )
                for component_id in rates
            ]
        )
        latest = inflation.get("latest")
        if not isinstance(latest, dict):
            raise ValueError("latest trim median block is missing")
        stored_trim_mom = _quantity_value(latest.get("trim_mom"), "trim_mom")
        stored_median_mom = _quantity_value(latest.get("median_mom"), "median_mom")
        stored_trim_yoy = _quantity_value(latest.get("trim_yoy"), "trim_yoy")
        stored_median_yoy = _quantity_value(latest.get("median_yoy"), "median_yoy")
        median_component = latest.get("median_component", "")
        if not isinstance(median_component, str) or not median_component:
            raise ValueError("median_component must be a non empty string")
        if median_component != recomputed.median_component_id:
            raise ValueError(
                f"median component {median_component!r} must match "
                f"recomputed {recomputed.median_component_id!r}"
            )
        history = inflation.get("history", [])
        if not isinstance(history, list) or len(history) < 12:
            raise ValueError("inflation history needs at least 12 months")
        if len(history) > MAX_CPI_MONTHS:
            raise ValueError("history exceeds the month cap before recompute")
        trailing_trim: list[float] = []
        trailing_median: list[float] = []
        for row in history[-12:]:
            if not isinstance(row, dict):
                raise ValueError("history rows must be mappings")
            trailing_trim.append(_require_float(row.get("trim_mom_percent", ""), "trim_mom"))
            trailing_median.append(_require_float(row.get("median_mom_percent", ""), "median_mom"))
        from goc_rates.cpi.changes import compound_annual_percent

        expected_trim_yoy = compound_annual_percent(trailing_trim)
        expected_median_yoy = compound_annual_percent(trailing_median)
        last_row = history[-1]
        if not isinstance(last_row, dict):
            raise ValueError("history rows must be mappings")
        stored_history_trim_yoy = _require_float(
            last_row.get("trim_yoy_percent", ""), "history trim_yoy"
        )
        stored_history_median_yoy = _require_float(
            last_row.get("median_yoy_percent", ""), "history median_yoy"
        )
        diffs = [
            abs(recomputed.trim_mom_percent - stored_trim_mom),
            abs(recomputed.median_mom_percent - stored_median_mom),
            abs(expected_trim_yoy - stored_trim_yoy),
            abs(expected_median_yoy - stored_median_yoy),
            abs(expected_trim_yoy - stored_history_trim_yoy),
            abs(expected_median_yoy - stored_history_median_yoy),
        ]
        worst = max(diffs)
        # Tolerance is 1 bp in percent units: 0.01.
        results.append(
            CheckResult(
                "V20",
                worst <= 0.01,
                f"trim median YoY recompute worst {worst:.4f} "
                f"within 0.01 (1 bp in percent units; unit: percent), "
                f"median {median_component!r} matches recompute",
            )
        )
    except (ValueError, TypeError, ArithmeticError) as exc:
        results.append(CheckResult("V20", False, f"trim median recompute failed: {exc}"))

    try:
        contributions = inflation.get("contributions", [])
        if not isinstance(contributions, list) or not contributions:
            raise ValueError("contributions are missing")
        if len(contributions) > MAX_CPI_COMPONENTS:
            raise ValueError("contribution count exceeds the cap before recompute")
        recomputed_total = 0.0
        worst_row_diff = 0.0
        component_ids: set[str] = set()
        for row in contributions:
            if not isinstance(row, dict):
                raise ValueError("contribution rows must be mappings, no filtering")
            component_id = row.get("component_id", "")
            if not isinstance(component_id, str) or not component_id:
                raise ValueError("contribution component_id must be a non empty string")
            if component_id in component_ids:
                raise ValueError(f"duplicate contribution component_id: {component_id!r}")
            component_ids.add(component_id)
            weight = _require_float(row.get("weight_percent", ""), "weight_percent")
            rate = _require_float(row.get("monthly_rate_percent", ""), "monthly_rate_percent")
            stored_part = _require_float(row.get("contribution_pp", ""), "contribution_pp")
            expected_part = weight * rate / 100.0
            if expected_part != expected_part or expected_part in (
                float("inf"),
                float("-inf"),
            ):
                raise ValueError("contribution recomputation overflowed")
            worst_row_diff = max(worst_row_diff, abs(expected_part - stored_part))
            recomputed_total += expected_part
        if recomputed_total != recomputed_total or recomputed_total in (
            float("inf"),
            float("-inf"),
        ):
            raise ValueError("recomputed contribution total overflowed")
        stored_total = _require_float(
            inflation.get("total_contribution_pp", ""), "total_contribution_pp"
        )
        reconcile = abs(recomputed_total - stored_total)
        headline = inflation.get("headline_mom")
        if not isinstance(headline, dict):
            raise ValueError("headline_mom quantity is missing")
        if str(headline.get("unit", "")).strip() != "percent_per_month":
            raise ValueError(
                f"headline_mom unit must be percent_per_month, got {headline.get('unit')!r}"
            )
        if str(headline.get("source_id", "")) != "derived:cpi_trim_median":
            raise ValueError("headline_mom source must be derived:cpi_trim_median")
        headline_value = _quantity_value(headline, "headline_mom")
        headline_diff = abs(headline_value - recomputed_total)
        excluded = _require_float(
            inflation.get("excluded_weight_fraction", ""), "excluded_weight_fraction"
        )
        kept = _require_float(inflation.get("kept_weight_fraction", ""), "kept_weight_fraction")
        excluded_drift = abs(excluded - 0.40)
        if abs(kept + excluded - 1.0) > 1e-9:
            raise ValueError("kept plus excluded weights must sum to one")
        latest = inflation.get("latest")
        if not isinstance(latest, dict):
            raise ValueError("latest trim median block is missing")
        median_component = latest.get("median_component", "")
        if not isinstance(median_component, str) or median_component not in component_ids:
            raise ValueError("median component must name one contribution row")
        passed = (
            worst_row_diff <= 0.01
            and reconcile <= 0.01
            and headline_diff <= 0.01
            and excluded_drift <= 1e-6
        )
        results.append(
            CheckResult(
                "V21",
                passed,
                f"contributions recompute worst row {worst_row_diff:.4f} pp, "
                f"recomputed total {recomputed_total:.4f} vs stored {stored_total:.4f} "
                f"diff {reconcile:.4f} pp within 0.01 pp; headline {headline_value:.4f} "
                f"diff {headline_diff:.4f} pp; excluded {excluded:.6f} vs 0.40 "
                f"drift {excluded_drift:.2e} within 1e-6 (unit: percentage_points)",
            )
        )
    except (ValueError, TypeError, ArithmeticError) as exc:
        results.append(CheckResult("V21", False, f"contribution reconcile failed: {exc}"))

    try:
        if inflation.get("label") != "experimental":
            raise ValueError("inflation label must be experimental")
        if inflation.get("is_official") is not False:
            raise ValueError("inflation is_official must be false")
        if inflation.get("publisher_series") != "statcan":
            raise ValueError("inflation publisher_series must be statcan")
        experimental = inflation.get("experimental_series", "")
        if not isinstance(experimental, str) or not experimental.startswith("derived:"):
            raise ValueError("experimental_series must use the derived prefix")
        bulk = inflation.get("bulk")
        if not isinstance(bulk, dict):
            raise ValueError("bulk hash section is missing")
        expected_products_v22: dict[str, int] = {
            "cpi_monthly": 18100004,
            "core_statistics": 18100256,
            "basket_weights": 18100007,
        }
        if set(bulk.keys()) != set(expected_products_v22.keys()):
            raise ValueError(f"bulk keys must pin the three products, got {sorted(bulk)}")
        for name, entry in bulk.items():
            if not isinstance(entry, dict):
                raise ValueError(f"bulk entry {name!r} must be a mapping")
            product_id = entry.get("product_id")
            if isinstance(product_id, bool) or not isinstance(product_id, int):
                raise ValueError(f"bulk entry {name!r} product_id must be an int")
            import re as _re_v22

            if not _re_v22.match(r"^[1-9][0-9]{7}$", str(product_id)):
                raise ValueError(f"bulk entry {name!r} product_id must be an 8 digit id")
            if product_id != expected_products_v22[name]:
                raise ValueError(
                    f"bulk entry {name!r} product id {product_id} "
                    f"must pin {expected_products_v22[name]}"
                )
        validation = inflation.get("validation")
        if not isinstance(validation, dict):
            raise ValueError("validation block is missing")
        months = validation.get("months")
        if isinstance(months, bool) or not isinstance(months, int):
            raise ValueError("validation months must be an int without coercion")
        if months < MIN_VALIDATION_MONTHS:
            raise ValueError(f"validation needs at least {MIN_VALIDATION_MONTHS} months")
        gate = _require_float(validation.get("gate_pp", ""), "gate_pp")
        if abs(gate - MAE_GATE_PP) > 1e-12:
            raise ValueError(f"validation gate must pin {MAE_GATE_PP}")
        residuals_trim = _require_float_list(
            validation.get("residuals_trim_pp", ""), "residuals_trim_pp"
        )
        residuals_median = _require_float_list(
            validation.get("residuals_median_pp", ""), "residuals_median_pp"
        )
        if len(residuals_trim) != months or len(residuals_median) != months:
            raise ValueError("residual lists must match validation months")
        trim_block = validation.get("trim")
        median_block = validation.get("median")
        if not isinstance(trim_block, dict) or not isinstance(median_block, dict):
            raise ValueError("validation trim and median blocks are missing")
        for name, block, residuals in (
            ("trim", trim_block, residuals_trim),
            ("median", median_block, residuals_median),
        ):
            mae = sum(abs(item) for item in residuals) / float(len(residuals))
            bias = sum(residuals) / float(len(residuals))
            max_abs = max(abs(item) for item in residuals)
            if abs(mae - _require_float(block.get("mae_pp", ""), f"{name} mae")) > 1e-9:
                raise ValueError(f"validation {name} MAE does not recompute")
            if abs(bias - _require_float(block.get("bias_pp", ""), f"{name} bias")) > 1e-9:
                raise ValueError(f"validation {name} bias does not recompute")
            if (
                abs(max_abs - _require_float(block.get("max_abs_resid_pp", ""), f"{name} max"))
                > 1e-9
            ):
                raise ValueError(f"validation {name} max residual does not recompute")
        mae_trim = sum(abs(item) for item in residuals_trim) / float(len(residuals_trim))
        mae_median = sum(abs(item) for item in residuals_median) / float(len(residuals_median))
        expected_exceeds = bool(mae_trim > gate or mae_median > gate)
        stored_exceeds = validation.get("exceeds_gate")
        if not isinstance(stored_exceeds, bool):
            raise ValueError("exceeds_gate must be a bool without coercion")
        if stored_exceeds != expected_exceeds:
            raise ValueError("exceeds_gate must match the recomputed gate outcome")
        if validation.get("flag") != validation_flag(expected_exceeds):
            raise ValueError("validation flag must match the gate outcome")
        # A breached gate flags for explanation and never blocks: V22 passes
        # whenever the flag is honest, even when exceeds_gate is true.
        results.append(
            CheckResult(
                "V22",
                True,
                f"inflation experimental, is_official false, statcan bulk pinned, "
                f"MAE trim {mae_trim:.4f} median {mae_median:.4f} vs gate {gate} "
                f"(unit: percentage_points), flag {validation.get('flag')}",
            )
        )
    except (ValueError, TypeError, ArithmeticError) as exc:
        results.append(CheckResult("V22", False, f"inflation label check failed: {exc}"))
    return results


def _breaks_section(snapshot: dict[str, Any]) -> Any:
    """Return the breaks section dict or None."""
    return _get_path(snapshot, "observations", "breaks")


def _run_phase5_checks(
    snapshot: dict[str, Any],
    tolerance_bp: float = TOLERANCE_BP,
) -> list[CheckResult]:
    """Run check V23 for the Phase 5 benchmark switch day over day gate.

    A present curve requires a present breaks section. The check pins the
    feed digest grammar, tenor closure, recomputed joint effective dates,
    calendar day over day deltas, recomputed gates, and nullness rules.
    """
    from goc_rates.breaks import (
        BREAKS_GATES,
        BREAKS_METHOD,
        BREAKS_SOURCE_ID,
        BREAKS_TENORS,
        BREAKS_THRESHOLD_BP,
        FEED_ALLOWED_TENORS,
        FEED_SOURCE,
        effective_joint_date,
        normalize_tenor,
    )
    from goc_rates.calendar import is_business_day, previous_business_day
    from goc_rates.limits import (
        MAX_DOD_RECORDS,
        MAX_HISTORY_OBS,
        MAX_SWITCH_EVENTS,
    )

    results: list[CheckResult] = []
    try:
        observations_raw = snapshot.get("observations")
        if not isinstance(observations_raw, dict):
            raise ValueError("observations section is missing")
        curve_section = observations_raw.get("curve")
        breaks = observations_raw.get("breaks")
        if not isinstance(curve_section, dict):
            raise ValueError("curve section is missing, breaks cannot be assessed")
        if not isinstance(breaks, dict):
            raise ValueError("breaks section is missing beside a present curve")
        if breaks.get("method") != BREAKS_METHOD:
            raise ValueError(f"breaks method must be {BREAKS_METHOD}")
        metadata = snapshot.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("metadata section is missing")
        snapshot_date_text = metadata.get("snapshot_date")
        snapshot_day = _parse_date(snapshot_date_text)
        if snapshot_day is None:
            raise ValueError("metadata.snapshot_date is unparseable")
        breaks_snapshot = _parse_date(breaks.get("snapshot_date"))
        if breaks_snapshot is None:
            raise ValueError("breaks snapshot_date is unparseable")
        if breaks_snapshot != snapshot_day:
            raise ValueError("breaks snapshot_date must match metadata.snapshot_date")
        print_day = _parse_date(breaks.get("print_date"))
        if print_day is None:
            raise ValueError("breaks print_date is unparseable")
        feed_source = breaks.get("feed_source")
        if not isinstance(feed_source, str) or feed_source.strip() != FEED_SOURCE:
            raise ValueError(f"breaks feed_source must pin {FEED_SOURCE}")
        feed_vintage = _parse_date(breaks.get("feed_vintage"))
        if feed_vintage is None:
            raise ValueError("breaks feed_vintage is unparseable")
        feed_digest = breaks.get("feed_sha256")
        if not isinstance(feed_digest, str) or len(feed_digest.strip()) != 64:
            raise ValueError("breaks feed_sha256 must be 64 hex chars")
        try:
            int(feed_digest.strip(), 16)
        except ValueError:
            raise ValueError("breaks feed_sha256 must be hex") from None
        provenance = snapshot.get("provenance")
        if not isinstance(provenance, dict):
            raise ValueError("provenance section is missing")
        switch_prov = provenance.get("benchmark_switches")
        if not isinstance(switch_prov, dict):
            raise ValueError("provenance benchmark_switches is missing")
        for prov_key in ("source_url", "retrieved_utc", "vintage"):
            value = switch_prov.get(prov_key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"provenance benchmark_switches {prov_key} is missing")
        prov_vintage = _parse_date(switch_prov.get("vintage"))
        if prov_vintage is None or prov_vintage != feed_vintage:
            raise ValueError("provenance benchmark_switches vintage must match breaks feed")
        prov_digest = switch_prov.get("sha256")
        if not isinstance(prov_digest, str) or prov_digest.strip() != feed_digest.strip():
            raise ValueError("provenance benchmark_switches sha256 must match breaks feed")
        threshold = _require_float(breaks.get("threshold_bp", ""), "threshold_bp")
        if abs(threshold - BREAKS_THRESHOLD_BP) > 1e-12:
            raise ValueError(f"breaks threshold must pin {BREAKS_THRESHOLD_BP}")
        if str(breaks.get("threshold_unit", "")).strip() != "basis_points":
            raise ValueError("breaks threshold_unit must be basis_points")
        events_raw = breaks.get("events")
        if not isinstance(events_raw, list) or not events_raw:
            raise ValueError("breaks events are missing")
        if len(events_raw) > MAX_SWITCH_EVENTS:
            raise ValueError("breaks event count exceeds the cap before recompute")
        seen_events: set[tuple[str, str]] = set()
        joint_by_tenor: dict[str, list[dt.date]] = {tenor: [] for tenor in BREAKS_TENORS}
        for row in events_raw:
            if not isinstance(row, dict):
                raise ValueError("breaks event rows must be mappings, no filtering")
            tenor_raw = row.get("tenor")
            if not isinstance(tenor_raw, str) or tenor_raw.strip() not in FEED_ALLOWED_TENORS:
                raise ValueError("breaks event tenor is outside the closed feed set")
            tenor = tenor_raw.strip()
            effective = _parse_date(row.get("effective_date"))
            joint = _parse_date(row.get("effective_joint_date"))
            if effective is None or joint is None:
                raise ValueError("breaks event dates are unparseable")
            expected_joint = effective_joint_date(effective)
            if joint != expected_joint:
                raise ValueError("breaks effective_joint_date does not recompute")
            event_key = (tenor, effective.isoformat())
            if event_key in seen_events:
                raise ValueError(f"duplicate breaks event: {event_key}")
            seen_events.add(event_key)
            for name in ("incoming_maturity", "outgoing_maturity"):
                maturity = row.get(name)
                if maturity is not None and _parse_date(maturity) is None:
                    raise ValueError(f"breaks event {name} must be ISO or null")
            for name in ("incoming_coupon_percent", "outgoing_coupon_percent"):
                coupon = row.get(name)
                if coupon is not None:
                    _require_float(coupon, name)
            joint_by_tenor.setdefault(normalize_tenor(tenor), []).append(joint)
        records_raw = breaks.get("records")
        if not isinstance(records_raw, list) or not records_raw:
            raise ValueError("breaks records are missing")
        if len(records_raw) != len(BREAKS_TENORS):
            raise ValueError(f"breaks records must hold {len(BREAKS_TENORS)} tenors")
        if len(records_raw) > MAX_DOD_RECORDS:
            raise ValueError("breaks record count exceeds the cap before recompute")
        labels = [
            str(item.get("tenor", "")) if isinstance(item, dict) else "" for item in records_raw
        ]
        if labels != list(BREAKS_TENORS):
            raise ValueError(f"breaks tenor set must be {list(BREAKS_TENORS)}, got {labels}")
        worst = 0.0
        for record in records_raw:
            if not isinstance(record, dict):
                raise ValueError("breaks records must be mappings, no filtering")
            tenor = str(record.get("tenor", "")).strip()
            if tenor not in BREAKS_TENORS:
                raise ValueError("breaks record tenor is outside the closure")
            prev_day = _parse_date(record.get("prev_date"))
            current_day = _parse_date(record.get("current_date"))
            if prev_day is None or current_day is None:
                raise ValueError("breaks record dates are unparseable")
            if current_day != print_day:
                raise ValueError("breaks record current_date must match print_date")
            if not current_day > prev_day:
                raise ValueError("breaks record current_date must exceed prev_date")
            prev_yield = record.get("prev_yield_percent")
            current_yield = record.get("current_yield_percent")
            for name, value in (
                ("prev_yield", prev_yield),
                ("current_yield", current_yield),
            ):
                if value is not None:
                    _require_float(value, name)
            history_count = record.get("history_count")
            if isinstance(history_count, bool) or not isinstance(history_count, int):
                raise ValueError("breaks history_count must be an int without coercion")
            if history_count < 0 or history_count > MAX_HISTORY_OBS:
                raise ValueError("breaks history_count is outside the bounded range")
            switch_flag = record.get("switch_in_window")
            gap_flag = record.get("calendar_gap")
            if not isinstance(switch_flag, bool) or not isinstance(gap_flag, bool):
                raise ValueError("breaks flags must be bools without coercion")
            gate = record.get("gate")
            if not isinstance(gate, str) or gate not in BREAKS_GATES:
                raise ValueError("breaks gate is outside the closed set")
            expected_prev = previous_business_day(current_day, "joint")
            expected_gap = (prev_day != expected_prev) or (
                not is_business_day(current_day, "joint")
            )
            if gap_flag != expected_gap:
                raise ValueError("breaks calendar_gap does not recompute")
            expected_switch = any(
                prev_day < joint <= current_day
                for joint in joint_by_tenor.get(normalize_tenor(tenor), [])
            )
            if switch_flag != expected_switch:
                raise ValueError("breaks switch_in_window does not recompute")
            prev_number = (
                None if prev_yield is None else _require_float(prev_yield, "prev_yield_percent")
            )
            current_number = (
                None
                if current_yield is None
                else _require_float(current_yield, "current_yield_percent")
            )
            if history_count < 2:
                expected_gate = "insufficient_history"
            elif prev_number is None or current_number is None:
                expected_gate = "missing_prev"
            elif expected_switch:
                expected_gate = "switch_break"
            elif expected_gap:
                expected_gate = "calendar_gap"
            else:
                expected_gate = "comparable"
            if gate != expected_gate:
                raise ValueError("breaks gate does not recompute from classify_gate")
            stored_dod = record.get("dod_bp")
            if gate in ("switch_break", "missing_prev", "insufficient_history"):
                if stored_dod is not None:
                    raise ValueError(f"breaks gate {gate} must suppress dod_bp to null")
            else:
                if stored_dod is None:
                    raise ValueError(f"breaks gate {gate} must keep a numeric dod_bp")
                assert prev_number is not None and current_number is not None
                expected_dod = (current_number - prev_number) * 100.0
                stored_number = _require_float(stored_dod, "dod_bp")
                worst = max(worst, abs(expected_dod - stored_number))
            if str(record.get("dod_unit", "")).strip() != "basis_points":
                raise ValueError("breaks dod_unit must be basis_points")
            quantity = record.get("dod_quantity")
            if not isinstance(quantity, dict):
                raise ValueError("breaks dod_quantity must be a mapping")
            if str(quantity.get("unit", "")).strip() != "basis_points":
                raise ValueError("breaks dod_quantity unit must be basis_points")
            if str(quantity.get("source_id", "")) != BREAKS_SOURCE_ID:
                raise ValueError(f"breaks dod_quantity source must be {BREAKS_SOURCE_ID}")
            quality = quantity.get("quality")
            if quality not in ("observed", "missing"):
                raise ValueError("breaks dod_quantity quality must be observed or missing")
            quantity_value = quantity.get("value")
            if stored_dod is None:
                if quantity_value is not None or quality != "missing":
                    raise ValueError("null dod_bp needs a missing null quantity")
            else:
                if quality != "observed":
                    raise ValueError("numeric dod_bp needs an observed quantity")
                if abs(_require_float(quantity_value, "dod_quantity") - stored_number) > 1e-9:
                    raise ValueError("breaks dod_quantity must match dod_bp")
            if str(record.get("source_id", "")) != BREAKS_SOURCE_ID:
                raise ValueError(f"breaks record source must be {BREAKS_SOURCE_ID}")
        if worst > tolerance_bp:
            raise ValueError(f"breaks dod recompute worst {worst:.4f} exceeds {tolerance_bp} bp")
        results.append(
            CheckResult(
                "V23",
                True,
                f"breaks {BREAKS_METHOD} with {len(records_raw)} tenors, "
                f"dod worst {worst:.4f} bp within {tolerance_bp} bp, "
                f"threshold {BREAKS_THRESHOLD_BP} bp, feed {feed_vintage.isoformat()} "
                f"sha {feed_digest.strip()[:12]} (unit: mixed)",
            )
        )
    except (ValueError, TypeError, ArithmeticError) as exc:
        results.append(CheckResult("V23", False, f"breaks integrity failed: {exc}"))
    return results


def _quantity_value(node: Any, name: str) -> float:
    """Extract a finite numeric value from a Quantity mapping."""
    if not isinstance(node, dict):
        raise ValueError(f"{name} must be a Quantity mapping")
    return _require_float(node.get("value", ""), name)


def _require_float_list(value: Any, name: str) -> list[float]:
    """Require a list of finite numbers without string coercion."""
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must be a non empty list")
    cleaned: list[float] = []
    for item in value:
        cleaned.append(_require_float(item, name))
    return cleaned


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
    metadata = snapshot.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("metadata section is missing")
    date_text = metadata.get("snapshot_date")
    if not isinstance(date_text, str):
        raise ValueError("metadata.snapshot_date must be a string")
    normalized_date = parse_strict_iso_date(date_text).isoformat()
    if snapshot_file.parent.name != normalized_date:
        raise ValueError(
            f"snapshot directory {snapshot_file.parent.name!r} "
            f"must match snapshot_date {normalized_date!r}"
        )
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
