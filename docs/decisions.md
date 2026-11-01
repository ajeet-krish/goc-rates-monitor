# goc-rates-monitor Decision Records

Last updated: 2026-11-02 (Phase 4)

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

## D09: Par approx curve with log discount interpolation

Curve v1 treats benchmark YTM inputs as par approximations with method id
`par_approx_semiannual_log_discount_v1`. Rationale: true bootstrap needs
issue level cash flows, so v1 stays explicit about its limits. Consequences:
snapshots label `is_par_approx` true, Long is a 30Y proxy, and verify
reprices knots within 1.0 bp (V13).

## D10: Stdlib math only with half year grid

Curve, analytics, risk, and backtest use stdlib math only with no numpy or
scipy. Rationale: fewer dependencies and deterministic builds. Consequences:
tenors must sit on a half year grid, interpolation is log linear, and ends
hold the nearest yield flat.

## D11: Derived units with explicit sources

Phase 2 adds `percent_yield`, `bp`, `bp_per_annum`, `duration_years`,
`dv01_per_million`, and `unitless_ratio` while keeping `basis_points` for
legacy fields. Rationale: derived outputs need distinct units from raw
inputs. Consequences: verify checks that derived quantities carry a
`derived:` source (V15).

## D12: Inner join with no forward fill

CA-US spreads join on common joint business days only. Rationale:
forward filling hides holidays and T+1 lags. Consequences: one sided
holidays drop from the join and spreads recompute on same dates (V16).

## D13: Simplified carry and closed form risk

Carry roll uses horizon 0.25 years ex coupon and ex funding on an unchanged
curve. Risk uses semiannual closed forms for price, duration, and DV01.
Rationale: a small auditable sketch beats a fragile full attribution.
Consequences: verify recomputes carry and DV01 from stored inputs (V17).

## D14: Fixed backtest rule with lookahead guard

Backtest rule `2s10s_z252_meanrev_v1` uses trailing 252 slopes excluding the
current day with entry at 1.0 z and next day DV01 neutral PnL. Rationale: a
single pinned rule keeps the illustration reproducible. Consequences: runs
need 254 joined observations (252 history plus current plus next day) and
verify recomputes next day PnL (V18).

## D15: Snapshot CLI wires Phase 2 sections from observed quantities

The snapshot CLI builds the benchmarks section from the benchmark map and
attempts the curve, carry, and risk sections from observed benchmark
quantities only. Rationale: no CLI produced snapshot should carry curve or
risk numbers without observed yields. Consequences: the skeleton still exits
1 with pending sections until the live Valet fetch lands, and spreads plus
backtest stay pending until 254 joint slope prints exist.

## D16: Central numeric and size bounds with fail closed caps

All Phase 2 math shares `limits.py` with tenor, period, knot, day, horizon,
yield, slope, source length, and observation count caps. Rationale: one
pinned bound set keeps product limits explicit and prevents unbounded loops
or payload driven memory growth. Consequences: yields must sit within minus
20 to 30 percent, tenors within 60 years with at most 120 semiannual periods
and 10 knots, bills within 366 days, carry horizons within 1.0 year, slopes
within 5000 bp, and histories within 2000 observations with at most 2000
spread records and 10000 quantities.

## D17: Strict ISO dates with monotonic history guards

Date inputs use `dates.py` with a fixed YYYY-MM-DD grammar plus fromisoformat
and round trip validation, and histories must be strictly increasing.
Rationale: grammar validation at the boundary stops traversal, coercion, and
lookahead defects before they reach calendars, joins, or backtests.
Consequences: padded, non calendar, or non increasing dates raise, and joins
plus the 254 observation backtest require strict ISO sequences.

## D18: Closed source identifiers with recompute hardening

Quantity source identifiers must match the closed grammar with a derived,
valet, fred, or statcan prefix plus a bounded suffix, and verify checks caps
before recompute while treating arithmetic overflow as a check failure with
no string coercion. Rationale: closed identifiers keep provenance auditable
and recompute guards keep untrusted snapshot values from crashing the
verifier. Consequences: V15 validates the full source grammar with a derived
prefix, V18 validates dates and slopes without str conversion, and arithmetic
errors fail the affected check.

## D19: Spike then pin the CPI bulk registry

Fetch the StatCan bulk zips for 18100004, 18100256, and 18100007
(eight digit product ids; the ten digit table suffix form returns
406) first, list members and hashes in memory, then pin the discovered
55 component SA series plus the weight vintage in
`config/cpi_components.yaml`. Rationale: the registry is evidence, not
a guess, and any upstream reclassification fails closed against the
pin. Consequences: May 2025 link month on 2024 expenditure weights is
provisional until the bulk metadata confirms the basket; the live
spike showed the weights zip at 1.2 MB with two members while the CPI
data member expands to 161 MB, so the member cap sits at 256 MB with
the cumulative expansion guard unchanged.

## D20: Reuse StatCan seasonal adjustment as published

Variant A reuses StatCan SA component indexes with no local X-13.
Rationale: re-adjusting revisable core measures adds error without an
audit trail. Consequences: every registry row asserts SA true, the
snapshot records `owns_seasonal_adjustment` false, and SA membership
changes explain residuals instead of silently shifting history.

## D21: Weighted trim and median on monthly rates with compounding

Trim removes 20 percent of cumulative weight at each tail with partial
splits on straddling components, median reads the first component past
50 percent, and annual rates compound the trailing 12 monthly cores.
Rationale: this mirrors the published method (rank, renormalize the
kept 60 percent, compound, cohere through rounded indexes).
Consequences: averaging the 12 monthly rates is a test failure, and
verify recomputes trim, median, and YoY within 1.0 bp equivalent.

## D22: Validation gate flags but never blocks

Replica YoY validates against published vintages over a trailing 36
month window with a 24 month minimum; MAE over 0.10 raises a flag, not
an error. Rationale: upstream revisions move vintages, and the build
must distinguish revision from arithmetic bug without stopping the
pipeline on honest misses. Consequences: V22 recomputes MAE, bias, and
max from stored residuals and requires the flag to match while passing
either way; hash equality separates bug from revision.

## D23: Bulk hashes distinguish revision from bug

Every snapshot stores the bulk zip sha256 plus a short sha12 per
product with retrieval UTC and link month vintage. Rationale: when a
published vintage moves, equal hashes mean local arithmetic is wrong
and changed hashes mean upstream revised. Consequences: provenance
carries `statcan_cpi` with the bulk link, vintage, and short hashes,
and member hashes are computed in memory without extraction.

## D24: Experimental label with minimal page wiring

The inflation section is labelled experimental and unofficial while
headline CPI stays final, and the page renders publisher versus
experimental series, the decomposition, the validation flag, the weight
vintage, and the short bulk hash. Rationale: core measures are
revisable vintages and the page must not present replica trim as an
official print. Consequences: V22 asserts the label and status, and the
site blocks derived displays on failed verification like every other
section.
