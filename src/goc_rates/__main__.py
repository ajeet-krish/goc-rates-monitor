"""Command line interface: snapshot and verify subcommands."""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from goc_rates.calendar import snapshot_date_for_run
from goc_rates.config import load_benchmark_map
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
    """Parse a --date value as ISO YYYY-MM-DD and re-serialize it.

    A missing value maps to the current Toronto business date. Any other
    value must already be ISO, so path separators can never reach Path use.
    """
    if date_text is None:
        return snapshot_date_for_run().isoformat()
    try:
        return dt.date.fromisoformat(date_text.strip()).isoformat()
    except ValueError:
        raise ValueError(f"--date must be ISO YYYY-MM-DD: {date_text!r}") from None


def run_snapshot(
    date_text: str | None,
    out_dir: str | None,
    config_path: str | None = "config/benchmark_map.yaml",
) -> int:
    """Write a skeleton snapshot that fails closed until real fetches land."""
    try:
        load_benchmark_map(Path(config_path) if config_path else Path("config/benchmark_map.yaml"))
    except (ValueError, OSError) as exc:
        print(f"snapshot failed: {exc}", file=sys.stderr)
        return 2
    try:
        snapshot_date = parse_snapshot_date(date_text)
    except ValueError as exc:
        print(f"snapshot failed: {exc}", file=sys.stderr)
        return 2
    observations = {
        "benchmarks": {},
        "corra": {"value_date": "", "pub_date": "", "date_role": "value_date_lags_pub_date"},
        "fred_lag": {"observation_date": "", "expected_lag_note": "DGS prints land T+1"},
        "statcan": {"seasonally_adjusted_reused_as_is": True, "vectors": {}},
        "tbill_check": {"yield_percent": 0.0, "price": 0.0, "days_to_maturity": 90},
        "cross_source_diff_bp": {"value_bp": 0.0, "unit": "basis_points"},
        "staleness": {"max_age_business_days": 0, "unit": "business_days"},
    }
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
