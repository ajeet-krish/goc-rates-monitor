# GoC Rates Monitor Research Notes

Last updated: 2026-11-01

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
