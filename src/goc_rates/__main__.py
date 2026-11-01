"""Command line interface: snapshot and verify subcommands."""

from __future__ import annotations

import argparse
import sys

from goc_rates.live_snapshot import resolve_target_date
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

    A missing value maps to the previous joint business day strictly before
    today in America/Toronto. Any other value must already be ISO, so path
    separators can never reach Path use. This routes through the live
    snapshot resolver so the CLI and pipeline share one date grammar.
    """
    try:
        return resolve_target_date(date_text).isoformat()
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
    """Fetch live data and write the snapshot triple, failing closed."""
    from goc_rates.live_snapshot import run_live_snapshot

    return run_live_snapshot(date_text, out_dir, config_path)


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
