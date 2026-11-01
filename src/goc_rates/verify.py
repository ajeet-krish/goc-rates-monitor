"""Verification checks V01 to V18 with a 1.0 basis point tolerance."""

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
    """Run checks V01 to V18 against a snapshot document."""
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
    for key in ("curve", "derived", "spreads", "canada_us_spreads", "carry", "risk", "backtest"):
        section = observations.get(key)
        if isinstance(section, (dict, list)):
            collected.extend(_quantities(section))
    return collected


def _spread_records(snapshot: dict[str, Any]) -> list[Any] | None:
    """Return raw spread records from any known section, else None.

    Records are returned unfiltered so the V16 check can fail closed on
    non-dict entries or an empty set instead of passing vacuously.
    """
    observations = snapshot.get("observations")
    if not isinstance(observations, dict):
        return None
    candidates: list[Any] = []
    for key in ("spreads", "canada_us_spreads"):
        section = observations.get(key)
        if isinstance(section, list):
            candidates = section
            break
        if isinstance(section, dict) and isinstance(section.get("records"), list):
            candidates = section["records"]
            break
    if not candidates:
        derived = observations.get("derived")
        if isinstance(derived, dict):
            for key in ("spreads", "canada_us_spreads"):
                section = derived.get(key)
                if isinstance(section, list):
                    candidates = section
                    break
                if isinstance(section, dict) and isinstance(section.get("records"), list):
                    candidates = section["records"]
                    break
    if not candidates:
        return None
    return candidates


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

    records = _spread_records(snapshot)
    if records is None:
        raw_spreads: Any = None
        observations_raw = snapshot.get("observations")
        if isinstance(observations_raw, dict):
            raw_spreads = observations_raw.get("spreads")
            if raw_spreads is None:
                derived_raw = observations_raw.get("derived")
                if isinstance(derived_raw, dict):
                    raw_spreads = derived_raw.get("spreads")
        if _is_degraded_missing(raw_spreads, fred_api_key):
            results.append(
                CheckResult(
                    "V16",
                    True,
                    "spreads missing, FRED degraded without key (unit: bp)",
                )
            )
        else:
            results.append(CheckResult("V16", False, "spread records section is missing"))
    else:
        try:
            if len(records) > MAX_SPREAD_RECORDS:
                raise ValueError("spread record count exceeds the cap before recompute")
            worst = 0.0
            for record in records:
                if not isinstance(record, dict):
                    raise ValueError("spread records must be mappings, no filtering")
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
