"""Command line interface: snapshot and verify subcommands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from goc_rates.calendar import snapshot_date_for_run
from goc_rates.config import load_benchmark_map
from goc_rates.dates import parse_strict_iso_date
from goc_rates.snapshot import build_snapshot, write_snapshot
from goc_rates.verify import verify_file


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(prog="goc-rates", description="GoC rates pipeline.")
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot", help="Write a snapshot skeleton.")
    snap.add_argument("--date", default=None, help="Snapshot date YYYY-MM-DD.")
    snap.add_argument(
        "--out",
        default=None,
        help="Operator trusted output directory for the snapshot tree.",
    )
    snap.add_argument("--config", default="config/benchmark_map.yaml", help="Benchmark map path.")
    ver = sub.add_parser("verify", help="Verify a snapshot file.")
    ver.add_argument("--snapshot", required=True, help="Path to snapshot.json.")
    ver.add_argument(
        "--out",
        default=None,
        help="Operator trusted path for the verify.json report.",
    )
    ver.add_argument("--config", default=None, help="Benchmark map path for label checks.")
    return parser


def parse_snapshot_date(date_text: str | None) -> str:
    """Parse a --date value as strict ISO YYYY-MM-DD and re-serialize it.

    A missing value maps to the current Toronto business date. Any other
    value must already be ISO, so path separators can never reach Path use.
    """
    if date_text is None:
        return snapshot_date_for_run().isoformat()
    try:
        return parse_strict_iso_date(date_text).isoformat()
    except ValueError:
        raise ValueError(f"--date must be ISO YYYY-MM-DD: {date_text!r}") from None


def _observed_benchmark_yields(
    benchmarks: dict[str, object],
) -> dict[str, object]:
    """Extract observed percent benchmark yields as Quantity mappings.

    Only entries whose valet quantity is observed with a percent unit and
    a finite value are returned. Anything else is skipped so the curve
    builder fails closed on missing data instead of using placeholders.
    """
    yields: dict[str, object] = {}
    for tenor in ("2Y", "5Y", "10Y", "30Y"):
        entry = benchmarks.get(tenor)
        if not isinstance(entry, dict):
            continue
        valet = entry.get("valet")
        if not isinstance(valet, dict):
            continue
        if valet.get("quality") != "observed":
            continue
        if valet.get("unit") not in ("percent", "percent_yield"):
            continue
        value = valet.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            continue
        yields[tenor] = valet
    return yields


def run_snapshot(
    date_text: str | None,
    out_dir: str | None,
    config_path: str | None = "config/benchmark_map.yaml",
) -> int:
    """Write a skeleton snapshot that fails closed until real fetches land."""
    try:
        benchmark_map = load_benchmark_map(
            Path(config_path) if config_path else Path("config/benchmark_map.yaml")
        )
    except (ValueError, OSError) as exc:
        print(f"snapshot failed: {exc}", file=sys.stderr)
        return 2
    try:
        snapshot_date = parse_snapshot_date(date_text)
    except ValueError as exc:
        print(f"snapshot failed: {exc}", file=sys.stderr)
        return 2
    from goc_rates.models import make_missing

    benchmarks: dict[str, object] = {}
    for tenor, entry in benchmark_map.benchmarks.items():
        benchmarks[tenor] = {
            "valet_label": entry.valet_label,
            "valet": make_missing("percent", f"valet:{entry.valet_series_id}"),
        }
    observations: dict[str, object] = {
        "benchmarks": benchmarks,
        "corra": {"value_date": "", "pub_date": "", "date_role": "value_date_lags_pub_date"},
        "fred_lag": {"observation_date": "", "expected_lag_note": "DGS prints land T+1"},
        "statcan": {"seasonally_adjusted_reused_as_is": True, "vectors": {}},
        "tbill_check": {"yield_percent": 0.0, "price": 0.0, "days_to_maturity": 90},
        "cross_source_diff_bp": {"value_bp": 0.0, "unit": "basis_points"},
        "staleness": {"max_age_business_days": 0, "unit": "business_days"},
    }
    try:
        from goc_rates.analytics import CARRY_HORIZON_YEARS, carry_roll_bp
        from goc_rates.curve import build_curve_section
        from goc_rates.risk import dv01_per_million, modified_duration, par_bond_price

        observed = _observed_benchmark_yields(benchmarks)
        if not observed:
            raise ValueError("no observed benchmark yields, live Valet fetch is pending")
        curve_section = build_curve_section(observed)  # type: ignore[arg-type]
        observations["curve"] = curve_section
        knots = curve_section["knots"]
        assert isinstance(knots, list)
        by_tenor = {
            str(row["tenor"]): float(str(row["yield_percent"]))
            for row in knots
            if isinstance(row, dict)
        }
        long_yield = by_tenor.get("10Y")
        five_yield = by_tenor.get("5Y")
        if long_yield is not None:
            observations["carry"] = {
                "yield_at_maturity_percent": long_yield,
                "yield_at_rolled_tenor_percent": long_yield,
                "horizon_years": CARRY_HORIZON_YEARS,
                "carry_roll_bp": carry_roll_bp(long_yield, long_yield, CARRY_HORIZON_YEARS),
            }
        if five_yield is not None:
            price = par_bond_price(five_yield, 5.0)
            duration = modified_duration(five_yield, 5.0)
            observations["risk"] = {
                "yield_percent": five_yield,
                "tenor_years": 5.0,
                "price": price,
                "modified_duration_years": duration,
                "dv01_per_million": dv01_per_million(price, duration),
            }
        print("spreads section pending: joint CA-US histories are pending", file=sys.stderr)
        print("backtest section pending: 254 joint slope prints are pending", file=sys.stderr)
    except (ValueError, TypeError, AssertionError, ArithmeticError) as exc:
        print(f"curve section pending: {exc}", file=sys.stderr)
    provenance = {
        "note": {
            "source_url": "pending Phase 1 fetch wiring",
            "retrieved_utc": "pending",
            "vintage": "pending",
        }
    }
    snapshot = build_snapshot(snapshot_date, observations, provenance)
    directory = Path(out_dir) if out_dir else Path("snapshots") / snapshot_date
    write_snapshot(directory, snapshot)
    print(f"wrote snapshot skeleton to {directory}", file=sys.stderr)
    print("snapshot skeleton fails closed: real fetches are pending", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "snapshot":
        return run_snapshot(args.date, args.out, args.config)
    if args.command == "verify":
        try:
            return verify_file(args.snapshot, args.out, benchmark_map_path=args.config)
        except ValueError as exc:
            print(f"verify failed: {exc}", file=sys.stderr)
            return 2
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
