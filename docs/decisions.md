# goc-rates-monitor Decision Records

Last updated: 2026-11-05 (Phase 8.2)

## D01: uv for Python management

Use uv with a src layout package named `goc_rates`. Rationale: one lockfile,
fast sync, reproducible builds. Consequences: contributors run `uv sync` and
`uv run pytest`, no pip installs.

## D02: Commit the lockfile

Commit `uv.lock` so CI resolves the same versions. Rationale: fail closed on
dependency drift. Consequences: `.gitignore` keeps raw cache ignored but no
longer ignores the lockfile.

## D03: Single daily workflow

One scheduled run per weekday at 16:30 UTC after the previous North
American close. Rationale: sources publish on lags (CORRA T+1, FRED DGS
T+1, BoC bond yields D+1 at 10:00 EST), so intraday runs add staleness
risk. Consequences: snapshot date maps to the previous joint business
day, and the run polls until that date's Valet print exists before
snapshotting.

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

Superseded 2026-11-05 by D39 (Phase 8.2): history observations are now
capped at 2750, while spread records stay at 2000.

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

## D25: Pinned switch feed with null outgoing legs

`config/benchmark_switches.yaml` pins schema 1, source `bench_CDN.pdf`,
and feed vintage 2026-11-01 with seven benchmark switch events. Each
event pins a tenor, an effective date, and an incoming maturity plus
coupon; outgoing legs stay null where unknown and are never
fabricated. Rationale: the bench PDF is evidence, and invented
outgoing issues would corrupt the switch window. Consequences: the
loader rejects drift, duplicates, bad tenors, and non strict dates,
and the feed hash travels in provenance.

## D26: Joint effective dates with LONG mapped to 30Y

The effective joint date is the first joint business day on or after
the effective date, so weekend and holiday shifts are explicit via the
calendar legs. LONG bench events map to the 30Y curve tenor.
Rationale: switches take effect on the first printable joint day, and
the curve only models 30Y. Consequences: verify recomputes every
joint date, and `switch_in_window` tests `(prev, current]` per tenor.

## D27: Switch suppresses, gap keeps with a flag

`switch_break` suppresses the day over day delta to null, while
`calendar_gap` keeps the numeric delta with a gap flag. `missing_prev`
and `insufficient_history` stay null, and `comparable` keeps numbers.
Rationale: a rotation can move the print with no market move, while a
holiday gap is still a market move worth showing. Consequences: V23
enforces the nullness rule per gate, and the page can annotate rather
than splice.

## D28: Dedicated V23 per user override

Breaks integrity is a dedicated V23 check, not folded into V04 or
V15. V04 stays benchmark labels only, and V15 additionally accepts
`derived:dod_gate` quantities from the breaks section. V23 was added
per user override to keep the switch gate visible as its own line.
Rationale: label drift, derived units, and switch gates fail for
different reasons and deserve distinct signals. Consequences: the
report grows from 22 to 23 checks, and a missing breaks section
beside a present curve fails.

## D29: Feed failure fails to skeleton

The live snapshot loads the switch feed beside the benchmark map and
records `benchmark_switches` provenance with vintage plus sha256. Any
feed error routes to the skeleton fallback, never to a silent pass
without breaks. Rationale: publishing a curve without its rotation
flags would mislead slope and carry readers. Consequences: missing or
corrupt feeds exit 1 through the skeleton path.

## D30: Synthetic demo stays frontend only

Synthetic frontend demo data for the breaks page is deferred to the
web layer and never enters the pipeline snapshots or verification.
Rationale: pipeline fixtures must stay pinned to bench evidence, and
demo moves belong behind an explicit frontend flag. Consequences: no
synthetic yields appear in `snapshots` or `verify.json`.

## D31: Spreads envelope with complete tenor set

Spreads use a typed envelope with status, reason, and records, and the ok
path requires the complete 2Y, 5Y, 10Y, and 30Y set with no duplicates and
no positional reads. Rationale: a partial list can pass vacuously while
hiding a missing tenor, and positional reads misalign tenors after a feed
change. Consequences: V16 fails legacy arrays closed, requires explicit
ca_date and us_date equal to the record date, and checks the full set on
every ok envelope.

## D32: Benchmark map issues source

Benchmark issues live in `config/benchmark_map.yaml` at schema version 2,
with one maturity date, coupon percent, and semiannual frequency per tenor
sourced from the bench CDN evidence carried by the switch feed incoming
legs. Rationale: the bootstrap needs issue level cashflows, and the bench
PDF plus the pinned switch feed are the evidence for the currently
benchmark issues. Consequences: the loader rejects drift, V24 agrees each
instrument maturity and coupon with the latest incoming leg effective on or
before settlement, and null incoming legs fail closed.

## D33: Sequential bisection for discount anchors

The bootstrap solves discount anchors sequentially in ascending maturity
with bisection inside the price tolerance, holding earlier anchors fixed
and interpolating log discounts between them. Rationale: each longer bond
prices off all earlier anchors, so solving out of order would reuse an
unsolved tail. Consequences: at most 200 bisection iterations run per
anchor, the bracket spans near zero to the previous anchor, and any miss
beyond 1.0 bp fails closed.

## D34: Legacy dispatch for curve checks

V13, V14, and V17 dispatch on the curve method, with the legacy par approx
path kept for the old recompute and the true bootstrap path used when the
method is `true_bootstrap_semiannual_log_discount_v1`. Rationale: history
must keep verifying old snapshots while live output moves to the bootstrap.
Consequences: V24 and V25 fail closed on a legacy curve with an explicit
method message, and the bootstrap V13, V14, and V17 replace the legacy
results before reporting.

## D35: Backfill command builds pure history

`src/goc_rates/history.py` builds joint daily rows plus CPI rows as pure
functions with no I/O and no clock, sealed by `build_backfill_document`.
Rationale: history must be reproducible from injected histories and an
explicit asof, with row counts and canonical bytes bounded before any
publish step. Consequences: daily rows join the four Canadian tenors on
joint complete dates with slopes, spreads, switch flags, and gap flags,
CPI rows compound trailing 12 month cores, and the document fails closed
outside the daily, monthly, and byte caps.

## D36: Merged file carries a verified flag

Every backfill row carries verified false with null snapshot and input
digests plus a recomputing row digest over the canonical subdocument.
Rationale: merged rows are not yet tied to a published snapshot, so they
must read as unverified until a later verification pass seals them.
Consequences: `build_backfill_document` recomputes every row digest, and
any digest drift fails the document before counts or bytes are checked.

## D37: Partial legs join per field with no forward fill

Spreads join each tenor US leg on the same date only, so a missing US
print yields null for that tenor with a status of ok, partial, or missing.
Rationale: forward filling hides holidays and T+1 lags, and one tenor gap
must not blank the full row. Consequences: daily rows keep per tenor
spreads with explicit units, the row status reflects how many legs are
present, and calendar gaps stay visible beside switch flags.

## D38: Bootstrap and backfill caps

Bootstrap bounds use `MAX_CASHFLOWS_PER_INSTRUMENT` 130,
`MAX_BOOTSTRAP_ANCHORS` 260, and `BOOTSTRAP_PRICE_TOLERANCE_BP` 1.0, and
backfill bounds use daily rows 250 to 1250, CPI months 1 to 60, and a 5 MiB
document cap. Rationale: one pinned bound set keeps solver loops, schedule
lengths, and history payloads explicit and prevents upstream growth from
exhausting memory. Consequences: cashflow generation, anchor solving, and
document assembly fail closed beyond the caps, and verify checks caps
before any recompute.

Superseded 2026-11-05 by D39 (Phase 8.2): the daily row bounds are now
250 to 2750. The bootstrap bounds, the CPI month bounds, and the 5 MiB
document cap stand as written.

## D39: Phase 8.2: 10 year window with raised history bounds

Dated 2026-11-05. `MAX_BACKFILL_DAILY_ROWS` and `MAX_HISTORY_OBS` are both
2750, `FRED_LOOKBACK_DAYS` and `VALET_LOOKBACK_DAYS` are both 3653 days
(about ten calendar years including leap days), and
`MIN_BACKFILL_DAILY_ROWS` stays 250. Rationale: a trailing ten year window
matches the BoC ten year lookup standard while the raised row and
observation caps keep every count bound fail closed. Consequences: this
supersedes the daily row upper bound in D38 and the history observation
bound in D16, byte caps stay 5 MiB, and drift tests pin the raised values
in both the pipeline and the web build.