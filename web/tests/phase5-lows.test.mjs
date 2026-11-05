import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import {
  validateSnapshot,
  validateVerify,
  ValidationError,
  EXPECTED_VERIFY_IDS,
  MAX_HISTORY_OBS,
} from "../src/lib/validate.ts";
import { CHECK_FAMILIES } from "../src/lib/methods-content.ts";
import { mockSnapshot, mockVerify, MOCK_DATE } from "../src/lib/fixtures/mock-snapshot.ts";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = dirname(here);
const readSource = (rel) => readFileSync(join(webRoot, rel), "utf8");

function goodSnapshot() {
  return structuredClone(mockSnapshot);
}

describe("phase5 lows: history caps, both true gates, calendar nullness", () => {
  it("rejects history_count over the observation cap", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.records[0].history_count = MAX_HISTORY_OBS + 1;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), new RegExp(String(MAX_HISTORY_OBS)));
  });

  it("accepts history_count at exactly the observation cap", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.records[0].history_count = MAX_HISTORY_OBS;
    assert.doesNotThrow(() => validateSnapshot(doc, MOCK_DATE));
  });

  it("pins MAX_HISTORY_OBS at 2750 beside the parameterized history_count gates", () => {
    assert.equal(MAX_HISTORY_OBS, 2750);
  });

  it("rejects a boolean history_count without coercion", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.records[0].history_count = true;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), ValidationError);
  });

  it("holds switch_break null when both flags are true", () => {
    const doc = goodSnapshot();
    const row = doc.observations.breaks.records.find((r) => r.gate === "switch_break");
    assert.ok(row);
    row.switch_in_window = true;
    row.calendar_gap = true;
    row.dod_bp = null;
    row.dod_quantity.value = null;
    row.dod_quantity.quality = "missing";
    assert.doesNotThrow(() => validateSnapshot(doc, MOCK_DATE));
  });

  it("rejects a calendar_gap that drops its number", () => {
    const doc = goodSnapshot();
    const before = doc.observations.breaks.records.find((r) => r.gate === "calendar_gap");
    let row = before;
    if (!row) {
      row = doc.observations.breaks.records.find((r) => r.gate === "comparable");
      row.gate = "calendar_gap";
    }
    row.dod_bp = null;
    row.dod_quantity.value = null;
    row.dod_quantity.quality = "missing";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /must keep a numeric dod_bp/);
  });
});

describe("phase5 lows: tenor drift, vintage, coupon units, provenance", () => {
  it("rejects a 9Y record tenor outside 2Y 5Y 10Y 30Y", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.records[0].tenor = "9Y";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /2Y.*5Y.*10Y.*30Y/);
  });

  it("rejects a drifted feed vintage", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.feed_vintage = "2026-10-01";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /2026-11-01/);
  });

  it("rejects a wrong incoming coupon unit", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.events[0].incoming_coupon_unit = "basis_points";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /percent/);
  });

  it("rejects a wrong prev yield unit", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.records[0].prev_yield_unit = "count";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /percent/);
  });

  it("rejects a provenance vintage mismatch", () => {
    const doc = goodSnapshot();
    doc.provenance.benchmark_switches.vintage = "2026-10-01";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /must match breaks feed_vintage/);
  });

  it("rejects a provenance sha mismatch", () => {
    const doc = goodSnapshot();
    doc.provenance.benchmark_switches.sha256 = "0".repeat(64);
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /must match breaks feed_sha256/);
  });
});

describe("phase5 lows: methods pins 25 checks tolerance footer banner", () => {
  it("pins 25 expected checks ending at V25", () => {
    assert.equal(EXPECTED_VERIFY_IDS.length, 25);
    assert.equal(EXPECTED_VERIFY_IDS[0], "V01");
    assert.equal(EXPECTED_VERIFY_IDS[24], "V25");
  });

  it("rejects a verify report with 24 checks", () => {
    const report = structuredClone(mockVerify);
    report.checks = report.checks.slice(0, 24);
    report.passed_count = 24;
    report.failed_count = 0;
    assert.throws(() => validateVerify(report), /exactly 25/);
  });

  it("covers V23 in the fourth check family and V24 to V25 in the fifth with 1.0 bp tolerance", () => {
    assert.equal(CHECK_FAMILIES.length, 5);
    assert.equal(CHECK_FAMILIES[3].range, "V23");
    assert.equal(CHECK_FAMILIES[4].range, "V24 to V25");
    const report = structuredClone(mockVerify);
    assert.equal(report.tolerance_bp, 1.0);
    assert.equal(report.tolerance_unit, "basis_points");
  });

  it("renders unknown fallbacks in the footer stamp", () => {
    const stamp = readSource("src/components/FooterStamp.tsx");
    assert.match(stamp, /method unknown/);
    assert.match(stamp, /vintage unknown/);
    assert.match(stamp, /tolerance unknown/);
    assert.match(stamp, /Unknown date requested/);
  });

  it("states calendar days in Toronto against the business day rule", () => {
    const banner = readSource("src/components/StalenessBanner.tsx");
    assert.match(banner, /calendar_days/);
    assert.match(banner, /business_days/);
    assert.match(banner, /America\/Toronto/);
    assert.match(banner, /V12/);
    assert.match(banner, /weekends age this banner but never fail that check/);
  });
});
