# GoC Test Results

Last updated: 2026-11-01

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
