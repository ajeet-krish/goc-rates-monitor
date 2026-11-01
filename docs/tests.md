# GoC Test Results

Last updated: 2026-11-01

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
