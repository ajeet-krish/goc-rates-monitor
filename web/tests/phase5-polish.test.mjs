import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { validateSnapshot, validateVerify, ValidationError } from "../src/lib/validate.ts";
import {
  ASSUMPTION_ROWS,
  CHECK_FAMILIES,
  LIMIT_ROWS,
  METHOD_SECTIONS,
} from "../src/lib/methods-content.ts";
import { mockSnapshot, mockVerify, MOCK_DATE } from "../src/lib/fixtures/mock-snapshot.ts";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = dirname(here);
const readSource = (rel) => readFileSync(join(webRoot, rel), "utf8");

function goodSnapshot() {
  return structuredClone(mockSnapshot);
}

function collectCopy(value, out) {
  if (typeof value === "string") {
    out.push(value);
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) collectCopy(item, out);
    return;
  }
  if (value && typeof value === "object") {
    for (const item of Object.values(value)) collectCopy(item, out);
  }
}

describe("phase5 breaks validation: feed pins, caps, gates", () => {
  it("accepts the mock breaks section", () => {
    assert.doesNotThrow(() => validateSnapshot(goodSnapshot(), MOCK_DATE));
  });

  it("rejects a non literal breaks method", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.method = "dod_gate_v9";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /benchmark_switch_dod_gate_v1/);
  });

  it("rejects a feed source that is not the pinned bench_CDN.pdf", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.feed_source = "random.pdf";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /bench_CDN/);
  });

  it("rejects a threshold that drifts from 15.0 bp", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.threshold_bp = 25;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /15/);
  });

  it("rejects more than 64 switch events", () => {
    const doc = goodSnapshot();
    const row = doc.observations.breaks.events[0];
    doc.observations.breaks.events = Array.from({ length: 65 }, (_, i) => ({
      ...structuredClone(row),
      effective_date: "2026-0" + ((i % 9) + 1) + "-15",
      effective_joint_date: "2026-0" + ((i % 9) + 1) + "-15",
    }));
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /1 to 64/);
  });

  it("rejects a record count other than 4 tenors", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.records = doc.observations.breaks.records.slice(0, 3);
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /exactly 4/);
  });

  it("rejects a tenor order break", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.records = [...doc.observations.breaks.records].reverse();
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /2Y.*5Y.*10Y.*30Y/);
  });

  it("rejects a non ISO effective date", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.events[0].effective_date = "10/30/2026";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), ValidationError);
  });

  it("rejects a short feed digest", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.feed_sha256 = "abc123";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /64 character/);
  });

  it("rejects an unknown gate", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.records[0].gate = "mystery";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /gate must be one of/);
  });

  it("rejects duplicate switch events", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.events = [
      structuredClone(doc.observations.breaks.events[0]),
      structuredClone(doc.observations.breaks.events[0]),
    ];
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /duplicate switch event/);
  });
});

describe("phase5 breaks pins: vintage, closed tenors, units, provenance", () => {
  it("pins feed_vintage to 2026-11-01, not any ISO date", () => {
    assert.equal(mockSnapshot.observations.breaks.feed_vintage, "2026-11-01");
    const doc = goodSnapshot();
    doc.observations.breaks.feed_vintage = "2026-10-15";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /2026-11-01/);
  });

  it("rejects a 9Y event tenor outside the closed feed set", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.events[0].tenor = "9Y";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /closed feed set|one of/);
  });

  it("rejects each tenor outside 2Y 3Y 5Y 7Y 10Y 30Y LONG", () => {
    for (const bad of ["1Y", "4Y", "9Y", "15Y", "20Y"]) {
      const doc = goodSnapshot();
      doc.observations.breaks.events[0].tenor = bad;
      assert.throws(() => validateSnapshot(doc, MOCK_DATE), ValidationError);
    }
  });

  it("accepts every closed feed tenor", () => {
    for (const tenor of ["2Y", "3Y", "5Y", "7Y", "10Y", "30Y", "LONG"]) {
      const doc = goodSnapshot();
      doc.observations.breaks.events[0].tenor = tenor;
      assert.doesNotThrow(() => validateSnapshot(doc, MOCK_DATE));
    }
  });

  it("rejects a wrong incoming coupon unit", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.events[0].incoming_coupon_unit = "basis_points";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /percent/);
  });

  it("rejects a wrong outgoing coupon unit", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.events[0].outgoing_coupon_unit = "count";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /percent/);
  });

  it("rejects a wrong prev yield unit", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.records[0].prev_yield_unit = "basis_points";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /percent/);
  });

  it("rejects a wrong history_count unit", () => {
    const doc = goodSnapshot();
    doc.observations.breaks.records[0].history_count_unit = "percent";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /count/);
  });

  it("pins provenance benchmark_switches vintage to the feed vintage", () => {
    const doc = goodSnapshot();
    assert.equal(doc.provenance.benchmark_switches.vintage, doc.observations.breaks.feed_vintage);
    doc.provenance.benchmark_switches.vintage = "2026-10-01";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /must match breaks feed_vintage/);
  });

  it("pins provenance benchmark_switches sha256 to the feed digest", () => {
    const doc = goodSnapshot();
    assert.equal(doc.provenance.benchmark_switches.sha256, doc.observations.breaks.feed_sha256);
    doc.provenance.benchmark_switches.sha256 = "0".repeat(64);
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /must match breaks feed_sha256/);
  });

  it("rejects a missing benchmark_switches provenance beside breaks", () => {
    const doc = goodSnapshot();
    delete doc.provenance.benchmark_switches;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /benchmark_switches is missing/);
  });
});

describe("phase5 gate nullness: NA names its reason", () => {
  it("holds one comparable with a number and one switch_break with null", () => {
    const records = mockSnapshot.observations.breaks.records;
    const comparable = records.find((r) => r.gate === "comparable");
    const suppressed = records.find((r) => r.gate === "switch_break");
    assert.ok(comparable && typeof comparable.dod_bp === "number");
    assert.ok(suppressed && suppressed.dod_bp === null);
  });

  it("rejects a switch_break that keeps a numeric dod", () => {
    const doc = goodSnapshot();
    const row = doc.observations.breaks.records.find((r) => r.gate === "switch_break");
    row.dod_bp = 3.5;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /must suppress dod_bp to null/);
  });

  it("rejects a comparable that drops its number", () => {
    const doc = goodSnapshot();
    const row = doc.observations.breaks.records.find((r) => r.gate === "comparable");
    row.dod_bp = null;
    row.dod_quantity.value = null;
    row.dod_quantity.quality = "missing";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /must keep a numeric dod_bp/);
  });

  it("rejects a quantity that disagrees with dod_bp", () => {
    const doc = goodSnapshot();
    const row = doc.observations.breaks.records.find((r) => r.gate === "comparable");
    row.dod_quantity.value += 0.5;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /must match dod_bp/);
  });

  it("rejects a quantity source outside derived:dod_gate", () => {
    const doc = goodSnapshot();
    const row = doc.observations.breaks.records.find((r) => r.gate === "comparable");
    row.dod_quantity.source_id = "derived:curve";
    row.source_id = "derived:curve";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /derived:dod_gate/);
  });

  it("rejects a null dod paired with an observed quantity", () => {
    const doc = goodSnapshot();
    const row = doc.observations.breaks.records.find((r) => r.gate === "switch_break");
    row.dod_quantity.quality = "observed";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), ValidationError);
  });

  it("accepts 23 checks with V23 present", () => {
    const report = structuredClone(mockVerify);
    assert.equal(report.checks.length, 23);
    assert.equal(report.checks[22].id, "V23");
    assert.doesNotThrow(() => validateVerify(report));
  });
});

describe("phase5 methods pins: ids, families, copy hygiene", () => {
  it("pins the three live method ids", () => {
    const methods = Object.fromEntries(METHOD_SECTIONS.map((s) => [s.id, s.method]));
    assert.equal(methods.curve, "par_approx_semiannual_log_discount_v1");
    assert.equal(methods.inflation, "cpi_trim_median_weighted_sa_v1");
    assert.equal(methods.breaks, "benchmark_switch_dod_gate_v1");
  });

  it("covers all 23 checks in four families ending at V23", () => {
    assert.equal(CHECK_FAMILIES.length, 4);
    assert.equal(CHECK_FAMILIES[3].range, "V23");
    assert.match(CHECK_FAMILIES[0].range, /V01 to V12/);
    assert.match(CHECK_FAMILIES[2].range, /V19 to V22/);
  });

  it("states the 15 bp threshold and the 1.0 bp tolerance", () => {
    const copy = [];
    collectCopy(METHOD_SECTIONS, copy);
    assert.ok(copy.some((t) => t.includes("15.0 basis points")));
    assert.ok(copy.some((t) => t.includes("1.0 basis point")));
  });

  it("names the tax window 2024-12 to 2026-03", () => {
    const copy = [];
    collectCopy(METHOD_SECTIONS, copy);
    assert.ok(copy.some((t) => t.includes("2024-12 to 2026-03")));
  });

  it("keeps assumptions and limits tables populated", () => {
    assert.ok(ASSUMPTION_ROWS.length >= 5);
    assert.ok(LIMIT_ROWS.length >= 4);
  });

  it("uses plain punctuation in methods copy", () => {
    const copy = [];
    collectCopy(METHOD_SECTIONS, copy);
    collectCopy(ASSUMPTION_ROWS, copy);
    collectCopy(LIMIT_ROWS, copy);
    collectCopy(CHECK_FAMILIES, copy);
    const emDash = String.fromCharCode(0x2014);
    const enDash = String.fromCharCode(0x2013);
    const doubled = "-".concat("-");
    for (const text of copy) {
      assert.ok(!text.includes(emDash), "em dash found");
      assert.ok(!text.includes(enDash), "en dash found");
      assert.ok(!text.includes(doubled), "double hyphen found");
    }
  });
});

describe("phase5 footer and banner copy", () => {
  it("stamps checked UTC plus inflation and breaks methods with feed vintage", () => {
    const stamp = readSource("src/components/FooterStamp.tsx");
    assert.match(stamp, /checked.*UTC/);
    assert.match(stamp, /inflation method/);
    assert.match(stamp, /breaks method/);
    assert.match(stamp, /feed vintage/);
    assert.match(stamp, /vintage unknown/);
  });

  it("links the stamp to verification, methods, breaks, and inflation", () => {
    const stamp = readSource("src/components/FooterStamp.tsx");
    for (const route of ["/verification", "/methods", "/breaks", "/inflation"]) {
      assert.ok(stamp.includes(route), "stamp misses route " + route);
    }
  });

  it("contrasts Toronto calendar days with the V12 business day rule", () => {
    const banner = readSource("src/components/StalenessBanner.tsx");
    assert.match(banner, /4 or more/);
    assert.match(banner, /calendar_days/);
    assert.match(banner, /5 business_days/);
    assert.match(banner, /V12/);
  });

  it("names gates and reasons on the breaks page with backtest separated", () => {
    const page = readSource("src/pages/BreaksPage.tsx");
    for (const gate of ["comparable", "switch_break", "calendar_gap", "missing_prev"]) {
      assert.ok(page.includes(gate), "breaks page misses gate " + gate);
    }
    assert.match(page, /Secondary: backtest/);
    assert.match(page, /no splice/);
  });

  it("shows the validation flag badge and tax window on the inflation page", () => {
    const page = readSource("src/pages/InflationPage.tsx");
    assert.match(page, /2024-12 to 2026-03/);
    assert.match(page, /exceeds_gate_needs_explanation/);
    assert.match(page, /sha12/);
  });
});
