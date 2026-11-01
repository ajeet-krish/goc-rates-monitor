"""Replica validation: MAE gate with a flag that never blocks the build."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from goc_rates.limits import MAX_CPI_MONTHS

VALIDATION_WINDOW_MONTHS = 36
MIN_VALIDATION_MONTHS = 24
MAE_GATE_PP = 0.10

FLAG_WITHIN_GATE = "within_gate"
FLAG_EXCEEDS_GATE = "exceeds_gate_needs_explanation"


@dataclass(frozen=True)
class ValidationResult:
    """Validation outcome: months, MAE, bias, max residual, gate, flag state."""

    months: int
    mae_pp: float
    bias_pp: float
    max_abs_resid_pp: float
    gate_pp: float
    exceeds_gate: bool


def validation_flag(exceeds_gate: bool) -> str:
    """Return the validation flag text for a gate outcome."""
    if not isinstance(exceeds_gate, bool):
        raise ValueError("exceeds_gate must be a bool")
    return FLAG_EXCEEDS_GATE if exceeds_gate else FLAG_WITHIN_GATE


def _check_series(values: Sequence[float], name: str) -> list[float]:
    """Return finite values as floats, else raise."""
    cleaned = list(values)
    if not cleaned:
        raise ValueError(f"{name} must contain at least one value")
    result: list[float] = []
    for value in cleaned:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} values must be numeric")
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"{name} values must be finite")
        result.append(number)
    return result


def validate_replica(
    replica_yoy: Sequence[float],
    published_yoy: Sequence[float],
    gate_pp: float = MAE_GATE_PP,
) -> ValidationResult:
    """Compare replica YoY against published YoY over a trailing window.

    Uses the trailing VALIDATION_WINDOW_MONTHS months when more history
    exists, requires at least MIN_VALIDATION_MONTHS months, and flags
    gate breaches without raising: the flag never blocks the build.
    """
    replica = _check_series(replica_yoy, "replica_yoy")
    published = _check_series(published_yoy, "published_yoy")
    if len(replica) != len(published):
        raise ValueError("replica and published series must have equal length")
    if len(replica) > MAX_CPI_MONTHS:
        raise ValueError(f"validation length {len(replica)} exceeds the {MAX_CPI_MONTHS} month cap")
    if len(replica) < MIN_VALIDATION_MONTHS:
        raise ValueError(
            f"validation needs at least {MIN_VALIDATION_MONTHS} months, got {len(replica)}"
        )
    if isinstance(gate_pp, bool) or not isinstance(gate_pp, (int, float)):
        raise ValueError("gate_pp must be numeric")
    gate = float(gate_pp)
    if gate != gate or gate in (float("inf"), float("-inf")) or gate <= 0.0:
        raise ValueError("gate_pp must be finite and positive")
    window_replica = replica[-VALIDATION_WINDOW_MONTHS:]
    window_published = published[-VALIDATION_WINDOW_MONTHS:]
    residuals = [
        replica_value - published_value
        for replica_value, published_value in zip(window_replica, window_published, strict=True)
    ]
    months = len(residuals)
    mae = sum(abs(item) for item in residuals) / float(months)
    bias = sum(residuals) / float(months)
    max_abs = max(abs(item) for item in residuals)
    for metric in (mae, bias, max_abs):
        if metric != metric or metric in (float("inf"), float("-inf")):
            raise ValueError("validation metric overflowed")
    return ValidationResult(
        months=months,
        mae_pp=mae,
        bias_pp=bias,
        max_abs_resid_pp=max_abs,
        gate_pp=gate,
        exceeds_gate=bool(mae > gate),
    )
