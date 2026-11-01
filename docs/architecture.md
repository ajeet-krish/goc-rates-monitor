# goc-rates-monitor Architecture

Last updated: 2026-11-01 (Phase 1)

## Purpose

Static rate dashboard plus Python pipeline. BoC Valet, FRED, and StatCan WDS
feed one daily snapshot that GitHub Pages publishes as JSON.

## Pipeline

Entry: `python -m goc_rates snapshot --date YYYY-MM-DD --out snapshots/YYYY-MM-DD`.
Verify: `python -m goc_rates verify --snapshot snapshots/YYYY-MM-DD/snapshot.json`.

Package layout (`src/goc_rates`):

| Module | Role |
| ------ | ---- |
| `models.py` | Quantity TypedDict with Unit, Quality, SourceId plus validation |
| `calendar.py` | Joint CA plus US business calendar, Toronto snapshot dating |
| `config.py` | BenchmarkEntry frozen dataclass plus benchmark map loader |
| `clients/base.py` | 15 s timeout, 3 retries on 429 and 5xx, Retry-After, User-Agent |
| `clients/valet.py` | BD.CDN series and group fetch with label assertion, no key |
| `clients/fred.py` | DGS fetch, key from env, missing key yields missing quality |
| `clients/statcan.py` | WDS vectors fetch, SA values reused as published |
| `snapshot.py` | Canonical JSON, atomic write, manifest sha256, raw retention |
| `verify.py` | V01 to V12 checks at 1.0 bp tolerance, verify.json, exit code |

## Data sources

Valet base is `https://www.bankofcanada.ca/valet/`. Group
`bond_yields_benchmark` holds the benchmark yields in percent.
FRED DGS yields are percent, daily, T+1 latency, never revised.
StatCan WDS uses `getDataFromVectorsAndLatestNPeriods`, no key.

## Calendar

CA leg follows BoC Schedule I open days in Toronto. US leg follows the SIFMA
bond calendar. Joint business days need both legs open. CORRA value dates lag
publication by one business day, so snapshots store value date, pub date,
and a date role flag.

## Snapshot format

`snapshot.json` holds metadata, observations, provenance, and warnings.
`manifest.json` holds the sha256 of `snapshot.json`. Canonical form is
sorted keys, indent 2, UTF-8, LF ending, strict floats. Every numeric field
carries a unit. Snapshots are committed to git. Only raw cache is pruned.

## Verification

Twelve checks (V01 to V12) cover canonical form, units, labels, T-bill price
inversion, CORRA roles, FRED lag, StatCan reuse, vintage markers, manifest
match, cross source tolerance, and staleness. Tolerance is 1.0 basis point.
Any failure blocks the build (fail closed).

## Config

`config/benchmark_map.yaml` pins schema version 1, tenors 2Y, 5Y, 10Y, 30Y
with Valet BD.CDN ids, FRED DGS comparators, and nullable legacy V codes.
`statcan_indicators` starts empty for the Phase 1 skeleton.

## Scheduling

One daily workflow run after North American close. Future phases add charts
(Phase 2) and alerts plus backfill (Phase 3).
