import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { zeroCurvePoints, missingZeroTenors } from "../src/lib/curve-points.ts";
import { mockSnapshot } from "../src/lib/fixtures/mock-snapshot.ts";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = dirname(here);
const readSource = (rel) => readFileSync(join(webRoot, rel), "utf8");

function knot(tenor, tenorYears, inputYtm) {
  return {
    tenor,
    tenor_years: tenorYears,
    tenor_unit: "duration_years",
    yield_percent: inputYtm,
    yield_unit: "percent_yield",
    discount: 0.5,
    discount_unit: "unitless_ratio",
    source_id: "derived:curve",
  };
}

describe("phase6 zero chart: points come from the solved zero mapping", () => {
  it("plots solved zeros, not input YTM, for the reported 10Y and 30Y case", () => {
    const knots = [knot("10Y", 10, 3.78), knot("30Y", 30, 4.11)];
    const zeroYields = { "10Y": { value: 3.8079 }, "30Y": { value: 4.1994 } };
    const points = zeroCurvePoints(knots, zeroYields);
    assert.deepEqual(points, [
      { x: 10, y: 3.8079 },
      { x: 30, y: 4.1994 },
    ]);
    assert.notEqual(points[0].y, 3.78);
    assert.notEqual(points[1].y, 4.11);
  });

  it("renders a missing solved zero as an unavailable null gap", () => {
    const knots = [knot("10Y", 10, 3.78), knot("30Y", 30, 4.11)];
    const zeroYields = { "10Y": { value: null }, "30Y": { value: 4.1994 } };
    const points = zeroCurvePoints(knots, zeroYields);
    assert.equal(points[0].y, null);
    assert.equal(points[1].y, 4.1994);
    assert.deepEqual(missingZeroTenors(knots, zeroYields), ["10Y"]);
  });

  it("treats an absent tenor entry as unavailable, never filled from input YTM", () => {
    const knots = [knot("2Y", 2, 3.32), knot("5Y", 5, 3.62)];
    const points = zeroCurvePoints(knots, { "2Y": { value: 3.31 } });
    assert.deepEqual(points, [
      { x: 2, y: 3.31 },
      { x: 5, y: null },
    ]);
    assert.deepEqual(missingZeroTenors(knots, { "2Y": { value: 3.31 } }), ["5Y"]);
  });

  it("holds the mock fixture divergent so the regression stays meaningful", () => {
    const byTenor = Object.fromEntries(
      mockSnapshot.observations.curve.knots.map((k) => [k.tenor, k.yield_percent]),
    );
    const zeros = mockSnapshot.observations.curve.zero_yields;
    let divergent = 0;
    for (const [tenor, input] of Object.entries(byTenor)) {
      const zero = zeros[tenor]?.value;
      assert.ok(typeof zero === "number", "mock zero missing for " + tenor);
      if (Math.abs(zero - input) > 1e-9) divergent += 1;
    }
    assert.ok(divergent > 0, "mock inputs and zeros must differ");
    const points = zeroCurvePoints(mockSnapshot.observations.curve.knots, zeros);
    for (const p of points) {
      const knot = mockSnapshot.observations.curve.knots.find((k) => k.tenor_years === p.x);
      assert.equal(p.y, zeros[knot.tenor].value);
    }
  });

  it("wires both zero charts through the solved zero helper", () => {
    for (const rel of ["src/pages/CurvePage.tsx", "src/pages/IndexPage.tsx"]) {
      const source = readSource(rel);
      assert.ok(source.includes("zeroCurvePoints"), rel + " misses the zero helper");
      assert.ok(source.includes("zero_yields"), rel + " misses the zero mapping");
      assert.ok(
        source.includes("missingZeroTenors") && source.includes("Unavailable: solved zero missing"),
        rel + " must name unavailable zeros",
      );
      assert.ok(
        !source.includes("y: k.yield_percent"),
        rel + " still plots input YTM under a zero label",
      );
    }
  });
});
