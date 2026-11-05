# GoC Rates Monitor Research Notes

Last updated: 2026-11-05

## 2026-11-01 - Phase 1 Foundation: Valet, FRED, StatCan, calendars, bill math

Phase 1 builds Valet plus FRED plus StatCan clients with label assertion,
calendar.py (joint CA plus US calendar with vintage dates), benchmark_map.yaml
skeleton, snapshot writer, verify skeleton, plus a 0.5 day StatCan spike to pin
tables 18-10-0004 plus 0256 plus 0259 plus 0007 and weight vintage.

### Key Findings
| Finding | Source | Confidence | Application |
|---------|--------|------------|-------------|
| Valet group `bond_yields_benchmark` holds 7 daily series: `BD.CDN.2YR.DQ.YLD`, `BD.CDN.3YR.DQ.YLD`, `BD.CDN.5YR.DQ.YLD`, `BD.CDN.7YR.DQ.YLD`, `BD.CDN.10YR.DQ.YLD`, `BD.CDN.LONG.DQ.YLD`, `BD.CDN.RRB.DQ.YLD`; unit Percent, frequency business-daily | BoC Valet `groups/bond_yields_benchmark/json` (fetched live 2026-11-01) | High | `benchmark_map.yaml` skeleton: pin these 7 series names plus labels |
| CORRA Valet series is `AVG.INTWO`, label "Canadian Overnight Repo Rate Average (CORRA)"; dated by value date, published T+1 business day around 09:00 ET (window 09:00 to 11:00 ET); CORRA Compounded Index published same-day 11:30 ET | BoC CORRA methodology page; Sphera CORRA series reference; BoC CORRA page | High | Valet client must not expect value date D on date D; snapshot records both value date and pub date; index vs rate timing differs |
| Valet needs no key; base `https://www.bankofcanada.ca/valet/`; routes need `seriesName` or `groupName` plus format; publish slots: bond yields 09:30 to 10:00 ET, interest rates 12:15 to 12:30 ET, T-bills 10:30 to 11:30 ET, FX 16:30 ET | BoC Valet how-to guide; BoC statistics page | High | Fetch scheduling plus staleness guards in pipeline |
| BoC revises published series: Dec 2025 weekly plus monthly CANSIM benchmark bond yields were revised Jan 2026 (not based on last-trading-Wednesday yield) | CIA explanatory report 226021E, 2026-01-28 | High | Label assertion plus vintage dates are load-bearing, not cosmetic; store revision markers |
| Legacy CANSIM V codes (for example V39062-style) still shown on BoC 10-year lookup pages; Valet uses new dotted names; 10-year lookup pages carry series notes plus metadata | BoC T-bill yields 10-year lookup; BoC bond yields 10-year lookup | Medium | `benchmark_map.yaml` should carry a `legacy_v_code` column for traceability, asserted where known, nullable otherwise |
| StatCan WDS `getFullTableDownloadCSV/{productId}/en` returns JSON `{status, object: zipURL}`; no key; zip holds data plus metadata CSVs; productId is 10-digit (for example 1810000401) | StatCan WDS user guide; tips page; Medium walkthrough | High | StatCan client shape: two-step fetch (JSON link, then zip); hash the zip bytes |
| Table pins: 18-10-0004-01 CPI monthly NSA (ex CANSIM 326-0020); 18-10-0256-01 core stats index levels BoC definitions (ex 326-0023, base Jan 1989=100); 18-10-0256-02 YoY percent change; 18-10-0259-01 historical real-time releases of core measures (ex 326-8023, the vintage table); 18-10-0007-01 basket weights (ex 326-0031, occasional frequency) | StatCan table pages; StatCan doc 2301_D69_V1; Daily release 2026-10-19 | High | Spike must pin all four productIds (1810000401, 1810025601, 1810025901, 1810000701) plus record WDS `releaseTime`, `cubeStartDate`, `cubeEndDate` |
| CPI basket re-weighted with May 2025 release on 2024 expenditure weights (table 18-10-0007-01); shelter weight jump driven by mortgage interest cost (5.65 percent) plus rent (7.19 percent) | StatCan Daily 2025-06-24; StatCan paper 62F0014M2025003 | High | Weight vintage must be pinned per snapshot; basket updates move history interpretation |
| CPI-common, CPI-median, CPI-trim are revisable (median and trim via seasonal adjustment, common via full-sample factor model); 18-10-0259-01 exists precisely to hold historical release vintages | StatCan Daily table t004a 2026-10-19; StatCan doc 2301_D69_V1 | High | Verify skeleton should treat core measures as vintage series, headline CPI as unrevised |
| FRED DGS10 and DGS2: source H.15, units Percent NSA, daily, never revised (single canonical print per date); H.15 publishes about 16:15 ET, FRED ingests T+1 morning | FRED DGS10 series page; Eco3min DGS10 notes | High | FRED client: expect T+1 latency; no vintage handling needed for DGS yields |
| FRED real-time protocol: `realtime_start` plus `realtime_end` define the as-of window (default today equals FRED mode); `vintage_dates` selects revisions; `output_type` 1 to 4 selects layout; `series/vintagedates` lists revision dates; API key required (free) | FRED API docs (realtime_period, series_vintagedates); PrismDataLab ALFRED post | High | Future macro series (CPI, GDP) must use ALFRED vintage params; yields skip it |
| CA holiday source of record: BoC holiday schedule page (national holidays); CORRA days equal Schedule I bank open days in Toronto | BoC holiday schedule; BoC CORRA methodology | High | calendar.py CA leg: encode BoC schedule, fall back to CRA public-holiday list for validation |
| US holiday sources: NYSE trading calendar plus ICE holiday announcement (2025 to 2027 published), Fed K.8 schedule, SIFMA bond-market recommendations (early closes 14:00 ET); bond and equity calendars differ (for example Columbus Day, Veterans Day) | NYSE hours-calendars; ICE press release; Fed K.8; SIFMA holiday schedule; FINRA 2026 schedule | High | Joint calendar uses SIFMA (bond) leg for US yields, not NYSE equity calendar; record which leg closed each date |
| Canadian T-bill yield convention: `Y = (F - P) / P * 365 / t`; add-on price recovery: `P = F / (1 + Y * t / 365)`; actual days, 365-day year; BoC auctions close 10:30 with standard terms (about 98, 168, 364 days) | Finance Canada technical guide; BoC regular T-bill results; CFFiM conventions | High | Verify skeleton recomputes auction average price from average yield as a cross-check |
| GoC bond price convention: semi-annual discounting `P = sum(CF_n / (1 + y/200)^n)`; benchmark issues rotate (current list with effective dates on BoC lookup page) | Finance Canada technical guide; BoC benchmark bonds page | Medium | Yields are the stored primitive; price math only for verify cross-checks |

### Relevant Equations
| Equation | Description | Variables |
|----------|-------------|-----------|
| `Y = (F - P) / P * 365 / t` | Canadian T-bill quoted yield (bank-add-on basis) | Y quoted yield (decimal), F face value, P price, t actual days to maturity |
| `P = F / (1 + Y * t / 365)` | T-bill price from quoted add-on yield (verify inversion) | Same as above |
| `P = sum_n CF_n / (1 + y/200)^n` | GoC bond clean price from yield to maturity | P price, CF_n cash flow period n (coupon/2, plus 100 at maturity), y yield in percent, n semi-annual periods |
| `trim/median over weighted monthly price changes` | CPI-trim removes 20 percent of weighted monthly variation at each tail (40 percent total); CPI-median is the 50th percentile weighted price change | Basket weights from 18-10-0007-01; SA component indexes |
| `vintage(date) = value known with realtime window containing date` | ALFRED point-in-time read: `realtime_start = realtime_end = asOf` | asOf vintage date, observation date, value |

### Validation Data
| Benchmark | Value | Source | Uncertainty |
|-----------|-------|--------|-------------|
| CORRA 2026-10-29 value date: 2.4900 percent (vs 2.2400 prior days) | 2.49 percent | BoC CORRA page | None stated; revised prints marked "R" |
| CORRA Compounded Index 2026-10-30 | 117.53533200 | BoC CORRA page | 8 decimals published |
| 10Y GoC benchmark 2026-10-14 | 3.85 percent | BoC selected bond yields | Daily, sourced CanDeal DNA plus BoC |
| Sep 2026 CPI-median / CPI-trim YoY | 1.9 / 1.8 percent | StatCan Daily t004a 2026-10-19 | Revisable (SA plus factor model) |
| DGS10 2026-10-28 | 5.05 percent | FRED, updated Oct 29 2026 15:16 CDT | Never revised |
| Current 10Y benchmark issue | 2036.06.01, 3.25 percent (eff. 2026.06.23) | BoC benchmark bonds page | Rotates; effective date recorded |
| Mortgage interest cost basket share (2024 weights) | 5.65 percent; rent 7.19 percent | StatCan 62F0014M2025003 | Rounding, weights sum to 100 percent |

### Practical Implications
- Valet client asserts `groupSeries` labels from `bond_yields_benchmark` on every fetch and fails closed on label drift; store group plus series label strings in the snapshot.
- StatCan spike pins productIds 1810000401, 1810025601, 1810025901, 1810000701; records WDS `releaseTime`, zip URL, and sha256 of the downloaded zip; records the active basket weight vintage from 18-10-0007-01.
- CORRA handling: value date lags publication by one business day; snapshot stores `value_date`, `pub_date`, and a `date_role` flag; never join CORRA value dates to same-day FRED or Valet yields without an explicit lag note.
- calendar.py: joint CA (BoC Schedule I open days) plus US (SIFMA bond calendar) table with per-date leg flags and a `vintage` (source retrieval date); FRED DGS prints are T+1 so the calendar marks expected-lag days.
- FRED client needs an API key (free) unlike Valet and WDS; DGS yields need no vintage logic, but the client keeps `realtime_start/end` params for future macro series.
- Verify skeleton: recompute T-bill price from average yield via the ACT/365 add-on formula and compare to `AUC_TBILL_AVG_PRICE`; treat core CPI measures (0256/0259) as revisable and headline CPI (0004) as final.
- Pin log rule: every snapshot records source URL, retrieval timestamp (UTC), content sha256, and upstream vintage marker (Valet date, WDS releaseTime, FRED observation date); any upstream label or schema change blocks the build.

### Citations
1. Bank of Canada, "Valet API how-to" and "Valet API lists" - https://www.bankofcanada.ca/valet-api-how-to
2. Bank of Canada, `groups/bond_yields_benchmark/json` (live fetch 2026-11-01)
3. Bank of Canada, "Methodology for calculating CORRA" - https://www.bankofcanada.ca/rates/interest-rates/corra/methodology-calculating-corra
4. Bank of Canada, CORRA page - https://www.bankofcanada.ca/rates/interest-rates/corra
5. Bank of Canada, holiday schedule - https://www.bankofcanada.ca/press/upcoming-events/bank-of-canada-holiday-schedule
6. Bank of Canada, "Canadian bond yields: 10-year lookup" and benchmark bonds effective dates
7. CIA, "Bank of Canada Revisions of December 2025 CANSIM Series" 226021E, 2026-01-28
8. Statistics Canada, WDS user guide - https://www.statcan.gc.ca/en/developers/wds/user-guide
9. Statistics Canada, tables 18-10-0004-01, 18-10-0256-01, 18-10-0256-02, 18-10-0259-01, 18-10-0007-01
10. Statistics Canada, Daily CPI 2026-10-19 table t004a (core revision note)
11. Statistics Canada, 62F0014M2025003 (2025 basket update on 2024 weights)
12. Statistics Canada, doc 2301_D69_V1 (CPI-trim/median index publication)
13. FRED API docs, "Real-Time Periods" and "series/vintagedates" - https://fred.stlouisfed.org/docs/api/fred/
14. FRED series DGS10 page (H.15, Percent NSA, daily)
15. NYSE hours-calendars; ICE NYSE holiday announcement (2025-2027); Fed K.8; SIFMA holiday schedule
16. Finance Canada, "Determining Bond and Treasury Bill Prices and Yields" - https://www.canada.ca/en/department-finance/programs/financial-sector-policy/securities/securities-technical-guide/determining-bond-treasury-bill-prices-yields.html
17. CFFiM, "Canadian Conventions in Fixed Income Markets"

### Verification Checklist
- [x] Findings are from reputable sources
- [x] Equations are correctly transcribed
- [x] Validation data includes uncertainty
- [x] Practical implications are actionable
- [x] All sources cited
- [x] Research supports phase architecture decisions

## 2026-11-01 - Phase 2 Curve engine: bills, par approx, slopes, z, carry, CA-US, CORRA, DV01

Phase 2 builds: bill ACT/365 conversion plus secondary-market average yield,
benchmark YTM par-approx curve with monotone interpolation on log discounts,
slopes 2s10s, 2s5s, 5s10s, 10s30s with 60 plus 250 day z, 1M carry-roll on an
unchanged curve, CA-US 2y, 5y, 10y same-day plus lagged spreads, CORRA minus
target, DV01-neutral illustrative backtest with one fixed rule, no NSS in v1.

### Key Findings
| Finding | Source | Confidence | Application |
|---------|--------|------------|-------------|
| CA T-bill quoted yield is bank-add-on: `Y = (F-P)/P * 365/t` with `t` actual days remaining, 365-day year; inversion `P = F/(1+Y*t/365)`. Applies to secondary-market average yields (BoC `tbill` group 1M/3M/6M/1Y) as well as auction averages; `t` uses standard terms about 30/91/182/365 days but must be actual days for conversion | Finance Canada technical guide; CFFiM conventions | High | Bill engine: convert each secondary-market avg yield to price via actual `t`; never use 360-day or bond-equivalent without conversion; store `t_days` and convention label |
| GoC domestic bond price convention is semi-annual discounting: `P = sum_n CF_n/(1+y/200)^n`, `CF_n = coupon/2`, final `+100`; accrued uses Actual/365; quoted price excludes accrued, YTM solves dirty price equality | Finance Canada technical guide | High | Verify cross-check only; yields remain stored primitive; price math documents par-approx limits |
| BoC benchmark yields are NOT par yields: mid-market closing YTMs of selected issues maturing approximately in term (2/3/5/7/10Y plus Long); issue rotates when building benchmark is adopted (e.g. 2Y 2028-08-01 2.75 percent eff. 2026-08-06; 10Y 2036-06-01 3.25 percent eff. 2026-06-23); day-to-day change can reflect switch to a more topical issue, not market move | BoC selected bond yields page; Notes on Canadian bond yields; bench_CDN.pdf | High | Par-approx must flag `benchmark_switch` dates from bench_CDN effective dates; z-scores and carry must be interpreted across switches; never present v1 curve as true par or zero curve |
| Par-approx error sources: (1) coupon bias (benchmark coupon differs from par, price differs from 100, so YTM differs from par yield for same maturity); (2) tenor mismatch (actual residual maturity differs from label, worst at long end where Long benchmark is ~30Y proxy, e.g. 2057-12-01 3.50 percent); (3) switch jumps. No NSS in v1 by design; label output `par_approx` plus method version | BoC notes page; Finance Canada price formula; BIS Papers 25 on BoC MLES vs NSS choice | High | Disclosure string in snapshot methods; long-end 10s30s slope carries largest approx error; tester pins switch-date cases |
| US Treasury official par curve is monotone convex (Hagan-West family) on bootstrapped instantaneous forwards from on-the-run bid prices (FRBNY about 15:30 ET), true par since 2021-12-06 replacing quasi-cubic Hermite spline; v1 does NOT replicate it, FRED DGS CMTs are consumed as comparators only | Treasury yield curve methodology (2025-02-18 revision); methodology change sheet | High | Do not fit NSS or MC in v1; cite Treasury only to justify why CA v1 stays par-approx and why CA-US spread compares benchmark-YTM vs CMT-par with disclosed basis |
| BoC official zero-coupon curve uses Merrill Lynch Exponential Spline (MLES) on bond plus bill prices, daily 0.25 to 30Y, published weekly Thursday about 16:30 ET with two-week lag; v1 must not confuse this lagged statistical curve with daily par-approx trading curve | Bolder-Johnson-Metzler 2004-48; BIS Papers 25 technical note; BoC yield-curves page | High | Roadmap note: Phase 6 true bootstrap may target MLES or NSS; v1 daily curve is separate product with its own method id |
| Interpolation rationale: interpolate monotone (PCHIP) on log discounts `ln D` vs `T`, not linear on yields. Linear-on-yield breaks discount monotonicity and implies discontinuous forwards (Hagan-West Raw method = piecewise-constant forwards). Log-discount linear guarantees positive decreasing `D`, positive forwards, no negative-rate arbitrage in normal regimes; monotone (PCHIP/Hyman filter) preserves shape without overshoot that cubic splines produce | Hagan-West 2006 AMF and 2008 Wilmott; NAG e01cef reference | High | Curve engine: `D_i = 1/(1+y_i/2)^(2*T_label)` proxy, PCHIP on `(T, ln D)`, recover `y(T)`; clamp flat extrapolation, never extrapolate beyond Long; document as `log-discount-PCHIP-v1` |
| Slope z: rolling `z = (s-mu)/sigma` on 60-day (about 3M, tactical) plus 250-day (about 1Y, cyclical) windows; require min obs (60-window needs at least 40 non-NA, 250-window at least 150) else `NA` with `insufficient_history` flag; regime flags on benchmark-switch dates and BoC policy dates; switch handling is flag-plus-freeze (hold z NaN for 5 days post-switch or annotate), never splice-adjust yields in v1 | Standard rolling-z practice; BoC switch note (change may reflect switch) | Medium | Backend implements `min_obs` gate plus `regime_flag`; tester validates NaN handling and flag propagation |
| Carry-roll 1M on unchanged curve: `roll_yield_move = y(T-1M tenor point)-y(T)` read off same-day curve, `carry_1M ≈ y(T)*h + roll` simplified, disclosed NO coupon accrual and NO funding leg; horizon fixed 1 month (21 biz days approx); yields in percent annualised, result in percent per month | Market carry/roll-down definition; BoC curve data as input | Medium | Label `carry_roll_1M_unChanged_curve_ex_coupon`; methods text must state simplification; no P and L claim |
| DV01 hedge: `DV01 ≈ ModDur*P*0.0001` per unit notional; `ModDur = MacDur/(1+y/2)`; duration-neutral ratio `HR = DV01_long/DV01_short`; illustrative backtest uses one fixed rule (e.g. DV01-neutral 2s10s flattener held N days) with costs disclosed as zero; not a strategy recommendation | CME DV01 guides; AnalystPrep hedge-ratio note; MX LGB spread paper (currency-adjusted DV01 ratio pattern) | High | Backtest module: compute DV01 from par-approx yields plus assumed par coupon, size short leg by HR, report gross moves only |
| CA-US join: inner join on common SIFMA-plus-BoC business days; same-day spread plus 1-day lagged (CA date vs prior US print) to handle FRED T+1 and 16:15 ET H.15 timing; never forward-fill, missing leg yields `NA` spread; CORRA value-date never joined to same-day yields without lag note | Phase 1 calendar finding; FRED H.15 timing; BoC CORRA T+1 pub rule | High | Snapshot join keys `ca_us_same_day` and `ca_us_lagged_1d`; verify asserts no forward-fill |
| CORRA calc: trimmed volume-weighted median (drop bottom 25 percent volume as specials), fallback = target plus 5-day mean CORRA-target spread if trimmed volume below max(3B, 30 percent of 5-day avg) or technical failure; CORRA value-date T published T+1 about 09:00 ET, index 11:30 ET same-day; spread `CORRA minus target` uses target effective that value date | BoC CORRA methodology page | High | CORRA engine: store value date, pub date, fallback flag; spread in bp vs target vintage |

### Relevant Equations
| Equation | Description | Variables |
|----------|-------------|-----------|
| `Y = (F-P)/P * 365/t` | CA T-bill quoted add-on yield | Y decimal, F face, P price, t actual days |
| `P = F/(1+Y*t/365)` | T-bill price inversion (verify plus bill engine) | Same as above |
| `P = sum_n CF_n/(1+y/200)^n` | GoC bond price from YTM | P per 100, CF coupon/2 (final +100), y percent, n half-years |
| `D_i = 1/(1+y_i/200)^(2*T_i)` then PCHIP on `(T_i, ln D_i)` | v1 discount proxy plus log-interpolation | y_i benchmark YTM percent, T_i label tenors 2/5/10/30 (Long=30 proxy) |
| `y(T) = 2*(D(T)^(-1/(2*T))-1)*100` | Recover semi-annual par-approx yield from interpolated discount | D(T) = exp(interp ln D), T years |
| `s = y_L - y_S` (bp = *100) | Slope e.g. 2s10s | y in percent |
| `z_k = (s-mu_k)/sigma_k`, k in {60, 250} | Rolling slope z | mu/sigma sample mean/std over k biz days, min obs gate |
| `CORRA_spread = CORRA - target` | Funding pressure gauge | Percent, converted to bp |
| `ModDur = (1/P)*sum_n n/2*CF_n/(1+y/200)^(n+1)/100` approx; `DV01 = ModDur*P*0.0001` | Dollar value of 01 per 100 notional | P price, y percent |
| `HR = DV01_long/DV01_short`; `N_short = N_long*HR` | DV01-neutral hedge ratio | N notionals |
| `carry_1M ≈ y(T)*h + (y(T-h_curve)-y(T))` with h=1/12, unchanged curve | Simplified roll-down carry, ex-coupon ex-funding | y percent decimal |

### Validation Data
| Benchmark | Value | Source | Uncertainty |
|-----------|-------|--------|-------------|
| Bill example 990.13 per 1000, 91-day implies 4.00 percent | 4.00 percent | Finance Canada guide | Exact by convention; t must be actual |
| Current benchmarks (Oct 2026 vintage): 2Y 2028-08-01 2.75 percent (2026-08-06); 5Y 2031-09-01 3.00 percent (2026-09-10); 10Y 2036-06-01 3.25 percent (2026-06-23); Long 2057-12-01 3.50 percent (2026-03-06) | See table | BoC selected yields plus bench_CDN.pdf | Rotates; effective date recorded |
| Sample benchmark prints 2026-10-21: 2Y 3.32, 5Y 3.62, 10Y 3.90, Long 4.19 percent | See row | BoC selected bond yields | Daily mid-market close, CanDeal DNA |
| Treasury MC par method live 2021-12-06; inputs most-recently-auctioned bills/notes/bonds, FRBNY about 15:30 ET bid | Method date | Treasury methodology plus change sheet | Treasury reserves input changes |
| BoC zero-coupon DB lag two weeks, Thursday 16:30 ET | Schedule | BoC yield-curves page | NA on holidays |
| CORRA fallback rule max(3B, 30 percent of 5-day avg); trim bottom 25 percent volume | Rule | BoC CORRA methodology | Threshold computed daily |
| FRED DGS T+1 latency, never revised | Latency | Phase 1 FRED finding; H.15 16:15 ET | No vintage handling |

### Practical Implications
- Bill module converts each BoC secondary-market average yield with actual `t` and 365-day add-on; stores `t_days`, convention `ACT/365-add-on`, inversion check at 0.1 bp; auction averages reuse same formula with auction term days.
- Curve module v1: inputs 2Y/5Y/10Y/Long benchmark YTMs (plus 3Y/7Y for diagnostics only); proxy tenors 2/5/10/30; PCHIP on log discounts; flat ends; method id `par-approx-logdiscount-PCHIP-v1`; output flagged `is_par_approx=true`, `is_zero=false`, `is_nss=false`.
- Switch table from bench_CDN effective dates drives `benchmark_switch` flags; z frozen/NA window 5 days; carry annotated across switches; 10s30s slope gets `high_approx_error` warning.
- Join module: inner join on joint CA-US biz days; two CA-US spreads (same-day, lagged-1d); no forward-fill assertion in verify; CORRA spread separate daily series by value date.
- Backtest: single fixed DV01-neutral rule, gross moves only, zero-cost disclosure, no Sharpe or live-signal claims; DV01 from par-approx yields assuming par coupon.
- Phase 6 note: true bootstrap (MLES per Bolder et al. or NSS) deferred; v1 interpolation choice keeps forwards positive and local, unlike cubic-on-yield.

### Citations
1. Finance Canada, "Determining Bond and Treasury Bill Prices and Yields" - https://www.canada.ca/en/department-finance/programs/financial-sector-policy/securities/securities-technical-guide/determining-bond-treasury-bill-prices-yields.html
2. Bank of Canada, "Selected bond yields" and "Notes on Canadian bond yields" - https://www.bankofcanada.ca/rates/interest-rates/canadian-bonds and https://www.bankofcanada.ca/rates/interest-rates/lookup-bond-yields/notes-on-canadian-bond-yields
3. Bank of Canada, bench_CDN.pdf benchmark issues plus effective dates - https://www.bankofcanada.ca/stats/assets/pdf/bench_CDN.pdf
4. Bank of Canada, "Yield curves for zero-coupon bonds" - https://www.bankofcanada.ca/rates/interest-rates/bond-yield-curves
5. Bolder, Johnson, Metzler, "An Empirical Analysis of the Canadian Term Structure of Zero-Coupon Interest Rates," BoC WP 2004-48 - https://doi.org/10.34989/swp-2004-48
6. BIS Papers 25, "Zero-coupon yield curves: technical documentation" (BoC MLES note) - https://www.bis.org/publ/bppdf/bispap25.htm
7. US Treasury, "Treasury Yield Curve Methodology" (rev. 2025-02-18) - https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/treasury-yield-curve-methodology
8. US Treasury, "Yield Curve Methodology Change Information Sheet" (HS to MC 2021-12-06)
9. Hagan and West, "Interpolation Methods for Curve Construction," Applied Mathematical Finance 13(2) 2006; "Methods for Constructing a Yield Curve," Wilmott May 2008
10. Bank of Canada, "Methodology for calculating CORRA" - https://www.bankofcanada.ca/rates/interest-rates/corra/methodology-calculating-corra
11. CME Group, "Calculating the Dollar Value of a Basis Point" and "How Can You Measure Risk in Treasuries" (DV01 via modified duration)
12. Montreal Exchange, "Yield Curve Spread Canada-US" (DV01-neutral hedge ratio pattern)
13. CFFiM, "Canadian Conventions in Fixed Income Markets" (ACT/365)
14. Statistics Canada tables 10-10-0144 / WDS releaseTime practice (Phase 1 pin: join outputs carry source vintage markers; no StatCan yield inputs in Phase 2)

### Verification Checklist
- [x] Findings are from reputable sources
- [x] Equations are correctly transcribed
- [x] Validation data includes uncertainty
- [x] Practical implications are actionable
- [x] All sources cited
- [x] Research supports phase architecture decisions

## 2026-11-01 - Phase 3 Site: SolidJS static export, charts, manifest lazy fetch, deep links, OG, mobile, provenance, fail-closed UI

Phase 3 builds SolidJS static site on GitHub Pages (no backend): routes index,
curve, inflation, placeholder, methods, verification, breaks; compare overlay
1M/1Y, since-yesterday deltas, `?asof=` via manifest lazy fetch, footer stamp
(date plus SHA plus checks), phone-readable, static OG image, funding bundle
(CORRA vs target, BoC dates, policy history, DGS2, auction link-outs, QT level),
`verify.json`-driven pages.

### Key Findings
| Finding | Source | Confidence | Application |
|---------|--------|------------|-------------|
| Vite static deploy on Pages needs `base: '/<repo>/'` (or `'/'` for user site/custom domain); assets resolve via `import.meta.env.BASE_URL`; Router needs matching `base={...}`; add `.nojekyll` so underscore-prefixed build assets (`_build`, `_server`) are served | Vite static-deploy guide; solid-gh-pages README; Simon Willison TIL; SolidStart GitHub Pages articles | High | `web/vite.config.ts` sets `base` from repo name; `Router base={import.meta.env.BASE_URL}`; CI writes `dist/.nojekyll` |
| SolidStart static preset (`preset: "static"` plus Nitro `prerender: { crawlLinks: true }` or explicit `routes`) emits `.output/public` for Pages; plain `vite-plugin-solid` SPA (no Start) also works and is simpler when all data is client-fetched JSON; either way no runtime API | SolidStart route-prerender docs; SolidStart GH-Pages DEV articles; SolidStart discussion #1398 (`ssr:false, server.static:true`) | High | Prefer plain Solid SPA + `@solidjs/router` unless SSR/prerender SEO is needed; prerender the 7 static routes, fetch snapshots client-side |
| Pages has no rewrites: deep path `/curve` 404s on hard load; standard fix is `404.html` + `index.html` redirect shim (rafgraph `spa-github-pages`: encode path+query into `?/...`, restore via `history.replaceState`); alternative is query-only routing (`?asof=`, `?/curve`) which needs no shim | rafgraph spa-github-pages; StackOverflow Blazor/GH-Pages 404; quick-vite gh-pages-spa (Solid `Router base={routeBase()}` + `PagesReRouter`); Bombie lesson post | High | Ship `404.html` shim verbatim (with `pathSegmentsToKeep=1`); keep all deep state in query (`?asof=YYYY-MM-DD`) so share links survive the shim round-trip |
| `?asof=` works without backend: parse `URLSearchParams` on boot, validate against manifest date list, `fetch` that date's snapshot JSON, `history.replaceState` on change; never trust raw param (fail closed to latest + notice) | Solid router `useSearchParams`/location docs; qflow dashboard manifest pattern (SPA fetches `manifest.json`, lazy-loads per-run files) | High | `?asof=` loader: fetch `manifest.json` first, whitelist date, then lazy-fetch `snapshots/<date>/...json`; invalid date renders unknown-date banner |
| Manifest lazy-fetch pattern (no runtime API): one small `manifest.json` (dates, sha, checks) loaded eagerly with `cache: no-store`; per-page JSON (`curve.json`, `verify.json`) lazy-loaded per route via Solid `lazy()` + `createResource` inside `Suspense`; keeps first paint small | qflow `gh-pages/data/manifest.json` pattern; Solid `lazy` + `createResource` docs; pixi-solid asset-manifest `createResource` example | High | `public/data/manifest.json` lists snapshot dates + file names + sha256; each route `createResource`s only its files; `Suspense` skeleton per page |
| uPlot beats lightweight-charts for this project: ~47.9 KB min (~21.3 KB gzip), zero deps, MIT, cold-renders 166k points in ~34 ms with best cursor/zoom perf; lightweight-charts standalone is ~60.7 KB gzip, prettier financial defaults (candles, price lines) but heavier, TradingView attribution required, worse at 100k points (448 ms vs 33 ms in ORTEX bench) | uPlot bench table + npm page; Bundlephobia uPlot; Lightweight-Charts docs + build variants; ORTEX 2026-09 bench (payload + render) | High | Choose uPlot for curve/inflation/breaks time series + compare overlay; wrap in one `TimeChart` component; revisit lightweight-charts only if candle/price-line UX is demanded |
| Static OG image: social scrapers do not run JS, so per-date dynamic OG is impossible on Pages; correct pattern is one committed `public/og.png` (1200x630 PNG, not SVG) + absolute `og:image`/`twitter:card` meta; generate at build via script (Playwright screenshot or Satori+Resvg HTML-to-PNG), regenerate when card copy changes | metaharness `scripts/make-og.mjs` (Playwright 1200x630 to `public/og.png`); og-images-generator (Satori HTML-to-PNG, no headless browser); nself OG docs (static fallback `og-default.png`) | High | Commit `web/public/og.png` 1200x630; `scripts/make-og.mjs` renders branded card (title, latest 10Y/2s10s, as-of date); meta tags use absolute Pages URL |
| Phone 360 px layout: single-column stack, chart full-bleed with min touch target 44 px, tables collapse to key-value or horizontal scroll, badge collapses to dot + expands on tap; freshness/provenance must never scroll out of view for deep-link arrivals | Geo-dashboard freshness-badge guide (mobile collapse rule); vaultwatch responsive commit (off-canvas sidebar, auto-fit grids) | Medium | CSS: `min-width:360px` gate, `@media (max-width:640px)` single column, uPlot resize via `ResizeObserver`, tables get `overflow-x:auto` + sticky first column |
| Provenance badge pattern: compute age from source timestamp (snapshot `as_of`), never build time; fetch manifest with `no-cache`; show relative age + absolute UTC + commit SHA link; three states ok/warn/critical with words not color alone; unknown age renders as failure ("data age unknown") | Geo-dashboard freshness badge post (`mountFreshnessBadge`, thresholds, `aria-label`); Helios freshness-anchor (commit SHA link + subject + relative time); gravitonkv reproducibility-linking commit | High | Footer stamp: `as of YYYY-MM-DD · manifest sha <short> (link) · verify <pass/fail> (link)` each linking to GitHub blob/commit; stale thresholds (warn >2 biz days, critical >5) from calendar |
| Fail-closed UI: missing snapshot, failed fetch, or stale manifest renders blocking banner + disables deltas/charts (show `NA` with reason), never silently falls back to cached or interpolated data; `verify.json` status gates each page (fail = red banner naming the check) | Geo-dashboard "unknown age is failure" rule; vaultwatch `SourceBadge` (live/fallback/cache/seed) pattern; ntm TUI stale-badge commit; Phase 1/2 fail-closed pipeline rules | High | `verify.json` drives banner component: `status!=pass` blocks derived displays; fetch `catch` renders error card with retry + link to latest good `?asof=`; no forward-fill assertion mirrored client-side |

### Relevant Equations
| Equation | Description | Variables |
|----------|-------------|-------------|
| `age_h = (now_utc - source_asof_utc) / 3600` | Data age from source timestamp (provenance badge) | now_utc browser clock, source_asof_utc manifest `as_of` midnight UTC |
| `state = ok if age<=warn; warn if warn<age<=crit; critical otherwise` | Badge state thresholds in business days | warn 2 biz days, crit 5 biz days (calendar-aware) |
| `url = BASE + 'data/' + date + '/' + file` | Snapshot URL join (respects Pages subpath) | BASE `import.meta.env.BASE_URL`, date `YYYY-MM-DD`, file e.g. `curve.json` |
| `delta_1d = y(asof) - y(prev_bizday)` (bp = *100) | Since-yesterday delta using joint CA-US calendar predecessor | y yield in percent, predecessor from calendar leg flags |
| `1200 x 630 PNG` | OG image canvas size | Fixed social-card geometry; keep text in central safe zone |
| `budget: uPlot ~21 KB gzip vs LW ~61 KB gzip` | Chart payload budget comparison | gzip bytes of the chart chunk alone |

### Validation Data
| Benchmark | Value | Source | Uncertainty |
|-----------|-------|--------|-------------|
| uPlot minified / gzip | 47.9 KB min bench; 49.6 KB min / 21.3 KB gzip (Bundlephobia) | uPlot bench table; bundlephobia uplot | Version 1.6.x; tree-shaken single-series is smaller |
| uPlot cold render 166,650 pts | 34 ms done (51 js / 2 rend / 1 paint / 34 sys) | uPlot bench 2023-03-11 (Ryzen 7 PRO 5850U, Chrome 113) | Hardware-specific; relative ordering is the durable claim |
| Lightweight-Charts standalone prod gzip | 60.7 KB | ORTEX bench 2026-09-05 (esbuild + gzip, same harness) | v5.2.1; per-entry-point, not tree-shaken app total |
| 100k-bar render: ORTEX 33 ms / LW 448 ms / Highcharts 202 ms | See row | ORTEX bench 2026-09-08 headless Chromium | Synthetic bars; time-series lines favor uPlot further |
| Vite Pages subpath rule | `base: '/<repo>/'` + `.nojekyll` + `dist/` artifact | Vite static-deploy guide; Willison TIL; SolidStart Pages posts | Custom-domain case uses `'/'` instead |
| OG geometry | 1200x630 PNG under `public/` served at site root | make-og.mjs; og-images-generator; nself docs | Scrapers ignore SVG and JS-rendered meta |
| Mobile floor | 360 px min width; 44 px touch targets | Geo-dashboard + vaultwatch responsive notes | Device lab spot-check, not a standard |

### Practical Implications
- Scaffold `web/` as plain Vite + `vite-plugin-solid` + `@solidjs/router` SPA (no Start/SSR): `base` from repo name, `Router base={import.meta.env.BASE_URL}`, `lazy()` per route (index, curve, inflation, methods, verification, breaks), `404.html` shim copied from rafgraph with `pathSegmentsToKeep=1`.
- Data layer: `public/data/manifest.json` (dates, sha256, verify status) fetched `no-store` on boot; `createResource(asof, fetchSnapshot)` per page with `Suspense` skeletons; `?asof=` validated against manifest, invalid yields unknown-date banner pinned to latest good.
- Charts: single `TimeChart` wrapper around uPlot (Canvas 2D, `ResizeObserver` sizing, cursor sync for compare overlay, 1M/1Y window buttons as x-range presets, not refetches); no candles in v1 so lightweight-charts attribution/weight is unjustified.
- Funding bundle page reads `verify.json` plus CORRA/target series plus BoC date/policy-history JSON plus DGS2 plus auction URLs plus QT level; every external link-out labeled with source plus retrieval date; QT level carries `high_approx` disclosure.
- Footer/provenance component on every route: `as of <date> UTC · pipeline <short-sha> (link) · verify <pass/fail> (link)` plus freshness badge (ok/warn/critical words plus absolute timestamp plus `aria-label`); stale or failed verify blocks deltas and charts with named reasons.
- OG: `scripts/make-og.mjs` (Playwright or Satori) writes `web/public/og.png` 1200x630; `index.html` meta uses absolute `https://<user>.github.io/<repo>/og.png`; tester spot-checks with a scraper-debugger and a 360 px device pass.
- Tester inputs from this research: shim round-trip (`/curve?asof=X` hard-load restores route plus date), invalid `?asof=` banner, missing-file 404 card, offline-manifest error, uPlot 1M/1Y plus overlay plus delta correctness, footer SHA/date/checks match `manifest.json` plus `verify.json`, OG PNG MIME plus dimensions, 360 px no-horizontal-scroll pass.

### Citations
1. Vite, "Deploying a Static Site / GitHub Pages" - https://vite.dev/guide/static-deploy
2. SolidStart, "Route pre-rendering" - https://docs.solidjs.com/solid-start/v2/building-your-application/route-prerendering
3. TangoYankee/solid-gh-pages - https://github.com/TangoYankee/solid-gh-pages
4. quick-vite/gh-pages-spa (Solid `routeBase` plus `PagesReRouter`) - https://github.com/quick-vite/gh-pages-spa
5. rafgraph/spa-github-pages (404 shim) - https://github.com/rafgraph/spa-github-pages
6. Solid Router, "Lazy loading" / "Routing and navigation" / "`createResource`/`createAsync`" - https://docs.solidjs.com/solid-router/advanced-concepts/lazy-loading
7. Solid, "`createResource`" reference - https://docs.solidjs.com/reference/basic-reactivity/create-resource.md
8. uPlot bench plus npm plus Bundlephobia - https://leeoniya.github.io/uPlot/ ; https://github.com/leeoniya/uPlot/blob/master/bench/table.md ; https://bundlephobia.com/package/uplot
9. TradingView Lightweight Charts docs (build variants, attribution) - https://tradingview.github.io/lightweight-charts/docs
10. ORTEX Charts performance (payload plus render bench, 2026-09) - https://ortexcharts.com/docs/performance
11. qflow dashboard README (manifest plus lazy-run JSON on gh-pages) - https://github.com/buttered-spuds/qflow/blob/main/dashboard/README.md
12. Geo-dashboard, "Publishing a Data Freshness Badge" - https://www.geo-dashboard.com/data-refresh-automation-pipelines/pipeline-observability-and-alerting/publishing-a-data-freshness-badge-on-a-geo-dashboard/
13. metaharness `apps/web-ui/scripts/make-og.mjs` (Playwright 1200x630 to `public/og.png`)
14. juliancataldo/og-images-generator (Satori HTML-to-PNG, no headless browser) - https://github.com/juliancataldo/og-images-generator
15. nself OG/social-cards docs (static `og-default.png` fallback) - https://nself.org/docs/guides/og-cards
16. Helios PR #1194 (freshness anchor plus last-result footer); gravitonkv 89e81e9 (reproducibility linking); ntm 02f382a (stale badge); vaultwatch Badge/SourceBadge plus responsive overhaul

### Verification Checklist
- [x] Findings are from reputable sources
- [x] Equations are correctly transcribed
- [x] Validation data includes uncertainty
- [x] Practical implications are actionable
- [x] All sources cited
- [x] Research supports phase architecture decisions

## 2026-11-01 - Phase 4 CPI engine: trim, median, SA reuse, weights, GST break, vintages

Phase 4 builds: ingest StatCan CPI component weights plus SA plus NSA bulk
(0004, 0006, 0256, 0259, 0007), hash downloads to distinguish upstream revision
from local arithmetic error, compute CPI-trim plus CPI-median under two SA
variants (chosen: reuse StatCan SA as canonical), trim rank 1M remove 20pct top
plus bottom by weight then renormalize, median weighted median same
distribution, validate 10y versus published with winner MAE plus residual table
every month over 0.1pp explained, decompositions (shelter, food, energy, goods
ex food and energy, services ex shelter), error table with headline plus
experimental label. Decision: reuse StatCan SA, do not refit X-13 in v1.

### Key Findings
| Finding | Source | Confidence | Application |
|---------|--------|------------|-------------|
| Official trim/median use fixed 55-component disaggregation (exhaustive, mutually exclusive, weights sum to 100, national only, history from Jan 1989). Full Table A1 list is Meat (01) through Tobacco (55); starred series partly constructed by BoC (e.g. leasing of passenger vehicles, other owned accommodation). Count changed 54 to 55 in 2016 methods update | StatCan 2301_D64_T9_V3 methodology plus Table A1 appendix | High | Engine hard-codes 55-item Table A1 map; assert 55 rows every month; fail closed on count drift |
| Input pipeline is tax-adjusted then SA: 55 NSA component indexes first adjusted to remove indirect-tax changes, then SA. Only 44 of 55 series are SA at introduction (rest have no identifiable seasonality); SA set is re-evaluated yearly so the SA member list can change. Each SA series adjusted separately | StatCan 2301_D64_T9_V3 Revisions and SA section | High | Two-variant design: Variant A canonical reuses StatCan SA; Variant B diagnostic bounds SA-membership effect; log which of the 55 were SA each vintage |
| Trim is weighted monthly distribution, not annual: sort 55 SA tax-adjusted m/m rates ascending with basket-link-month weights, exclude bottom 20pct plus top 20pct of cumulative weight (40pct total removed). Boundary rule: first component straddling 20pct (or 80pct) contributes only the partial weight needed. Excluded set varies monthly | StatCan 2301_D64_T9_V3 Steps 1-3, Notes 4-5 | High | Implement cumulative-weight rank with partial-weight split; store excluded names plus kept weight (must equal 60pct) per month |
| Median is same distribution 50th percentile: first component where cumulative weight exceeds 50pct; median component varies monthly. Equivalent to trimming everything except the midpoint | StatCan 2301_D64_T9_V3 median Steps 1-3, Note 6 | High | Implement single-pass sort shared with trim; record median component identity per month for residual forensics |
| Annual rate is compounding, not mean: y/y equals product of (1 plus m/m over 100) minus 1 times 100 over 12 months ending in t. Since Jan 2024 release, published y/y is computed from trim/median indexes rounded to one decimal (coherence fix) | StatCan 2301_D64_T9_V3 Step 4 formulas; Daily Jan-2024 change note | High | Engine must compound 12 monthly trimmed/medians; then round-trip through 1-decimal index replica for published comparison; never average the 12 m/m |
| Revision policy changed with Jan 2026 release: trim/median now revised 3y back each January plus 1m in all other months (aligns with SA table 18-10-0006-01 and international practice). Prior rule was 7y every release. SA table itself revises prior month monthly plus 3y each January; models revisited as needed | Daily Jan-2026 Note to readers; 2301_D64_T9_V3 Note 9 as amended 2026-02-17 | High | Hash every bulk zip plus record WDS releaseTime; diff 0256 vintage to classify over 0.1pp moves as upstream revision vs arithmetic bug; keep 84-month backfill only for pre-2026 history |
| Real-time vintage table 18-10-0259-01 exists precisely to hold historical release vintages (ex CANSIM 326-8023); updated with lag (e.g. Mar 2 for Jan release). 0256 holds current-vintage levels plus y/y; 0259 is the audit trail | StatCan table catalogue; Daily Jan-2026 real-time note | High | Validator joins replica to 0259 vintage matching release date, not just 0256 current; pin vintage date in snapshot |
| Basket weight vintage must be pinned at link-month prices: 2024-expenditure basket introduced with May 2025 release (June 24 2025 Daily). Weights at basket-reference prices price-updated to link-month hybrid expenditures. 2024 shares: shelter 29.12pct, MIC 5.65pct (plus 45bp), rent 7.19pct (plus 33bp), food 16.72pct, transport 17.29pct | StatCan 62F0014M2025003 plus tables 1-2; Daily May-2025 | High | Snapshot stores basket vintage (2024/link month) plus 0007 sha; apply weight vintage active at observation month when backfilling 10y |
| Temporary GST/HST break Dec 14 2024 to Feb 15 2025 covered about 10pct of basket at final tax-inclusive prices; affected restaurant meals, alcohol, toys/games/hobby, children clothing. Creates base-year y/y distortions through Mar 2026 (e.g. restaurant meals plus 12.3pct y/y Jan 2026, plus 7.8pct Feb then plus 3.2pct Mar as break falls out; gasoline minus 16.7pct y/y Jan 2026 is separate energy story) | Daily Jan-2026 GST break box; Daily Mar-2026 base-effect note; Daily Dec-2024 | High | Decompositions must flag Dec 2024 to Mar 2026 tax window; tax-adjusted core inputs already strip indirect taxes but headline replica must retain them; error table carries experimental label on affected months |
| Prior Phase 1 carryover: 55 components with 43 SA in earlier vintage, and Khan-Morel-Sabourin 2015 enhancement framing (trim about 9bp, median about 37bp, tight MAE about 0.15) remain directionally useful but SA count is now 44 and must be re-asserted per vintage, not hard-coded | docs/research.md Phase 1; Khan et al. 2015 via StatCan doc | Medium | Re-assert SA count from bulk metadata each fetch; do not hard-code 43 or 44 |
| BoC published cross-check anchors: Sep 2026 headline 3.1pct y/y with trim 1.8pct and median 1.9pct; Jan 2026 headline 2.3pct with trim 2.4pct and median 2.5pct; SA m/m plus 0.1pct Jan 2026 | BoC CPI page; Daily Jan-2026; TD Sep-2026 summary | High | Golden tests pin Sep 2026 plus Jan 2026 plus GST-window months |

### Relevant Equations
| Equation | Description | Variables |
|----------|-------------|-----------|
| `r_i = (I_i,t / I_i,t-1 - 1) * 100` | SA tax-adjusted monthly rate per component | I SA tax-adjusted index, i in 1..55, t month |
| `order r_(1) <= ... <= r_(55); C_k = sum_{j<=k} w_(j)` | Rank by rate carrying basket-link-month weight | w basket weight at link month, C cumulative weight 0-100 |
| `trim_m/m = sum_{i in kept} w'_i * r_i; w'_i = w_i / sum_kept` with kept equals 20 < C <= 80 plus partial splits at 20 and 80 | Trimmed weighted mean, kept weight renormalized to 60pct | Partial split per Notes 4-5: only the needed slice of straddling component counts |
| `median_m/m = r_(k*) where k* = first k with C_k > 50` | Weighted median monthly rate | Same sorted distribution as trim |
| `core_y/y_t = (prod_{s=t-11..t} (1 + core_m/m_s / 100) - 1) * 100` | Annual core by compounding 12 monthly cores | core in {trim, median}; never arithmetic mean |
| `core_y/y_pub = (J_t / J_t-12 - 1) * 100` where J rounded to 1 decimal | Published y/y since Jan 2024 (coherence rule) | J trim/median index level rounded to 1dp |
| `contrib_c = w_c * r_c / 100` (pp) and `share = contrib / headline_m/m` | Decomposition contribution in percentage points | w link-month weight pct, r component m/m pct |
| `resid_t = replica_t - published_vintage_t; MAE = mean(abs(resid))` over 10y | Winner validation metric | Replica vs 0259-vintage published; flag any abs resid over 0.1pp |

### Validation Data
| Benchmark | Value | Source | Uncertainty |
|-----------|-------|--------|-------------|
| 55-component list Table A1 (Meat through Tobacco) | 55 exhaustive items | StatCan 2301_D64_T9_V3 appendix | Fixed disaggregation; reclassification risk pre-1989 |
| SA coverage at introduction | 44 of 55 SA | StatCan methodology doc | Re-evaluated yearly; assert per vintage |
| Basket 2024: shelter 29.12pct, MIC 5.65pct, rent 7.19pct | See row | StatCan 62F0014M2025003 | Rounding; link-month price-updating |
| Trim exclusion | 20pct each tail, 40pct total, 60pct kept | StatCan methodology | Partial-weight boundary rule |
| Median definition | 50th percentile by weight | StatCan methodology | First C_k over 50 rule |
| Revision window current | 3y each Jan plus 1m otherwise; was 7y each release | Daily Jan-2026; methodology Note 9 | Model revisits can extend |
| GST/HST break window | 2024-12-14 to 2025-02-15, about 10pct basket | Daily Jan-2026 box | Final-price tax-inclusive CPI |
| Sep 2026 published | Headline 3.1pct, trim 1.8pct, median 1.9pct | BoC CPI page; TD Economics 2026-10-19 | Revisable core |
| Jan 2026 published | Headline 2.3pct, trim 2.4pct, median 2.5pct, SA m/m plus 0.1pct | Daily Jan-2026 | Revisable core |
| Sep 2026 grocery moderation | Food from stores plus 1.7pct y/y (from plus 2.8pct Aug) | TD Sep-2026 | NSA headline component |
| Real-time table lag example | 0259 updated Mar 2 for Jan release | Daily Jan-2026 | Consult RCT doc for schedule |

### Practical Implications
- Canonical Variant A (shipped): reuse StatCan SA component indexes directly (tax-adjusted plus SA as published); no local X-13. Diagnostic Variant B (internal envelope): same trim/median math on NSA tax-adjusted inputs to bound SA effect; publish A, log B minus A spread; SA-membership changes go to B explanation first.
- Ingest pins: 0004 NSA, 0006 SA, 0256 current core, 0259 vintages, 0007 weights; per snapshot record productId, WDS releaseTime, cube start/end dates, zip URL, sha256 of zip bytes, retrieval UTC, active basket vintage plus link month.
- Hash rule distinguishes revision from bug: if 0256/0259 vintage value moved but zip hash changed, classify as upstream revision; if hash identical but replica differs, classify as arithmetic bug and block build.
- Weight vintage pinning: backfill 10y with period-correct basket vintage (link-month weights active at each month); never apply 2024 weights to the full 10y.
- Compounding guard: implement product formula; add unit test that mean-of-12 fails golden (e.g. Sep 2026) while product passes within 0.05pp before 1-decimal rounding.
- Tax window handling: flag 2024-12 through 2026-03 months experimental in error table; headline replica keeps taxes in, core inputs use tax-adjusted series; decomposition pages carry GST-break footnote with 10pct coverage and affected groups.
- Residual table: every month 10y history, columns replica trim/median, vintage published, resid, winner flag; any abs resid over 0.1pp requires named explanation (revision vintage, weight vintage, rounding, SA-member change, tax window) before pass.
- Decomposition build from 0004/0006 aggregates: shelter, food, energy, goods ex food and energy, services ex shelter; contributions in pp with weights shown; SA headline m/m plus NSA y/y shown side by side with vintage note.

### Citations
1. Statistics Canada, "The Bank of Canada's Preferred Measures of Core Inflation Methodology Document" 2301_D64_T9_V3 (Table A1 55 components, trim/median steps, compounding, 44 SA, revision Note 9 amended 2026-02-17) - https://www.statcan.gc.ca/en/statistical-programs/document/2301_D64_T9_V3
2. Statistics Canada, Daily CPI Jan 2026 (revision policy change to 3y plus 1m, GST break Dec14 2024 to Feb15 2025 about 10pct, Jan 2026 2.3pct headline trim 2.4 median 2.5) - https://www150.statcan.gc.ca/n1/daily-quotidien/260217/dq260217a-eng.htm
3. Statistics Canada, Daily CPI Jan 2024 (trim/median y/y from 1-decimal indexes) - https://www150.statcan.gc.ca/n1/daily-quotidien/240220/dq240220a-eng.htm
4. Statistics Canada, Daily CPI Mar 2026 (GST base-year fallout Mar 2026) - https://www150.statcan.gc.ca/n1/daily-quotidien/260420/dq260420a-eng.htm
5. Statistics Canada, 62F0014M2025003 basket 2024 analysis (shelter 29.12, MIC 5.65, rent 7.19) - https://www150.statcan.gc.ca/n1/pub/62f0014m/62f0014m2025003-eng.htm
6. Statistics Canada, tables 18-10-0004-01, 18-10-0006-01, 18-10-0256-01, 18-10-0259-01, 18-10-0007-01 catalogue pages
7. Bank of Canada, CPI page (Sep 2026 3.1 headline, 1.8 trim, 1.9 median back to 2015 history) - https://www.bankofcanada.ca/rates/price-indexes/cpi/
8. Khan, Morel, Sabourin 2015 Discussion Paper 2015-12 and 2013 Working Paper 2013-35 (selection basis, factor model for common) via StatCan doc references
9. TD Economics, Canadian CPI Sep 2026 2026-10-19 (benign core, grocery 1.7pct)

### Verification Checklist
- [x] Findings are from reputable sources
- [x] Equations are correctly transcribed
- [x] Validation data includes uncertainty
- [x] Practical implications are actionable
- [x] All sources cited
- [x] Research supports phase architecture decisions

## 2026-11-01 - Phase 5 polish: breaks automation, verification page, methods assumptions

Phase 5 polishes: breaks page driven by a benchmark-switch log with a
15 bp day-over-day fail rule, holiday-thinned calendars, and revision
diffs; verification page driven by verify.json with blocking fail-closed
behaviour and an explicit tolerance plus method plus SHA line; methods
page stating every v1 assumption and limit with attribution and no
forecasts. Live state at research time: curve live 2026-10-30, verify 22
of 22 pass (V16/V18 spreads plus backtest missing with FRED degraded
without key, V19 to V22 skipped with CPI degraded), site 200, routes
index plus curve plus funding plus inflation plus placeholder plus
methods plus verification plus breaks, StalenessBanner plus FooterStamp
with real counts, build-data sha verify.

### Key Findings
| Finding | Source | Confidence | Application |
|---------|------------|------------|-------------|
| Benchmark-switch log is authoritative from bench_CDN effective dates: 2Y 2028-11-01 3.00 percent eff. 2026-10-23, 3Y 2029-09-01 3.50 percent eff. 2026-10-23, 5Y 2031-09-01 3.00 percent eff. 2026-09-10, 7Y 2033-06-01 2.75 percent eff. 2026-09-10, 10Y 2036-06-01 3.25 percent eff. 2026-06-23, Long 2057-12-01 3.50 percent eff. 2026-03-06; switch can move the printed yield with no market move | BoC selected bond yields plus Notes on Canadian bond yields plus bench_CDN.pdf (fetched 2026-11-01) | High | Breaks page consumes a switch-log JSON derived from bench_CDN; every 2s10s slope chart annotates switch dates; 5-day post-switch window flagged never spliced |
| Breaks DoD rule for polish: flag any absolute day-over-day benchmark yield move at or above 15 bp with no switch-log entry on that date as a break entry requiring explanation; below 15 bp is noise, at or above with a switch entry is explained rotation | Project DoD (orchestrator brief); BoC switch note that day-to-day change can reflect switch | High | Backend or page logic: `abs(y_t minus y_{t-1}) times 100 at or above 15 and no switch equals fail or break-row`; tester pins one synthetic 20 bp no-switch fail case and one switch-explained pass case |
| Holiday-thinned handling follows joint calendar: CA leg BoC Schedule I open days, US leg SIFMA bond recommendations (recommendations only, firms decide); one-sided holidays drop from the join with no forward fill; examples Columbus Day 2026-10-12 full SIFMA close with NYSE open, Veterans Day 2026-11-11 full close | SIFMA holiday schedule plus 2026-09-29 Columbus Day and 2026-10-28 Veterans Day recommendations; Phase 1 calendar finding; movertape 2026-10-26 cross-check | High | Breaks page marks holiday-thinned sessions (early close 14:00 ET, Columbus and Veterans full closes); spreads require common joint business days; verify V16 asserts no forward fill |
| Revision diffs distinguish upstream revision from local bug: StatCan trim and median revise (3y each January plus 1m otherwise), FRED DGS never revised, BoC yields unrevised prints with issue rotation; hash equality on bulk zip separates bug (same hash, replica differs) from revision (hash changed) | StatCan Daily Jan-2026 plus 2301_D64_T9_V3 Note 9; FRED DGS docs; Phase 4 bulk-hash rule | High | Breaks and inflation pages show revision diff (vintage value versus current 0256) with zip sha12; verify V22 recomputes MAE and flag match while passing either way |
| Verification page must be verify.json driven: show `passed`, `passed_count of checks.length`, `tolerance_bp plus tolerance_unit`, per-check id plus state plus detail with units, plus `snapshot_sha256`; build-data already refuses to publish on manifest digest mismatch, missing manifest or verify, bad JSON, snapshot_date mismatch, or `verify.snapshot_sha256` mismatch | Live snapshots/2026-10-30/verify.json (22 checks, tolerance 1.0 basis_points, sha eae33396); web/scripts/build-data.mjs Phase 1 plus Phase 2 gates | High | VerificationPage reads only verify.json fields; blocking banner when `passed` false or fetch error; demo a known-bad fixture (tampered yield) that fails V13 or V11 to prove the gate can fail |
| Fail-closed demo pattern: a check that cannot fail is a comment; proof-carrying display marks only claim-checked numbers verified and blocks derived displays on failure with named reasons, stale never silent | World Bank PCN protocol; Kymira verification and anchoring; Lotus fail-closed docs; Phase 3 fail-closed UI rule | Medium | Add a methods plus verification note plus tester case: feed known-bad snapshot, confirm red FAIL banner and disabled deltas and charts with NA plus reason |
| Methods page must state every v1 limit in plain language: par approx not zero, NSS dropped, carry 1M on unchanged curve ex coupon and ex funding, spreads same-day plus lagged-1d with close-time disclosure, backtest illustrative fixed rule with zero costs, CPI experimental reuse-SA with MAE gate that flags but never blocks, attribution BoC plus OGL plus StatCan plus FRED, no forecasts | Phase 2 par-approx-logdiscount-PCHIP-v1 plus D09 to D14 plus D20 to D24; Treasury MC note (why v1 stays par approx); BoC MLES note (why zero curve deferred) | High | Methods page ledger cards with one sentence per limit plus method id, tolerance, and sha line; tech-lead owns wording, tester asserts each sentence present |
| Close-time disclosure anchors spreads: BoC benchmark mid-market closes (CanDeal DNA), H.15 about 16:15 ET with FRED T+1 morning ingest, CORRA value date T published T+1 about 09:00 ET; same-day spread compares different close vintages so lagged-1d spread is the like-for-like comparator | BoC selected yields sources line; FRED H.15 timing; BoC CORRA methodology | High | Methods spreads card states both legs plus times; snapshot stores `ca_us_same_day` and `ca_us_lagged_1d` join keys |
| Attribution and licence: BoC Valet data under BoC Terms of Use, StatCan bulk under Statistics Canada Open Licence, FRED H.15 via FRED API, SIFMA schedule by recommendation; footer links to source plus retrieval date | BoC Terms of Use; StatCan Open Licence; SIFMA recommendation disclaimer; FRED API terms | High | Methods attribution card plus footer source links; no forecast language anywhere (past moves not forecasts) |

### Relevant Equations
| Equation | Description | Variables |
|----------|-------------|-----------|
| `dod_bp = (y_t minus y_{t-1}) times 100` | Day-over-day benchmark move in bp | y in percent, t joint business days |
| `break = (abs(dod_bp) at or above 15) and (no switch-log entry on t)` | Break-entry rule for polish | 15 bp threshold, switch log from bench_CDN effective dates |
| `age_biz = joint-biz-days(asof, now)` | Staleness in business days for banner | asof snapshot date, calendar legs |
| `state = pass if verify.passed else fail; block = not passed or fetch-error or stale-critical` | Verify gating for derived displays | verify.json passed boolean, banner state |
| `carry_1M approx y(T) times h plus (y(T minus h_curve) minus y(T))` with h = 1/12, unchanged curve | Simplified carry-roll ex coupon ex funding | y percent decimal, h years, curve frozen at t |
| `core_y/y_t = (prod_{s=t-11..t}(1 plus core_m/m_s / 100) minus 1) times 100` | Annual core by compounding 12 monthlies | core in {trim, median}; never mean of 12 |
| `resid_t = replica_t minus published_vintage_t; MAE = mean(abs(resid))` | CPI validation residual and gate metric | replica versus 0259 vintage, gate 0.10 pp flags but never blocks |
| `sha_publish = sha256(raw snapshot.json bytes); publish iff sha equals manifest plus verify.snapshot_sha256` | Content-hash publish gate | raw bytes, hex digest, manifest plus verify copies |

### Validation Data
| Benchmark | Value | Source | Uncertainty |
|-----------|-------|--------|-------------|
| Current benchmarks eff. dates Oct 2026 | 2Y 2028-11-01 3.00 percent (2026-10-23); 3Y 2029-09-01 3.50 percent (2026-10-23); 10Y 3.87 percent on 2026-10-28 decision day | BoC selected yields page (fetched 2026-11-01) | Daily mid-market close, CanDeal DNA; rotates after last auction |
| BoC policy 2026-10-28 | Plus 25 bp to 2.50 percent; 2Y 3.41 percent, 10Y 3.87 percent that day | BoC FAD press release 2026-10-28; Investing.com recap | Market prints move intraday; page shows closes only |
| Live verify 2026-10-30 | 22 of 22 pass, tolerance 1.0 basis_points, sha eae33396; V16/V18 missing with FRED degraded, V19 to V22 skipped with CPI degraded | snapshots/2026-10-30/verify.json plus build-data.mjs | Degraded legs expected without FRED key and CPI bulk; gate still pass with skip notes |
| SIFMA 2026 closes | Columbus Day 2026-10-12 full close (NYSE open); Veterans Day 2026-11-11 full close; early closes 14:00 ET (Good Friday noon exception) | SIFMA schedule plus 2026-09-29 and 2026-10-28 notices; calendarhours cross-check | Recommendations only; firms decide; settlement times separate |
| CPI Sep 2026 anchor | Headline 3.1 percent, trim 1.8 percent, median 1.9 percent | BoC CPI page; TD 2026-10-19 | Revisable core vintages |
| MAE gate | 0.10 pp over trailing 36 months with 24 minimum; flag but never block | D22 plus Phase 4 validation | Upstream revision moves vintages; hash separates bug from revision |

### Practical Implications
- Breaks page: render switch-log table (issue plus effective date per tenor), slope chart with switch markers and 5-day shaded regime flags, DoD table with 15 bp break column, holiday-thinned badges from joint calendar, and revision-diff panel linking bulk sha12 to 0256 versus 0259 vintage values.
- Verification page: bind every line to verify.json (counts, tolerance plus unit, per-check detail with units, snapshot_sha256 with short plus full copy); on `passed` false or fetch error show blocking red banner naming failed check ids and disable deltas and charts to NA with reasons; add one demonstrable fail fixture (for example 20 bp no-switch tamper) in tests or a methods footnote proving the gate trips.
- Methods page: ship seven ledger cards (curve par-approx plus NSS dropped, carry 1M ex coupon ex funding, spreads same-day plus lagged with close times, backtest fixed rule DV01-neutral gross only, CPI experimental reuse-SA plus MAE flag, verification tolerance plus method plus SHA, attribution plus no-forecasts); each card names the method id and the limit in one sentence.
- Snapshot and pipeline: store `benchmark_switch` flags from bench_CDN dates, `ca_us_same_day` and `ca_us_lagged_1d` spreads with close-time notes, carry with `horizon_years` and ex-coupon flag, CPI bulk sha256 plus sha12 plus link-month vintage, and manifest plus verify digests that build-data re-verifies before publish.
- Tester inputs from this research: switch-date annotation on 2026-10-23 rotation, synthetic 15 bp no-switch fail versus switch-explained pass, Columbus Day thinned-session badge, invalid `?asof=` unknown-date banner, tampered-snapshot verify FAIL with blocked deriveds, methods sentence presence check for par-approx, NSS, carry, spreads, backtest, CPI experimental, attribution, and no-forecasts.

### Citations
1. Bank of Canada, "Selected bond yields" (benchmark definitions, switch note, current issues plus effective dates, CanDeal DNA source) - https://www.bankofcanada.ca/rates/interest-rates/canadian-bonds
2. Bank of Canada, bench_CDN.pdf benchmark issues plus effective dates - https://www.bankofcanada.ca/stats/assets/pdf/bench_CDN.pdf
3. Bank of Canada, "Yield curves for zero-coupon bonds" (MLES weekly Thursday with two-week lag) - https://www.bankofcanada.ca/rates/interest-rates/bond-yield-curves
4. US Treasury, "Treasury Yield Curve Methodology" (monotone convex par since 2021-12-06) - https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/treasury-yield-curve-methodology
5. SIFMA, "Holiday Schedule" (recommendations-only disclaimer) - https://www.sifma.org/resources/guides-playbooks/holiday-schedule
6. SIFMA, Columbus Day 2026-09-29 and Veterans Day 2026-10-28 full-close recommendations
7. Statistics Canada, "The Bank of Canada's Preferred Measures of Core Inflation Methodology Document" 2301_D64_T9_V3 (55 items, SA reuse, trim plus median steps, compounding, revision Note 9)
8. Statistics Canada, Daily CPI Jan-2026 (3y plus 1m revision rule, GST break Dec14 2024 to Feb15 2025) and Daily Jan-2024 (1-decimal coherence)
9. FRED API docs, "Real-Time Periods" and H.15 16:15 ET plus T+1 ingest (DGS never revised)
10. Bank of Canada, "Methodology for calculating CORRA" (T+1 value-date lag, trimmed median, fallback rule)
11. Bank of Canada Terms of Use; Statistics Canada Open Licence; FRED API Terms of Use
12. World Bank PCN, "Proof-Carrying Numbers" (fail-closed verified marks) - https://github.com/worldbank/pcn
13. Kymira, "Verification and anchoring" (reconcile to file totals, prove the check can fail) - https://kymira.ai/features/verification
14. Project live evidence: snapshots/2026-10-30/verify.json (22 of 22, 1.0 basis_points, sha eae33396) and web/scripts/build-data.mjs (manifest plus verify digest gates with stale prune)

### Verification Checklist
- [x] Findings are from reputable sources
- [x] Equations are correctly transcribed
- [x] Validation data includes uncertainty
- [x] Practical implications are actionable
- [x] All sources cited
- [x] Research supports phase architecture decisions

## 2026-11-02 - Terminal speed vs daily dashboard: C++/Rust payoff thresholds

Question: what actually makes Bloomberg/finance terminals fast, and would
C++/Rust help goc-rates-monitor (Python uv pipeline from BoC Valet,
StatCan bulk, FRED to one daily snapshot JSON; SolidJS static site on
GitHub Pages with uPlot; 4 benchmark yields, 55 CPI components, daily
batch after North American close, T+1 lags, no tick data, no order book).

### Key Findings
| Finding | Source | Confidence | Application |
|---------|------------|------------|-------------|
| Terminal latency lives in fanout, not math: Bloomberg Ticker Plant ingests millions of messages per second, B-PIPE serves 35M instruments from 330-plus exchanges via geographically dispersed ticker plants with conflated streaming; speed comes from colo, kernel-bypass networking, delta compression, and local router appliances, not faster yield arithmetic | Bloomberg Ticker Plant story; B-PIPE product page; TechDCoded explainer | High | This project has no streaming leg; nothing here maps to a ticker plant |
| Bloomberg Terminal is a hybrid: proprietary C++ data-processing core plus embedded Chromium/V8/Node.js with TypeScript UI (R+ framework); performance work is GC minimization, custom allocators, portable columns, coalescing, and WebAssembly for compute kernels, not a full-native UI | Paul Williams NDC talk; Bloomberg JS blog (Temporal, TypeScript at scale); R+ job postings | High | Validates current split: Python compute plus JS Canvas charts; WASM only if a kernel proves hot |
| Industry pattern is polyglot by plane: C++ for colocated execution and feed handlers, Rust for new low-latency services (Databento, tickstream cite sub-ms pipeline, PTP timestamps, zero-copy), Java/C# for distribution, Python/NumPy for research, TypeScript for dashboards | LuxAlgo language guide; B2Broker HFT infra guide; Databento; tickstream; LSEG RTSDK flavor table (ETA C++ lowest latency, WebSocket highest) | High | Keep research plus batch in Python, dashboards in TypeScript; native only on a measured microsecond path |
| Chart interaction at this scale is already solved in JS: uPlot cold-renders 166,650 points in about 25 ms at about 100k points per ms, streams 3,600 points at 60 fps at 10 percent CPU; WebGL/WASM only wins past about 100k in-view points or true 60 fps waveform streaming | uPlot bench plus README; ORTEX 2026 bench (100k-bar 33 ms uPlot vs 448 ms lightweight-charts) | High | 10-year daily series (about 2,500 points per line) renders in single-digit ms; no chart rewrite justified |
| Native payoff threshold is quantitative: Python is fine above about 50 ms round-trip budgets or broker-routed bar strategies; Rust/C++ wins when budgets are single-digit ms, message rates exceed about 10k to 100k per second sustained, or backtests loop millions of windows (pandas 140 ms per window to Rust microseconds in one ML-lab case; tickbar 119M ticks per s Rust vs 4.7M pandas resample) | TierZero threshold matrix; 99francs hot-path sidecar case; tickbar bench; Rustify/PyO3 guides | Medium | Project rates are about 4 to 60 new numbers per day; three orders of magnitude below the switch point |
| The correct migration shape when latency does bite is hot-path sidecar, not rewrite: keep Python as financial source of truth, extract one control loop to Rust via PyO3/FFI with fallback; full rewrites cost months and add bug surface | 99francs trading-bot migration; nanobook Python-plus-Rust LOB pattern; PyO3 guides (borrow in, move out, GIL release) | High | If a kernel ever needs it, wrap trim/median or curve math in PyO3; never rewrite fetch, verify, or snapshot logic |

### Relevant Equations
| Equation | Description | Variables |
|----------|-------------|-----------|
| `wall = fetch + compute + render + network` | Daily-batch latency budget decomposition | All terms in seconds or ms per run |
| `speedup = t_python / t_native` | Native payoff estimate (profiled hot path only) | t per window or per message |
| `breakeven = rewrite_cost / (runs * saved_per_run)` | Whether optimization pays back | Cost in engineer time, saving in seconds |
| `points = series * obs_per_series` | Chart load estimate | e.g. 6 series times 2,500 days = 15,000 points |

### Validation Data
| Benchmark | Value | Source | Uncertainty |
|-----------|-------|--------|-------------|
| Bloomberg fanout scale | Millions of msgs per s; 35M instruments; 330-plus venues, 325k terminals | Bloomberg Ticker Plant plus B-PIPE pages | Marketing-rounded; ordering is the durable claim |
| uPlot cold render | 166,650 points in 25 ms; about 100k points per ms thereafter | uPlot bench page | Hardware-specific (desktop Chromium); relative lead over Chart.js/ECharts is durable |
| uPlot stream | 3,600 points at 60 fps, 10 percent CPU, 12.3 MB RAM | uPlot README | Same hardware caveat |
| Python fine threshold | Above about 50 ms round-trip budget | TierZero matrix; LuxAlgo guide | Rule of thumb, not a standard |
| pandas to Rust window | About 140 ms to 1 to 5 ms per window (one lab, 1m/5m bars) | DEV.to lab post | Single-team anecdote; workload-specific |
| tickbar aggregation | 119M ticks per s Rust vs 4.7M pandas resample (about 25x) | tickbar README bench | Synthetic bench; zero-copy path needed for Python 6.7M figure |
| This project daily delta | About 4 yields plus about 55 monthly CPI values; snapshot units KB; 10y chart units 10k points | snapshots/2026-10-30/snapshot.json (4 benchmarks observed) | Exact counts vary with CPI bulk vintage |

### Practical Implications
- No C++ or Rust migration: fetch latency (HTTP seconds plus T+1 source lags of hours) dominates wall time at above 95 percent; compute (curve PCHIP on 4 knots, 55-item trim/median sort, z-scores) is single-digit ms in Python; chart render is single-digit ms in uPlot. Native code would optimize under 1 percent of the budget.
- Latency budget for this project: fetch 10 to 300 s (Valet seconds, FRED seconds, StatCan bulk zip 1.2 MB weights to 161 MB CPI member, plus scheduled wait for 09:00 to 16:30 ET pubs and T+1 lags); compute under 100 ms; snapshot JSON write plus sha256 under 50 ms; site first paint network-bound (manifest plus per-date JSON, each under 100 KB) with uPlot render under 16 ms. Optimize fetch (retry, caching, manifest `no-store`, per-page lazy JSON), not arithmetic.
- Keep the Bloomberg-analogous split the project already has: Python batch core (auditable, fail-closed verify V01 to V23 at 1.0 bp) plus TypeScript/Canvas presentation (uPlot). This mirrors Terminal C++-core plus Chromium-UI without the cost.
- Only revisit native code if scope changes to intraday ticks, order-book replay, or million-row backtests: trigger conditions are sustained above 10k msgs per s, sub-50 ms interaction SLA, or profiled Python kernel above 100 ms per page load. Then use the sidecar pattern (PyO3 around one function, or WASM for a chart kernel), never a rewrite.
- Concrete next actions: profile before any perf work (`cProfile`/`py-spy` on pipeline, DevTools Performance on site); keep `limits.py` caps as the perf guard; log fetch versus compute timings per run so a future regression is attributable.

### Citations
1. Bloomberg, "How Bloomberg handles a massive wave of real-time market data in microseconds" - https://www.bloomberg.com/company/stories/how-bloomberg-handles-a-massive-wave-of-real-time-market-data-in-microseconds
2. Bloomberg, "B-PIPE Real-Time Market Data Feed" - https://professional.bloomberg.com/products/data/enterprise-catalog/real-time-data-feed
3. Paul Williams, "Developing the Bloomberg Terminal: Local performance and measurement techniques" (NDC) - https://www.youtube.com/watch?v=uqehwCWKVVw
4. Bloomberg JS Blog, "Temporal: The 9-Year Journey" and "10 Insights from Adopting TypeScript at Scale" - https://bloomberg.github.io/js-blog/post/temporal
5. LSEG, "Real-Time Market Data APIs and Distribution" (RTSDK flavor/latency table) - https://developers.lseg.com/en/use-cases-catalog/real-time
6. Databento (Rust, PTP timestamps, 590 us internet median) - https://databento.com
7. tickstream (Rust pipeline, sub-ms ingest-to-egress) - https://tick-stream.xyz
8. LuxAlgo, "Best Programming Languages for Algorithmic Trading" - https://www.luxalgo.com/blog/best-programming-languages-for-algorithmic-trading/
9. B2Broker, "High-Frequency Trading Infrastructure: Technical Guideline" - https://b2broker.com/news/high-frequency-trading-infrastructure/
10. TierZero, "Python vs Rust for Crypto HFT Bots: Where Python Breaks Down" (50 ms threshold matrix) - https://tierzero.dev/blog/python-vs-rust-hft-bot-crypto-performance
11. 99francs, "Python to Rust Trading Bot Migration: Latency Case Study" (hot-path sidecar) - https://www.99francs.agency/blog/python-to-rust-trading-bot-migration
12. gregorian-09/tickbar (119M ticks per s Rust vs 4.7M pandas) - https://github.com/gregorian-09/tickbar
13. uPlot bench plus README (166,650 points in 25 ms; streaming figures) - https://leeoniya.github.io/uPlot
14. ORTEX Charts performance bench (uPlot 33 ms vs lightweight-charts 448 ms per 100k bars) - https://ortexcharts.com/docs/performance

### Verification Checklist
- [x] Findings are from reputable sources
- [x] Equations are correctly transcribed
- [x] Validation data includes uncertainty
- [x] Practical implications are actionable
- [x] All sources cited
- [x] Research supports phase architecture decisions

## 2026-11-05 - Backfill depth: Valet, FRED, StatCan bulk, long window caps and analysis conventions

Question: how far back can the joint Canada plus US daily history and the CPI month history
actually go, which upstream and local caps bound an extension of the Phase 7 backfill, what is
standard practice for multi year rate analysis (percentiles, regime shading, rolling returns,
drawdown, inversion frequency), and what does the static artifact weigh at 5, 10 and 20 years.
All source probes below were live on 2026-11-05.

### Key Findings
| Finding | Source | Confidence | Application |
|---------|--------|------------|-------------|
| Valet group `bond_yields_benchmark` starts 2001-01-02: windows 1900-01-01..1990-12-31 and 1991-01-01..1994-12-31 return zero observations, the 1995-01-01..2004-12-31 window returns its first row at 2001-01-02, and the single series `BD.CDN.10YR.DQ.YLD` for 1950-01-01..2000-12-31 is empty | Live Valet group and series probes | High | Hard ceiling for joint Canada plus US history is about 26 years, never deeper without a different Canadian source |
| One unbounded group request (`start_date=1950-01-01&end_date=2026-11-05`) returns 6,461 observations, 3,874,616 bytes, 978 ms, first 2001-01-02, last 2026-11-03 | Live Valet fetch | High | Fits local `MAX_OBSERVATIONS` 10,000 and `MAX_RESPONSE_BYTES` 10 MB with 2.6x headroom, no pagination exists and none is needed |
| Valet publishes no numeric request limit; the how-to asks callers to start slow during peak times, retry with back-off, and cache daily data; no registration or key | BoC Valet API how-to, section Request limits | High | `BaseClient` 3 attempts with 0.5/1/2 s back-off and 15 s timeout is already within the guidance |
| FRED `series/observations` accepts `limit` 1 to 100000 (default 100000) plus `offset` pagination; rate limit is 120 requests per minute per key, over which returns 429 with risk of temporary block | FRED API observations doc; FRED API errors doc (429 text) | High | Each DGS series fits in one request; four requests per run is far below the throttle |
| Start dates: DGS2 1976-06-01 (13,136 observations to 2026-10-06), DGS5 1962-01-02, DGS10 1962-01-02, DGS30 1977-02-15 with the series discontinued 2002-02-18 and reintroduced 2006-02-09 | Federal Reserve H.15 Data Download Program review table; FRED DGS30 data page notes | High | US leg is far deeper than the Canadian leg, and the 30-year gap forces a multi-year `spreads_status` of partial or missing on the 30Y tenor |
| Current code bounds: `FRED_LOOKBACK_DAYS` 2190 (about 6 years), FRED and Valet `limit` or `recent_limit` at `MAX_HISTORY_OBS` 2000, CA history trimmed by `_trim_recent(..., MAX_BACKFILL_DAILY_ROWS)` 1250, joint rows capped at 1250 with minimum 250 | `src/goc_rates/backfill.py`, `src/goc_rates/limits.py` | High | Both the 2000 observation cap and the 1250 row cap bind today, upstream fetch already returns full Valet history before trimming |
| StatCan cube starts (WDS `getCubeMetadata`): 18-10-0004-01 1914-01-01 with 2,139 series and 1,154,918 points; 18-10-0006-01 SA 1992-01-01 with 11 series; 18-10-0007-01 weights 1986-01-01 with 5,136 series and 78,014 points; 18-10-0256-01 core 1949-01-01 with 13 series; 18-10-0259-01 vintages 1989-01-01 with 565 series | StatCan WDS live, 2026-11-05 | High | Bulk depth is not the binding constraint for CPI, local caps and weight vintages are |
| Sampled component vectors 41690973, 41690976, 41690978, 41691027 each carry 1,353 monthly points from 1914-01 to 2026-09 | WDS `getDataFromVectorsAndLatestNPeriods` live | High | The 60 month window is a local choice, not a data limit; the shared consecutive intersection can run far longer |
| Trim and median index series in 18-10-0256-01 are labelled `(index, 198901=100)`, so published validation anchors exist only from 1989-01; weight vintages only exist from 1986-01 | WDS cube metadata and dimension member names | High | Any CPI extension beyond 1989 has no published cross-check, and beyond 1986 has no period-correct basket weights |
| WDS service limits: 50 requests per second server wide, 25 per individual IP, and HTTP 409 from midnight to 08:30 EST while tables refresh; WDS is explicitly not meant for large extracts (bulk CSV or SDMX for that) | StatCan WDS user guide | High | Keep the zip bulk path with the local 256 MB member caps, do not switch to per-vector WDS calls for backfill |
| Local CPI caps: `MAX_BACKFILL_CPI_MONTHS` 60, `CPI_INDEX_MONTHS_KEPT` 61, `MAX_CPI_MONTHS` 240 component months, `MAX_BACKFILL_BYTES` 5 MB; shared months must be strictly consecutive or the build fails closed | `limits.py`, `backfill.py` `_cpi_inputs` and `build_cpi_rows` | High | Extending CPI needs cap changes plus a period-correct weight vintage strategy, the consecutive rule stays |
| Web caps: `build-data.mjs` 1250 daily, 60 CPI, 5 MB history; `Chart.tsx` 2000 points per series and 16 series; `DataTable.tsx` 2000 rows; `snapshot.ts` 5 MB per fetched JSON; `phase7-terminal.test.mjs` asserts these constants as drift guards | `web/scripts/build-data.mjs`, `web/src/components/Chart.tsx`, `web/src/components/DataTable.tsx`, `web/src/lib/snapshot.ts` | High | The 2000 point chart cap trips at about 8 years, before any byte cap; cap changes must update the drift tests |
| Measured volume: `history/backfill.json` is 1,308,994 bytes for 1,250 daily rows plus 60 CPI rows, which is about 1,020 bytes per daily row and 249 joint rows per year (first daily row 2021-10-25, asof 2026-10-30) | `history/backfill-manifest.json`, artifact row counts | High | Projections: 10y about 2.55 MB, 20y about 5.08 MB, 26y ceiling about 6.6 MB |
| The full H.15 Treasury constant maturity package (all observations) is a 984.4 KB CSV, and FRED DGS10 full history is about 16,900 daily rows | Fed H.15 Data Download Program review page | Medium | Raw US data volume is trivial, the project's own derived row shape dominates artifact size |
| Standard regime shading convention is NBER recession shading as published by FRED (lighter shading while a recession is ongoing, monthly turning points drawn as daily), with policy cycle markers taken from official decision tables | FRED help page on recession bars; NBER business cycle dating; BoC policy interest rate table (date, target, change, effective day after announcement since 2021) | High | Regime bands for hiking and cutting cycles come from the BoC decision table for the CA leg and NBER bars for the US leg, no invented cycle detection |
| Canonical spread series and inversion practice: FRED publishes T10Y2Y and T10Y3M as first class series, the NY Fed publishes a 10y minus 3m recession probability with `P = Phi(-0.5333 - 0.6330 * spread)`, the Cleveland Fed charts the spread with recession shading; T10Y2Y data begins June 1976 and has had six sustained inversion episodes (1978-80, 1980-82, 1989-90, 2000-01, 2006-07, 2022-24) | FRED T10Y2Y page; NY Fed probability of US recession PDF; Cleveland Fed yield curve page; secondary episode count from eco3min inversion history | High for primary sources, Medium for episode counts | 2s10s inversion frequency should be reported as negative-day share over a stated window, with NBER shading behind it |
| Percentile bands have no single official standard; statistical releases use fixed windows (BoC Canadian bond yields 10-year lookup) or full history with user windowing (FRED), so any band must disclose its window and calendar | BoC 10-year lookup; FRED full history convention | Medium | Recommend a trailing 10-year percentile band (10th, 50th, 90th) as primary with a full-history range as secondary, window label printed on the chart |
| Rolling horizon reporting is standard as basis point change over trailing 1 year (about 250 business days) and 5 years (about 1,250), and FRED encodes this canonically with `chg` and `pch` unit transforms; the repo already uses 60 and 250 day z-windows | FRED API units documentation; Phase 2 slope z research in this file | High | Add `dy_1y_bp` and `dy_5y_bp` derived fields rather than recomputing in the browser |
| Drawdown language belongs to price or total return series; this project stores yields only, so the defensible metric is distance from the trailing window maximum yield in basis points with the window stated | Market convention, no central bank standard found | Medium | Label it `dist_from_peak_yield_bp` with an explicit window, do not call it drawdown without a return series |
| Probable CPI pinning defect: `config/cpi_components.yaml` labels do not match WDS series titles for the pinned vectors, and the artifact's trim year-over-year diverges from published values (see Validation Data) | WDS `getSeriesInfoFromVector` and published anchors, live 2026-11-05 | High for the metadata mismatch, needs code-reviewer confirmation for impact | Resolve and add a label assertion before any CPI window extension, V19 to V22 currently skip when CPI degrades so the gate has not been running |

Updated 2026-11-05 (Phase 8.2): `FRED_LOOKBACK_DAYS` and `VALET_LOOKBACK_DAYS` are
3653 days, `MAX_BACKFILL_DAILY_ROWS`, `MAX_HISTORY_OBS`, and `MAX_HISTORY_DAILY`
are 2750, and the byte caps are unchanged at 5 MiB. The web daily row cap in
`build-data.mjs` reads 2750, while `MAX_CHART_POINTS` and `MAX_TABLE_ROWS` stay
at 2000 by contract.

### Relevant Equations
| Equation | Description | Variables |
|----------|-------------|-----------|
| `rows = 249 * years` | Joint CA plus US daily rows per year (measured 1250 rows over 2021-10-25 to 2026-10-30) | years in calendar years, joint business days only |
| `bytes = rows * 1020 + overhead(about 40000 with 60 CPI rows)` | Artifact size model from the measured manifest | bytes UTF-8 of canonical indent-2 JSON |
| `p_k(t) = quantile(y over trailing W days, k)` with k in {0.10, 0.50, 0.90} | Percentile band, window W disclosed | W about 2500 days for a 10-year band |
| `dy_1y = (y_t - y_{t-250}) * 100`, `dy_5y = (y_t - y_{t-1250}) * 100` | Rolling horizon change in basis points | y in percent, t joint business days |
| `inv_freq = count(s_d < 0) / count(d in window)` | 2s10s inversion frequency | s_d = y_10y - y_2y in bp per day |
| `d_peak = (max(y over W) - y_t) * 100` | Distance from trailing peak yield in bp | positive means current yield is below the window high |
| `P = Phi(-0.5333 - 0.6330 * spread)` | NY Fed (Estrella and Mishrick) recession probability from the 10y minus 3m spread | spread in percentage points, Phi standard normal CDF |
| `z = (s - mu) / sigma` over 60 and 250 days | Slope z already in the project (unchanged) | existing Phase 2 convention |

### Validation Data
| Benchmark | Value | Source | Uncertainty |
|-----------|-------|--------|-------------|
| Valet full history response | 6,461 rows, 3,874,616 bytes, 978 ms, first 2001-01-02, last 2026-11-03 | Live group fetch 2026-11-05 | Grows by one row per business day |
| Valet empty probes | 1900-1990 empty, 1991-1994 empty, 1995-2004 first row 2001-01-02, `BD.CDN.10YR.DQ.YLD` 1950-2000 empty | Live probes | None |
| DGS2 | 1976-06-01 to present, 13,136 observations to 2026-10-06 | Fed H.15 DDP review table | Official series metadata |
| DGS5, DGS10 | 1962-01-02 start | Fed H.15 DDP review table; FRED series metadata | Official series metadata |
| DGS30 | 1977-02-15 start, discontinued 2002-02-18, reintroduced 2006-02-09 | FRED DGS30 data page notes | Gap is about 3 years 11 months |
| FRED throttle | 120 requests per minute per key, 429 on excess | FRED API errors doc | Stated as up to 120 |
| StatCan cubes | 0004 1914-01-01 (2,139 series, 1,154,918 points, release 2026-10-19T08:30); 0006 1992-01-01 (11 series); 0007 1986-01-01 to 2025-01-01 (5,136 series); 0256 1949-01-01 (13 series); 0259 1989-01-01 to 2026-03-01 (565 series) | WDS `getCubeMetadata` live | Cube dates move with table maintenance |
| Component vector depth | 1,353 months from 1914-01 to 2026-09 for vectors 41690973, 41690976, 41690978, 41691027 | WDS `getDataFromVectorsAndLatestNPeriods` | None stated |
| Artifact | 1,308,994 bytes, sha256 `5b4a81d1...`, daily_count 1,250 (2021-10-25 to 2026-10-30), cpi_count 60 (2021-10 to 2026-09) | `history/backfill-manifest.json` plus artifact metadata | Exact by construction |
| Published CPI-trim y/y (vector 108785715) | Sep 2022 5.5, Jan 2026 2.4, Sep 2026 1.8 | WDS live | Current vintage, revisable 3y plus 1m |
| Artifact CPI-trim y/y | Sep 2022 9.996, Jan 2026 4.284, Sep 2026 1.803 | `history/backfill.json` | Matches published only at the last month |
| Config label versus WDS title | `C01 Meat` on 41690973 returns `Canada;All-items`; `C04 Bakery and cereal products` on 41690976 returns `Canada;Meat`; `C10 Rent` on 41690982 returns `Canada;Fresh or frozen chicken`; `trim_index_vector_id` 41691028 returns `Canada;Canned vegetables and other vegetable preparations` | WDS `getSeriesInfoFromVector` live | Metadata is authoritative for vector identity |
| Headline cross-check | Vector 41690973 y/y Jan 2026 2.29 and Sep 2026 3.09 against published headline 2.3 and 3.1 | WDS plus StatCan Daily | Confirms that vector is All-items, not Meat |
| True core vectors | trim index 1481215116 (Jan 2026 level 218.0, y/y 2.44), median index 1481215115 (y/y Sep 2026 1.95), trim y/y 108785715 (2.4 and 1.8) | WDS coordinate lookup on 18100256 | Index base 1989-01 equals 100 |

### Practical Implications
- Recommended maximum window: 10 years (about 2,490 daily rows, about 2.55 MB). Rationale: it matches the BoC standard 10-year lookup window, it fits every 5 MB byte cap with about 45 percent headroom, it needs only cap and drift-test updates, and uPlot renders 4 series times 2,490 points orders of magnitude below its 166k point bench.
- Cap changes needed for 10 years: `MAX_BACKFILL_DAILY_ROWS` to about 2,750, `MAX_HISTORY_OBS` to about 3,000, `FRED_LOOKBACK_DAYS` to about 3,820, `MAX_HISTORY_DAILY` in build-data to about 2,750, `MAX_CHART_POINTS` to about 4,000, `MAX_TABLE_ROWS` to about 3,000, and the drift assertions in `web/tests/phase7-terminal.test.mjs`.
- Do not target 20 years without a size strategy: 5,000 rows is about 5.08 MB and crosses three 5 MB caps (pipeline, build-data, client fetch). Viable strategies are compact row encoding (arrays instead of keyed objects, roughly 3x smaller), splitting a yields-only history from derived slopes and spreads that the client recomputes, or chunking history by window.
- Hard ceiling regardless of strategy: 2001-01-02 from Valet (about 26 years, 6,461 rows). Anything deeper requires a different Canadian source (for example BoC weekly or monthly research series), which is out of scope for this pipeline.
- CPI window: keep 60 months until two issues are resolved, the probable vector pinning mismatch and the period-correct weight vintage rule from Phase 4 (config pins the 2024 basket with link month 2025-05, provisional true, while weights exist only from 1986 and published validation only from 1989). If extended, `MAX_CPI_MONTHS` 240 caps component months at 20 years and published cross-checks stop at 1989.
- US 30-year leg has no prints from 2002-02-18 to 2006-02-09, so a multi-year window must tolerate `spreads_status` of partial or missing on that tenor, and the UI should annotate the gap rather than forward fill (existing no-fill rule stays).
- Analysis panel over the longer window: trailing 10-year percentile band (10th, 50th, 90th) with window label, NBER recession shading behind the US leg, BoC policy decision markers (date, target, change) for the CA leg, rolling 250 and 1,250 day changes in bp, distance from trailing peak yield in bp with window stated, and 2s10s inversion day share over the same stated window.
- Data growth: a 10-year artifact roughly doubles the committed history file, and the artifact is rewritten on each backfill, so keep backfill regeneration infrequent and let daily snapshots carry the small delta; git delta compression mitigates but does not remove the cost.
- Verification items for tester and code-reviewer: run verify with working StatCan access so V19 to V22 actually execute (both recent snapshots show them skipped with CPI degraded), add a label assertion that each config component vector title matches its config label, and pin a golden check that replica trim y/y matches published anchors (Sep 2022 5.5, Jan 2026 2.4, Sep 2026 1.8).

### Citations
1. Bank of Canada, Valet API how-to, section Request limits - https://www.bankofcanada.ca/valet-api-how-to
2. Bank of Canada, live Valet group probes `observations/group/bond_yields_benchmark/json` (2026-11-05)
3. FRED API, series observations parameters (limit 1 to 100000, offset) - https://fred.stlouisfed.org/docs/api/fred/series_observations.html
4. FRED API, errors (429 up to 120 requests per minute) - https://fred.stlouisfed.org/docs/api/fred/errors.html
5. Federal Reserve Board, H.15 Data Download Program review (available-from dates and observation counts) - https://www.federalreserve.gov/datadownload/Review.aspx?rel=H15
6. FRED, DGS30 data page and series notes (1977-02-15 start, 2002 discontinuation, 2006 reintroduction) - https://fred.stlouisfed.org/data/DGS30
7. Statistics Canada, Web Data Service user guide (rate limits, 409 window, getCubeMetadata) - https://www.statcan.gc.ca/en/developers/wds/user-guide
8. Statistics Canada, WDS `getCubeMetadata` for 18100004, 18100006, 18100007, 18100256, 18100259 (live 2026-11-05)
9. Statistics Canada, WDS `getSeriesInfoFromVector` and `getDataFromVectorsAndLatestNPeriods` probes (live 2026-11-05)
10. FRED help, what dates are used for the US recession bars - https://fred.stlouisfed.org/help/data/understanding-the-data/recession-bars
11. NBER, business cycle dating - https://www.nber.org/research/business-cycle-dating
12. FRED, T10Y2Y 10-Year Treasury Constant Maturity Minus 2-Year - https://fred.stlouisfed.org/series/t10y2y
13. Federal Reserve Bank of New York, probability of US recession predicted by Treasury spread (Estrella and Mishrick coefficients) - https://www.newyorkfed.org/medialibrary/media/research/capital_markets/prob_rec.pdf
14. Federal Reserve Bank of Cleveland, yield curve and predicted GDP growth - https://www.clevelandfed.org/indicators-and-data/yield-curve-and-predicted-gdp-growth
15. Bank of Canada, policy interest rate decision table - https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate
16. Bank of Canada, Canadian bond yields 10-year lookup - https://www.bankofcanada.ca/rates/interest-rates/lookup-bond-yields
17. eco3min, 2s10s inversion history since 1976 (secondary source for episode counts) - https://eco3min.fr/en/yield-curve-inversion-history-2s10s-spread
18. Project code: `src/goc_rates/limits.py`, `src/goc_rates/backfill.py`, `src/goc_rates/history.py`, `src/goc_rates/clients/`, `web/scripts/build-data.mjs`, `web/src/components/Chart.tsx`

### Verification Checklist
- [x] Findings are from reputable sources
- [x] Equations are correctly transcribed
- [x] Validation data includes uncertainty
- [x] Practical implications are actionable
- [x] All sources cited
- [x] Research supports phase architecture decisions
- [ ] Open: code-reviewer to confirm the CPI component vector pinning mismatch before any CPI window extension
