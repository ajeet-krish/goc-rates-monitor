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
