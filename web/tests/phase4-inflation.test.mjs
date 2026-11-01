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

describe("phase4 inflation mirrors: method, contributions, headline, bulk, flag", () => {
  it("accepts the fixed mock with 2.4266 YoY and headline_mom", () => {
    assert.doesNotThrow(() => validateSnapshot(goodSnapshot(), MOCK_DATE));
  });

  it("rejects a non literal method", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.method = "trim_v1";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), ValidationError);
  });

  it("rejects a scaled contribution and total that V21 must catch", () => {
    const doc = goodSnapshot();
    for (const row of doc.observations.inflation.contributions) {
      row.contribution_pp *= 2;
    }
    doc.observations.inflation.total_contribution_pp *= 2;
    doc.observations.inflation.headline_mom.value *= 2;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /recompute/);
  });

  it("rejects a rate edit without its contribution", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.contributions[0].monthly_rate_percent += 2;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /recompute/);
  });

  it("rejects a headline_mom that disagrees with the recomputed mean", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.headline_mom.value += 0.05;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /headline/);
  });

  it("rejects a bulk product id that breaks the name to id pin", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.bulk.cpi_monthly.product_id = 18100005;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /must pin/);
  });

  it("rejects a ten digit bulk product id", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.bulk.cpi_monthly.product_id = 1810000401;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /8 digit/);
  });

  it("rejects a flag that does not match the recomputed gate", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.validation.flag = "exceeds_gate_needs_explanation";
    doc.observations.inflation.validation.exceeds_gate = true;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /gate/);
  });

  it("rejects a median_component outside the contribution set", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.latest.median_component = "C99";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /contribution row/);
  });

  it("rejects a listed but wrong median_component that breaks the weighted median recompute", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.latest.median_component = "C01";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /recomputed weighted median/);
  });

  it("rejects a YoY that does not compound the history moms", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.latest.trim_yoy.value += 0.05;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /compound/);
  });
});
