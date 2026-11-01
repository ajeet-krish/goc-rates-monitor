# goc-rates-monitor Architecture

Last updated: 2026-11-02 (Phase 4)

## Purpose

Static rate dashboard plus Python pipeline. BoC Valet, FRED, and StatCan WDS
feed one daily snapshot that GitHub Pages publishes as JSON. Phase 2 adds a
par approx curve engine with slopes, carry, spreads, risk, and a fixed
backtest illustration.

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
| `verify.py` | V01 to V18 checks at 1.0 bp tolerance, verify.json, exit code |
| `curve.py` | Par approx curve on semiannual log discounts, bills, knots |
| `analytics.py` | Slopes, butterfly, z, carry roll, CA-US spreads, joins |
| `risk.py` | Par price, modified duration, DV01 per million, semiannual |
| `backtest.py` | Fixed 2s10s mean reversion sketch, next day, DV01 neutral |
| `limits.py` | Central numeric and size caps shared by Phase 2 math |
| `dates.py` | Strict ISO date parsing plus monotonic history validation |

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

## Curve engine

Method `par_approx_semiannual_log_discount_v1` treats benchmark YTM inputs
as par approximations. Knot discounts use `D = 1 / (1 + y / 2) ^ (2 * T)`.
Between knots log discounts interpolate linearly. Ends hold the nearest
knot yield flat. Long is a 30Y proxy and is labelled as such. Minimum three
knots on a half year grid, else fail closed. Bill math uses ACT/365 add on:
`P = F / (1 + Y * t / 365)` with explicit days and face.

## Snapshot format

`snapshot.json` holds metadata, observations, provenance, and warnings.
`manifest.json` holds the sha256 of `snapshot.json`. Canonical form is
sorted keys, indent 2, UTF-8, LF ending, strict floats. Every numeric field
carries a unit. Snapshots are committed to git. Only raw cache is pruned.

Phase 2 observations add `curve` (method, knots, discounts, zero yields),
`spreads` (same date CA-US records), `carry` (yield, rolled yield,
horizon, carry in bp), `risk` (yield, tenor, price, duration, DV01), and
`backtest` (rule, dates, slopes, total PnL). Derived quantities use units
`percent_yield`, `bp`, `bp_per_annum`, `duration_years`,
`dv01_per_million`, and `unitless_ratio` with a `derived:` source.

## Verification

Eighteen checks (V01 to V18) cover canonical form, units, labels, T-bill
price inversion, CORRA roles, FRED lag, StatCan reuse, vintage markers,
manifest match, cross source tolerance, staleness, curve reprice, discount
range and monotonicity, derived units and sources, spread recomputation,
carry and DV01 recomputation, and backtest rule plus count plus next day
recomputation. Tolerance is 1.0 basis point. Any failure blocks the build.
Verify checks caps before recompute, catches arithmetic overflow as a check
failure, validates derived sources against the closed grammar, and validates
backtest dates and slopes without string coercion. Math modules enforce the
shared limits on yields, tenors, periods, knots, bills, horizons, slopes,
and history sizes, with strict ISO dates throughout.

## Config

`config/benchmark_map.yaml` pins schema version 1, tenors 2Y, 5Y, 10Y, 30Y
with Valet BD.CDN ids, FRED DGS comparators, and nullable legacy V codes.
`statcan_indicators` starts empty for the Phase 1 skeleton.

## Scheduling

One daily workflow run after North American close. Phase 2 adds curve
charts. Later phases add alerts plus backfill.

## Phase 4 CPI engine

`src/goc_rates/cpi/` builds an experimental trim and median from 55
pinned StatCan SA components. Bulk ingest (`bulk.py`) runs the WDS two
step fetch (`getFullTableDownloadCSV` for 18100004, 18100256,
18100007) with streamed bytes under `MAX_BULK_BYTES`, lists zip
members without extracting, and hashes each member in memory (spike:
eight digit product ids, weights zip 1.2 MB with two members, CPI data
member 161 MB expanded, hence the 256 MB member cap with a cumulative
guard).
`config/cpi_components.yaml` pins the 55 component registry plus the
2024 expenditure weight vintage with link month 2025-05 provisional;
`components.py` asserts SA true on every row and `weights.py`
renormalizes only when the registry sums to 100 within 1e-6.

`trim_median.py` (`cpi_trim_median_weighted_sa_v1`) sorts monthly SA
rates with link month weights, drops the bottom and top 20 percent of
cumulative weight with partial splits on straddlers, and reads the
median as the first component past 50 percent. Annual rates compound
the trailing 12 monthly cores, never average. `decomposition.py`
reports contributions in percentage points (`w * r / 100`).
`validation.py` compares the replica against published vintages over a
trailing 36 month window with a 24 month minimum; an MAE over 0.10
flags for explanation and never blocks the build. `section.py` stores
two chained index months, twelve history months, and bulk sha256
hashes with short sha12 prefixes.

Method, label, and status are explicit: label `experimental`,
`is_official` false, publisher `statcan`, experimental series
`derived:cpi_trim_median`, and `owns_seasonal_adjustment` false since
StatCan SA values are reused as published. New units
`percent_per_month` and `percentage_points` carry every numeric field.

## Verification

Twenty two checks (V01 to V22). V19 pins the inflation inputs (method,
55 components, 2025-05 link, 100 within 1e-6, bulk sha pairs, SA reuse
owned elsewhere, YYYY-MM reference, count caps). V20 recomputes trim,
median, and YoY within 1.0 bp equivalent (0.01 in percent units). V21
reconciles contributions within 0.01 pp and the 0.40 excluded weight
within 1e-6. V22 asserts the experimental label, recomputes MAE, bias,
and max from stored residuals, and requires the gate flag to match the
recomputed outcome while passing either way. CPI caps live in
`limits.py` (`MAX_CPI_COMPONENTS` 128, `MAX_CPI_MONTHS` 240, bulk byte
and member caps).
