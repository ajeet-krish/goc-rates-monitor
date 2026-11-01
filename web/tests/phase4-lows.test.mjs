import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { validateSnapshot, ValidationError } from "../src/lib/validate.ts";
import {
  mockSnapshot,
  MOCK_DATE,
} from "../src/lib/fixtures/mock-snapshot.ts";

function goodSnapshot() {
  return structuredClone(mockSnapshot);
}

describe("phase4 lows: product grammar, single mom tamper, history compound", () => {
  it("rejects a three digit bulk product id", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.bulk.cpi_monthly.product_id = 999;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /8 digit/);
  });

  it("rejects a trim_mom tamper with median left intact", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.latest.trim_mom.value += 0.05;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /trim_mom/);
  });

  it("rejects a median_mom tamper with trim left intact", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.latest.median_mom.value += 0.05;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /median_mom/);
  });

  it("rejects a history mom edit that breaks the YoY compound", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.history[0].trim_mom_percent += 1.0;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /compound/);
  });

  it("rejects a duplicate contribution component id", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.contributions[1].component_id =
      doc.observations.inflation.contributions[0].component_id;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /duplicate/);
  });
});
