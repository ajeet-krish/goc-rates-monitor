# goc-rates-monitor Decision Records

Last updated: 2026-11-01 (Phase 1)

## D01: uv for Python management

Use uv with a src layout package named `goc_rates`. Rationale: one lockfile,
fast sync, reproducible builds. Consequences: contributors run `uv sync` and
`uv run pytest`, no pip installs.

## D02: Commit the lockfile

Commit `uv.lock` so CI resolves the same versions. Rationale: fail closed on
dependency drift. Consequences: `.gitignore` keeps raw cache ignored but no
longer ignores the lockfile.

## D03: Single daily workflow

One scheduled run per day after North American close. Rationale: sources
publish on lags (CORRA T+1, FRED DGS T+1), so intraday runs add staleness
risk. Consequences: snapshot date maps to the previous joint business day.

## D04: Verify tolerance of 1.0 basis point

Cross source checks pass within 1.0 bp. Rationale: rounds quote noise while
catching series mixups. Consequences: V11 fails the build above tolerance.

## D05: Label yields as YTM

Benchmark yields are yields to maturity in percent, labeled as such in charts.
Rationale: avoids confusion with coupon or price levels. Consequences: every
numeric field carries a unit string.

## D06: Reuse StatCan seasonal adjustment as published

WDS values are stored without extra transformation. Rationale: re-adjusting
revisable core measures adds error. Consequences: verify asserts the reuse
flag (V08) and treats core measures as revisable vintages.

## D07: Canonical JSON form

Snapshots use sorted keys, indent 2, UTF-8, LF endings, strict floats.
Rationale: stable diffs and sha256 manifests. Consequences: writers must use
the snapshot module, never ad hoc dumps.

## D08: Commit snapshots to git

Daily `snapshots/YYYY-MM-DD/snapshot.json` plus `manifest.json` are committed.
Rationale: full history with content hashes for audit. Consequences: raw
cache is the only pruned artifact; snapshots are never pruned.
