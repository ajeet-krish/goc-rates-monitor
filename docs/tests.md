# GoC Test Results

Last updated: 2026-11-02

## 2026-11-02 - Phase 6 V24 V25: Test Report

Phase 6 true bootstrap fixture repin in `tests/test_verify.py`,
`tests/test_breaks.py`, `tests/test_phase5_lows.py`, and
`tests/test_live_snapshot.py` plus `web/tests/phase3-validate.test.mjs`,
`web/tests/phase5-lows.test.mjs`, and `web/tests/phase5-polish.test.mjs`.
Run with `uv run pytest` in `/Users/ajeet/Projects/goc-rates-monitor`,
plus `npm test`, `npm run build`, and `npm run typecheck` in `web`.

| Test | Verdict | Notes |
| ---- | ------- | ----- |
| uv run pytest (236 passed) | PASS | Full pipeline suite, 230 prior plus 6 repinned and new bootstrap pins |
| test_verify passing snapshot passes V01 to V25 | PASS | Bootstrap curve with settlement, 4 instruments, 4 anchors, 25 checks |
| test_verify bootstrap true method shape | PASS | Method true_bootstrap_semiannual_log_discount_v1, is_par_approx false, is_zero true, V24 V25 pass |
| test_verify V13 discount drift fails | PASS | Knot discount plus 0.01 fails V13 stored worst |
| test_breaks V23 plus V24 V25 pass | PASS | Bootstrap method flags, settlement, instruments, anchors pinned |
| test_phase5_lows 25 checks plus bootstrap shape | PASS | 25 checks ending V25, V24 V25 pass |
| test_live full and degraded pass V01 to V25 | PASS | Live bootstrap snapshots already passed, counts updated 23 to 25 |
| uv run ruff check src tests | PASS | All checks passed |
| uv run ruff format src tests | PASS | Two files reformatted, remainder unchanged |
| npm test web (132 passed) | PASS | 20 suites, 0 fail |
| web pins 25 checks ending at V25 | PASS | EXPECTED_VERIFY_IDS length 25, V01 to V25, 24 check reject |
| web pins bootstrap method id | PASS | Curve method true_bootstrap_semiannual_log_discount_v1, five families ending V24 to V25 |
| npm run typecheck | PASS | tsc noEmit clean |
| npm run build | PASS | vite build clean, all pages emitted |

Coverage summary: 236 passed (pytest) plus 132 passed (web), 0 failed. Happy path covered (bootstrap passing fixtures pass V01 to V25, live full and degraded paths pass V24 V25, mock 25 check report validates). Edge cases covered (4 instrument and anchor agreement, settlement dating, residual ACT over 365 tenors, 24 check truncation). Error conditions covered (V13 discount drift, V23 gate and digest tampers, verify count and id mismatches, provenance vintage and sha drift).

Failure analysis: seven interim failures before the repin, all in stale test expectations, no product defects found. Python fixtures still built the legacy par approx curve so V13, V17, V24, and V25 failed closed on the true bootstrap contract; live bootstrap snapshots already passed V01 to V25. Web validators already expected 25 checks and the bootstrap method, so the three stale test files failed on 23 and V23 and par_approx pins. Fixed by rebuilding fixtures with build_bootstrap_curve_section plus carry and risk from solved zeros and 5Y cashflows, updating counts to 25 and V25, method to true_bootstrap_semiannual_log_discount_v1, is_par_approx false, is_zero true, settlement_date, instruments plus anchors, and families to five ending V24 to V25.

## 2026-11-01 - Phase 5 lows: Test Report

Phase 5 breaks polish lows in `tests/test_phase5_lows.py` (14 tests)
plus `web/tests/phase5-lows.test.mjs` (16 tests). Run with `uv run pytest`
in `/Users/ajeet/Projects/goc-rates-monitor`, plus `npm test`,
`npm run build`, and `npm run typecheck` in `web`.

| Test | Verdict | Notes |
| ---- | ------- | ----- |
| uv run pytest (228 passed) | PASS | Full pipeline suite, 214 prior plus 14 new lows |
| test_classify_gate_history_count_over_cap_rejects | PASS | 2001 rejects with bounded range |
| test_classify_gate_history_count_at_cap_accepts | PASS | 2000 accepts as comparable |
| test_classify_gate_history_count_bool_rejects | PASS | True rejects without coercion |
| test_build_breaks_history_over_cap_rejects | PASS | 2001 obs history rejects on observation cap |
| test_effective_joint_max_date_raises_value_error | PASS | date max raises ValueError not OverflowError |
| test_effective_joint_non_date_rejects | PASS | String date rejects with must be a date |
| test_load_feed_oversize_rejects_with_byte_cap | PASS | 64KB plus 1 byte rejects with byte cap |
| test_load_feed_oversize_precheck_reports_declared_size | PASS | Oversize binary rejects on stat precheck with byte cap |
| test_both_true_gate_is_switch_break_with_null | PASS | Both true is switch_break with null delta and missing quality |
| test_v23_calendar_gap_null_fails | PASS | calendar_gap with null dod fails V23 keeps numeric rule |
| test_v23_9y_record_tenor_fails | PASS | 9Y record tenor fails V23 closure |
| test_v23_provenance_vintage_drift_fails | PASS | Drifted vintage fails provenance match |
| test_v23_provenance_sha_mismatch_fails | PASS | Zeroed sha fails with sha256 detail |
| test_verify_reports_23_checks_at_1bp | PASS | 23 checks V23 last tolerance 1.0 passing |
| npm test web (130 passed) | PASS | 114 prior plus 16 new lows |
| web rejects history_count over 2000 | PASS | 2001 rejects with 2000 cap |
| web accepts history_count at exactly 2000 | PASS | Boundary 2000 passes |
| web rejects boolean history_count | PASS | True rejects without coercion |
| web holds switch_break null when both flags true | PASS | Both true with null passes |
| web rejects calendar_gap that drops its number | PASS | calendar_gap null fails must keep numeric |
| web rejects 9Y record tenor | PASS | 9Y fails tenor set pin |
| web rejects drifted feed vintage | PASS | Wrong vintage fails 2026-11-01 pin |
| web rejects wrong coupon and yield units | PASS | basis_points coupon and count yield fail percent rule |
| web rejects provenance vintage and sha mismatch | PASS | Both fail must match breaks feed lines |
| web pins 23 checks ending at V23 | PASS | EXPECTED_VERIFY_IDS length 23 V01 to V23 |
| web rejects verify with 22 checks | PASS | Truncated report fails exactly 23 rule |
| web covers V23 family with 1.0 bp tolerance | PASS | Fourth family V23 tolerance basis_points |
| web renders unknown fallbacks in footer | PASS | method unknown vintage unknown tolerance unknown plus Unknown date line |
| web states calendar versus business copy | PASS | calendar_days Toronto business_days V12 weekends line |
| npm run build | PASS | vite build clean, all pages emitted |
| npm run typecheck | PASS | tsc noEmit clean |
| uv run ruff check src tests | PASS | All checks passed after line length and unused import fixes |

Coverage summary: 228 passed (pytest) plus 130 passed (web), 0 failed. Happy path covered (both true switch_break null, 2000 boundary, 23 checks pass at 1.0 bp). Edge cases covered (2000 cap boundary, date max overflow path, stat precheck size, boolean history_count, both flags true). Error conditions covered (2001 history, oversize feed, non date joint, calendar_gap null, 9Y tenor, vintage drift, sha mismatch, 22 check report).

Failure analysis: one interim ruff fault (line over 100 chars and two unused imports in the new test file) fixed in test code. Two product gaps closed before green. Web `validateSnapshot` lacked the 2000 history_count upper cap so 2001 passed while Python V23 rejected it; added `MAX_HISTORY_OBS` 2000 and an integer in [0, 2000] guard. `effective_joint_date` could surface `OverflowError` on calendar overflow near date max; wrapped the 16 day scan so overflow and year range both become `ValueError`. `load_switch_feed` read the full file before checking the 64KB cap; added a `stat` size precheck that rejects oversize before `read_bytes`. No other product defects found.

## 2026-11-02 - Phase 4: Test Report

Phase 4 CPI engine suite in `tests/test_cpi_trim_median.py`,
`tests/test_cpi_engine.py`, `tests/test_cpi_bulk.py`,
`tests/test_cpi_golden.py`, and `tests/test_phase4_negatives.py`,
plus `tests/cpi_fixtures.py` shared demo inflation. Existing
`tests/test_verify.py` and `tests/test_live_snapshot.py` extend to 22
checks with the demo inflation attached.
Run with `uv run pytest` in `/Users/ajeet/Projects/goc-rates-monitor`,
plus `npm test`, `npm run build`, and `npm run typecheck` in `web`.

| Test | Verdict | Notes |
| ---- | ------- | ----- |
| uv run pytest (149 passed) | PASS | Full pipeline suite, includes 56 new Phase 4 tests |
| test_cpi_trim_median (9 tests) | PASS | Median first over 50, partial tail splits, 60pct renormalize, mean fails while product passes, flat 0.2pct compounds to 2.4266 |
| test_cpi_engine (13 tests) | PASS | Changes, 55 SA registry load, weight renormalization and drift, vintage pin, contributions, 24 month minimum, gate flag, section labels and hashes |
| test_cpi_bulk (13 tests) | PASS | Two step fetch, non SUCCESS and non https refusal, declared and buffered caps, non zip and member and count caps, month extraction, truncation, missing vectors, no files written |
| test_cpi_golden (3 tests) | PASS | Three component golden pins trim 0.2667 percent per month, median A, product YoY, 12 month history, two index months |
| test_phase4_negatives (18 tests) | PASS | Weight, count, link, SA ownership, reference, sha12, stored trim, excluded weight, label, official, MAE suppression, flag honesty, honest breach passes, missing section |
| test_verify extended (22 checks) | PASS | Demo inflation attached, full snapshot passes V01 to V22 |
| test_live_snapshot extended (22 checks) | PASS | Demo inflation attached, full and degraded FRED paths pass V01 to V22 |
| npm test web (58 passed) | PASS | 53 prior plus 5 new inflation validator tests |
| npm run build | PASS | vite build clean, InflationPage chunk emitted |
| npm run typecheck | PASS | tsc noEmit clean |
| Live spike probe | PASS | 8 digit product ids return SUCCESS with zip URLs, 10 digit returns 406; weights zip 1.2 MB two members hashed in memory; CPI data member 161 MB expanded under the 256 MB member cap with cumulative guard |

Coverage summary: 149 passed (pytest) plus 58 passed (web), 0 failed. Happy path covered (demo inflation passes V19 to V22, golden trim and median, valid web triple). Edge cases covered (median boundary at exactly 50 percent, straddling tail splits, 24 month minimum, trailing 36 window, honest breach). Error conditions covered (weight drift, SA flag, link pin, reference grammar, sha12 mismatch, stored trim move, excluded weight, label and official status, MAE suppression, dishonest flag, missing section, oversize and non zip bulk, missing vectors).

Failure analysis: two interim test faults, both in new test code. The weight sum message match expected the literal 1.0 instead of the formatted total, and the flat 0.2 percent golden used 2.4274 instead of the computed 2.4266. Both fixed in test expectations. One product change from the spike: the registry pins eight digit product ids after the live API returned 406 for ten digit ids, and the member cap moved to 256 MB after the CPI data member measured 161 MB expanded. No other product code defects found.

## 2026-11-02 - Deploy: Test Report

Deploy verification across pipeline, web, live snapshot stubs, and daily workflow gates. No new test files; probes ran ad hoc plus existing suites.

| Test | Verdict | Notes |
| ---- | ------- | ----- |
| uv run pytest (93 passed) | PASS | Full pipeline suite, 1.18s, includes live full pass and degraded FRED pass |
| npm test web (53 passed) | PASS | node:test suites, 9 suites, 0 fail |
| npm run build:data | PASS | Exit 0, published 0 dates (no snapshots dir), index.json latest null |
| npm run build | PASS | vite build clean, 48 modules, dist written |
| npm run typecheck | PASS | tsc noEmit clean |
| SNAPSHOT_DATE only after verify 0, no skeleton marker | PASS | Print gated by code == 0; skeleton path returns 1 with skeleton message only |
| dirname mismatch reject | PASS | Wrong out dirname returns 2 with must match snapshot date message |
| StatCan skip no call | PASS | Empty statcan_indicators skips fetch, vectors empty, no statcan provenance |
| FRED absent degraded pass | PASS | fred_available False marks spreads and backtest missing with FRED_API_KEY reasons, warning present |
| FRED configured missing fail closed | PASS | fred_available True with empty histories marks spreads missing for no joint prints and backtest missing for 0 joint prints |
| FRED key absent returns None | PASS | read_api_key None when env unset |
| mock marker reject | PASS | Live snapshot returns 1 on mock marker; daily greps snapshots and dist for mock and refuses to publish |
| strict ISO reject ../ | PASS | ../, .., slash dates, padded whitespace, empty, month 13 all raise; 2026-10-30 resolves |
| daily.yml YAML parse | PASS | yaml.safe_load succeeds |
| daily.yml no ${{ }} in run blocks | PASS | 0 run blocks contain expression syntax; values pass via env |
| daily.yml permissions | PASS | Top contents read, snapshot contents write, build contents read, deploy pages write plus id-token write |
| daily.yml dist asserts | PASS | Asserts latest equals date plus dist .nojekyll, index.html, 404.html, data index, date snapshot and verify, with mock scan |

Coverage summary: 93 passed (pytest) plus 53 passed (web), 0 failed. Happy path covered (live full V01 to V18 pass, build data publish, vite build, typecheck). Edge cases covered (dirname mismatch, StatCan skip, FRED degraded versus configured empty, strict date grammar, run block env indirection). Error conditions covered (mock marker in snapshot and dist, YAML parse, permission pins, dist gate asserts, skeleton fail closed).

Failure analysis: one interim probe fault where the StatCan skip probe tried to assign a frozen dataclass field; reran using the as loaded map (statcan_indicators already empty) and asserted the skip branch directly. No product code defect found.

## 2026-11-01 - Phase 3: Test Report

Phase 3 site shell suite in `web/tests/` (node:test, no new framework).
Run with `npm test` in `/Users/ajeet/Projects/goc-rates-monitor/web`,
plus `npm run build` and `npm run typecheck` (both clean).

| Test | Verdict | Notes |
| ---- | ------- | ----- |
| Validators reject bad unit, quality, source grammar, overlong source | PASS | Benchmark quantity mutations each throw ValidationError |
| Validators reject NaN and Infinity | PASS | NaN, Infinity, negative Infinity all throw on value |
| Missing quality null accepted, non null rejected | PASS | Matches closed quality semantics |
| Asof mismatch rejected | PASS | snapshot_date versus requested asof detail names both dates |
| Verify digest mismatch rejected, match accepted | PASS | Published digest binding holds |
| Empty verify, non V01-V18, duplicate ids rejected | PASS | Exactly 18 checks V01 to V18 enforced |
| passed_count, failed_count, passed flag consistency rejected | PASS | Three inconsistency probes all fail closed |
| 5MiB cap and 15s timeout pinned | PASS | Constants asserted, oversize declared and streamed bodies rejected, hung fetch times out |
| Excessive knots, spreads, backtest, quantities, dates, provenance rejected | PASS | 11 knots, 2001 spreads, 2001 backtest, 10001 quantities, 2001 dates, 65 provenance entries |
| Deep nested recursion rejected | PASS | 80 level nesting trips the 64 level cap |
| Asof invalid versus absent versus unknown | PASS | Malformed kept distinct from absent, unknown well formed falls back to latest with banner |
| Router navigate, resource keys, wildcard fallback, 404 asof preserve | PASS | Static wiring checks on App.tsx, 404.html, index.html |
| Phone 360 no scroll | PASS | overflow-x auto, max-width 100 percent, 640px collapse, 44px touch targets |
| Footer stamp real counts tolerance method | PASS | passed_count, checks.length, tolerance pair, curveMethod, sha, unknownDate all rendered |
| Mock only via VITE_USE_MOCK dynamic import, bundle clean | PASS | No static fixture import, fresh dist chunks lack mock fixture and MOCK_DATE |
| Loading gate blocked no derived | PASS | Loading, error, missing, and failed states all block with NA messaging |
| build-data valid triple publishes with index | PASS | Sandbox run exits 0, dates and latest correct |
| build-data tampered snapshot fails sha no publish | PASS | Trailing byte trips digest mismatch, nothing published |
| build-data verify mismatch fails | PASS | Wrong snapshot_sha256 exits nonzero, nothing published |
| build-data missing manifest fails | PASS | Refuses to publish without manifest |
| build-data malformed dirs ignored | PASS | latest, 2026-13-99, notes.txt, 2026-02-30 skipped |
| build-data stale prune | PASS | Removed date pruned from output with log line |

Coverage summary: 53 passed, 0 failed (38 validate plus asof, 9 shell plus router, 6 build-data). Happy path covered (valid triple publish, digest match, known date resolve). Edge cases covered (missing quality null, empty asof value, impossible calendar dates, malformed dir names, stale prune). Error conditions covered (unit, quality, source, finiteness, asof and digest mismatch, count inconsistency, all collection caps, nesting cap, oversize, timeout, tampered snapshot, verify mismatch, missing manifest). New files `web/tests/phase3-validate.test.mjs`, `web/tests/phase3-shell.test.mjs`, `web/tests/phase3-build-data.test.mjs` plus `web/tests/ts-resolve.mjs` and `web/tests/register.mjs` loader shim; `test` script added to `web/package.json`. No source changes needed.

Failure analysis: two interim test faults, both in new test code. The asof probes first passed full paths to readAsofState, but the app passes location.search, so inputs were corrected to bare query strings. The fetch layer reads import.meta.env, which is undefined under plain node, so the test-only loader shim pins the same local defaults Vite provides; production code untouched. No product code defect found.

## 2026-11-01 - Phase 1: Test Report

Foundation suite plus review follow up negatives and boundary tests.
Full suite run with `uv run pytest` in `/Users/ajeet/Projects/goc-rates-monitor`.

| Test | Verdict | Notes |
| ---- | ------- | ----- |
| test_calendar.py (8 tests) | PASS | Easter computus, Good Friday, Christmas observed, joint legs, arithmetic, window, Toronto dating, US year boundary |
| test_clients.py (7 tests) | PASS | Valet series parse, label drift, group labels, retry, FRED missing key, FRED fixture, StatCan reuse |
| test_snapshot.py (5 tests) | PASS | Canonical dumps, NaN reject, manifest sha256, fail closed sections, raw prune |
| test_verify.py (5 tests) | PASS | Tolerance pin, T-bill formula, 12 checks pass, drift fails V11, verify_file exit 0 |
| Tampered snapshot bytes fail V10 | PASS | Appended byte yields exit 1, V10 mismatch detail |
| Missing manifest fails V10 | PASS | Absent manifest.json yields exit 1, V10 missing detail |
| StatCan non SUCCESS status raises | PASS | ERROR status raises ValueError on status |
| StatCan missing vectorDataPoint raises | PASS | Entry without vectorDataPoint raises ValueError |
| StatCan missing requested vector raises | PASS | Response omitting requested id raises ValueError |
| CLI config failure returns 2 | PASS | Missing map prints snapshot failed to stderr, exit 2 |
| CLI skeleton returns 1 not 0 | PASS | Writes snapshot.json plus manifest.json, exit 1, fails closed |
| US Saturday to Friday observe | PASS | 2021-12-31 closed on US and joint, open on CA |
| CA 2027 Christmas plus Boxing bump | PASS | Dec 27 and Dec 28 holidays, both non business on CA |
| CA 2027 Family Day plus Sep 30 | PASS | Feb 15 and Sep 30 holidays, both non business on CA |
| FRED key leak fails V11 redacted | PASS | Embedded key fails V11, detail omits key value |
| Path traversal date rejected | PASS | ../, nested traversal, slashes, empty all raise ValueError |
| Valet ID with slash rejected | PASS | Series and group ids with slash raise before network |
| Oversize declared Content-Length capped | PASS | Declared bytes over cap raise ValueError |
| Oversize snapshot file capped | PASS | verify_file over byte cap raises ValueError |
| fsync ordering mocked check | PASS | Order fsync then replace then dir fsync verified |

Coverage summary: 41 passed, 0 failed. Happy path covered by existing 25 tests (calendar, clients, snapshot, verify). Edge cases covered (2027 holiday collisions, year boundary observe, zero count, empty sections). Error conditions covered (tampered bytes, missing manifest, StatCan drift modes, CLI failures, traversal, grammar, caps, secret leak). New file `tests/test_phase1_negatives.py` adds 16 tests; no source changes needed.

Failure analysis: one interim failure in the fsync ordering test where the real directory fsync emitted an extra recorded fsync call. Fixed by stubbing the directory fsync step so the recorded order asserts file fsync before rename before directory fsync. No product code defect found.

## 2026-11-01 - Phase 2: Test Report

Phase 2 curve engine boundary plus negative tests. Full suite run with `uv run pytest` in `/Users/ajeet/Projects/goc-rates-monitor`.

| Test | Verdict | Notes |
| ---- | ------- | ----- |
| test_backtest_exactly_253_raises | PASS | 253 obs raise on the 254 minimum |
| test_backtest_254_yields_one_signal | PASS | 254 obs yield one signal row |
| test_non_positive_semiannual_base_raises | PASS | Yield negative 250 raises on range and base |
| test_non_decreasing_discounts_raise | PASS | 30pct short with 0pct long raises on monotonicity |
| test_v13_method_flag_tamper_fails | PASS | Tampered method fails V13 |
| test_v13_tenor_set_tamper_fails | PASS | 20Y label swap fails V13 tenor set |
| test_v13_stored_discount_mismatch_fails | PASS | 1pct discount bump fails V13 over 1.0bp |
| test_v13_stored_zero_mismatch_fails | PASS | 0.05pct zero bump fails V13 over 1.0bp |
| test_v16_missing_leg_dates_fail | PASS | Missing ca_date fails V16 |
| test_v16_non_dict_record_fails | PASS | Numeric record fails V16 without filtering |
| test_v16_empty_set_fails | PASS | Empty spreads fail V16 without vacuous pass |
| test_v18_non_iso_dates_fail | PASS | Slash date grammar fails V18 |
| test_v18_duplicate_dates_fail | PASS | Repeated date fails V18 strict increase |
| test_v18_out_of_order_dates_fail | PASS | Swapped dates fail V18 strict increase |
| test_max_tenor_1e9_raises_fast | PASS | 1e9 tenor raises via cap in under 1 second |
| test_tenor_60_5_raises | PASS | 60.5 year tenor raises on curve and risk paths |
| test_tenor_60_succeeds_with_120_periods | PASS | 60 year tenor prices at par with 120 periods |
| test_11_knots_reject | PASS | 11 knots raise on the 10 knot cap |
| test_2001_obs_reject | PASS | 2001 backtest obs raise on the 2000 cap |
| test_bill_days_400_reject | PASS | 400 day bill raises on the 366 day cap |
| test_source_id_api_key_fragment_reject | PASS | api_key fragment fails grammar and V15 |
| test_source_id_81_char_reject | PASS | 81 char id raises on the 80 char cap |
| test_yield_edges_accept | PASS | Negative 20 and 30 accept on slope and price |
| test_yield_edges_reject | PASS | Negative 20.01, 30.01, NaN, inf all raise |
| test_v13_overflow_becomes_fail_not_crash | PASS | Patched discount OverflowError fails V13 cleanly |
| test_v18_overflow_becomes_fail_not_crash | PASS | Patched backtest OverflowError fails V18 cleanly |
| test_cli_wired_real_quantities | PASS | Observed quantities wire into a real curve section |
| test_cli_skeleton_still_returns_1 | PASS | Skeleton writes pair and exits 1 to fail closed |

Coverage summary: 87 passed, 0 failed (59 prior plus 28 new in `tests/test_phase2_negatives.py`). Happy path covered by prior curve, analytics, risk, backtest, and verify goldens. Edge cases covered (254 single signal, 60 year 120 period par, yield edges negative 20 and 30). Error conditions covered (253 short, nonpositive base, nondecreasing discounts, V13 tamper and stored mismatch, V16 record modes, V18 date grammar, tenor and count caps, source id grammar, yield range, OverflowError containment, CLI skeleton). No source changes needed; `uv run ruff check src tests` passes.

Failure analysis: two interim test faults, both in new test code. The yield edge test first used negative 20 in a par knot, which correctly raises since any negative yield implies a discount above 1. Fixed to assert negative 20 and 30 on slope and par price paths. The V18 overflow test first patched `verify.run_backtest`, which does not exist since the import is local to the check runner. Fixed to patch `goc_rates.backtest.run_backtest`. No product code defect found; verify already contains OverflowError via ArithmeticError handling so both overflow probes fail closed.

## 2026-11-01 - Phase 4 lows: Test Report

Phase 4 low coverage in `tests/test_phase4_lows.py` (11 tests) plus
`web/tests/phase4-lows.test.mjs` (5 tests). Run with `uv run pytest`
in `/Users/ajeet/Projects/goc-rates-monitor`, plus `npm test`,
`npm run build`, and `npm run typecheck` in `web`.

| Test | Verdict | Notes |
| ---- | ------- | ----- |
| uv run pytest (173 passed) | PASS | Full pipeline suite, 162 prior plus 11 new lows |
| test_bulk_declared_size_understates_streamed_size_fails_closed | PASS | Declared 5 bytes with 50 streamed bytes fails on the 20 byte streaming cap |
| test_v21_scaled_contributions_and_total_together_fails | PASS | 1.5x scaled rows plus total plus headline still fails V21 row recompute |
| test_product_id_999_fails_v19 | PASS | Three digit id breaks the 8 digit grammar in V19 |
| test_product_id_999_fails_v22 | PASS | Three digit id breaks the bulk pin in V22 |
| test_duplicate_contribution_component_id_fails_v20_and_v21 | PASS | Repeated component id fails V20 and V21 |
| test_duplicate_vector_id_rejected_from_specs | PASS | Repeated vector id fails closed on specs load |
| test_basket_expenditure_year_disagree_fails_closed | PASS | Basket year 2023 versus registry 2024 fails closed |
| test_basket_weight_disagree_fails_closed | PASS | Weight beyond tolerance fails with disagrees |
| test_median_mom_only_tamper_fails_v20 | PASS | Median mom moved 5bp alone fails V20 |
| test_history_median_yoy_tamper_fails_v20 | PASS | History median YoY moved 5bp fails V20 |
| test_latest_trim_yoy_tamper_fails_v20 | PASS | Latest trim YoY moved 5bp fails trailing compound |
| npm test web (74 passed) | PASS | 69 prior plus 5 new lows |
| web rejects a three digit bulk product id | PASS | Product id 999 fails the 8 digit grammar |
| web rejects a trim_mom tamper with median left intact | PASS | Trim mom moved 5bp alone fails trim recompute |
| web rejects a median_mom tamper with trim left intact | PASS | Median mom moved 5bp alone fails median recompute |
| web rejects a history mom edit that breaks the YoY compound | PASS | History trim mom plus 1.0 breaks the trailing compound |
| web rejects a duplicate contribution component id | PASS | Repeated component id fails duplicate guard |
| npm run build | PASS | vite build clean, InflationPage chunk emitted |
| npm run typecheck | PASS | tsc noEmit clean |

Coverage summary: 173 passed (pytest) plus 74 passed (web), 0 failed. Happy path covered (prior demo fixture and mock snapshot still pass V19 to V22). Edge cases covered (1.5x scale factor distinct from the prior 2.0x probe, single mom tampers with the other leg intact, history versus latest YoY tampers). Error conditions covered (understated declared bulk size caught by the streaming cap, 999 product grammar in V19 V22 and web, duplicate contribution and vector ids, basket year and weight disagree).

Failure analysis: no product code defects found. One interim design note: the understated size probe first needed a doctored ZipInfo (declared 5 bytes, streamed 50 bytes, cap 20) so the precheck passes and the streaming guard is the layer that fails closed. No source changes needed.

## 2026-11-02 - Phase 6 step 6.0: Test Report

Phase 6 step 6.0 spreads envelope negatives in `tests/test_phase2_negatives.py`
(2 new tests) plus `web/tests/phase3-validate.test.mjs` (2 new tests).
Run with `uv run pytest` in `/Users/ajeet/Projects/goc-rates-monitor`,
plus `npm test` and `npm run typecheck` in `web`.

| Test | Verdict | Notes |
| ---- | ------- | ----- |
| uv run pytest (230 passed) | PASS | Full pipeline suite, 228 prior plus 2 new envelope negatives |
| test_v16_three_tenor_subset_fails | PASS | ok envelope with 2Y 5Y 10Y only fails V16 on the complete tenor set |
| test_v16_duplicate_tenor_fails | PASS | ok envelope with two 2Y records and no 30Y fails V16 on the complete tenor set |
| uv run ruff check src tests | PASS | All checks passed, no lint faults in the new tests |
| npm test web (132 passed) | PASS | 130 prior plus 2 new envelope negatives, 20 suites, 0 fail |
| web rejects an ok envelope with a 3 tenor subset | PASS | Sliced to 3 records fails with exactly plus no duplicates message |
| web rejects an ok envelope with a duplicate tenor and no 30Y | PASS | Doubled 2Y with 30Y dropped fails with no duplicates message |
| npm run typecheck | PASS | tsc noEmit clean |

Coverage summary: 230 passed (pytest) plus 132 passed (web), 0 failed. Happy path covered (prior 4 tenor ok fixtures still pass V16 and validateSnapshot). Edge cases covered (3 record subset boundary, exactly 4 records with one duplicated label). Error conditions covered (subset envelope fails V16 and validateSnapshot, duplicate tenor envelope fails V16 and validateSnapshot).

Failure analysis: no product code defects found. Both the Python V16 check and the web validator already enforced the exact 2Y 5Y 10Y 30Y set with no duplicates, so both negative probes failed closed on the first run with no source changes needed. No interim test faults.

## 2026-11-02 - Phase 7 history batch: Test Report

Phase 7 history batch in `history/backfill.json` (1250 daily, 60 CPI)
plus `web/public/data/history.json` merge (1250 daily with 1 verified,
60 CPI with 0 verified) and `web/tests/phase7-history.test.mjs`
(14 tests). Run with `uv run pytest -q` and
`uv run ruff check src tests` in `/Users/ajeet/Projects/goc-rates-monitor`,
plus `npm test`, `npm run typecheck`, and `npm run build` in `web`.

| Test | Verdict | Notes |
| ---- | ------- | ----- |
| uv run pytest (253 passed) | PASS | Full pipeline suite, includes 8 backfill command tests |
| uv run ruff check src tests | PASS | All checks passed |
| uv run ruff format check | NOTE | 57 files formatted, `tests/test_backfill.py` would reformat (line length nit, preexisting) |
| npm test web (151 passed) | PASS | 23 suites, 0 fail, includes 14 phase7 history tests |
| npm run typecheck | PASS | tsc noEmit clean |
| npm run build | PASS | vite build clean plus build:data merge, 52 modules |
| history.json publishes 1250 daily 1 verified | PASS | Merged history holds 1250 daily rows, exactly 1 verified (2026-10-30, source derived:history_verified_v1) |
| history.json publishes 60 CPI 0 verified | PASS | Merged history holds 60 CPI months (2021-10 to 2026-09), all verified false |
| verifyPassed gate | PASS | Index latest entry verify_passed true; failed verify snapshots never promote (web test pins daily stays backfill only) |
| CPI YoY recompute | PASS | Last CPI row trim and median YoY recompute to 0.0 diff via trailing 12 month compound; first 11 null, month 12 first non null |
| Slope recompute on verified row | PASS | All four slope pairs recompute to 0.0 diff on the 2026-10-30 verified row |
| Backfill raw rows carry verified false | PASS | All 1250 daily and 60 CPI backfill rows verified false with derived:backfill_v1 source |

Coverage summary: 253 passed (pytest) plus 151 passed (web), 0 failed. Happy path covered (backfill full and degraded paths, history merge happy path publishes history.json plus index history entry). Edge cases covered (250 row minimum, 1250 daily cap, 60 CPI cap, backfill absent, tampered manifest). Error conditions covered (non ISO asof, Valet failure, config failure, digest mismatch, promoted row forgery with verified true, overlap conflict beyond 1.0 bp, failed verify never promotes, slope and YoY recompute rejects).

Failure analysis: no product code defects found. One style note only: `uv run ruff format --check` flags `tests/test_backfill.py` for a line length reformat; suggested fix is `uv run ruff format tests/test_backfill.py` with no behavior change. Probes confirmed merge outputs directly (history.json 1250 daily with 1 verified at 2026-10-30, 60 CPI with 0 verified, index verify_passed true, YoY and slope recompute diff 0.0).
