import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { escapeCsvCell, toCsv, csvHeaderLabel } from "../src/lib/csv.ts";
import {
  deltaBp,
  stepDate,
  overlayCurves,
  dateToEpochSec,
  monthToEpochSec,
} from "../src/lib/history.ts";
import { isStrictIsoDate, readAsofState, resolveAsof } from "../src/lib/asof.ts";
import { validateSnapshot } from "../src/lib/validate.ts";
import { mockSnapshot, MOCK_DATE } from "../src/lib/fixtures/mock-snapshot.ts";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = dirname(here);
const readSource = (rel) => readFileSync(join(webRoot, rel), "utf8");

function knotRow(tenor, years, value) {
  return {
    knots: [{ tenor, tenor_years: years }],
    zeroYields: { [tenor]: { value } },
  };
}

describe("phase7 terminal DataTable sorting: nulls last contract in source", () => {
  const source = readSource("src/components/DataTable.tsx");
  const sortHelpers = readSource("src/lib/table-sort.ts");

  it("names every missing token so NA variants sort as missing", () => {
    for (const token of ['""', '"na"', '"n/a"', '"null"', '"none"', '"missing"']) {
      assert.ok(sortHelpers.includes(token), "missing token absent: " + token);
    }
    assert.ok(sortHelpers.includes("MISSING_TOKENS"), "missing token set absent");
  });

  it("forces missing cells last before the direction flip is applied", () => {
    const aMissing = sortHelpers.indexOf("if (aMissing) return 1;");
    const bMissing = sortHelpers.indexOf("if (bMissing) return -1;");
    const flip = sortHelpers.indexOf('dir === "asc" ? order : -order');
    assert.ok(aMissing >= 0, "aMissing nulls last line absent");
    assert.ok(bMissing >= 0, "bMissing nulls last line absent");
    assert.ok(flip >= 0, "direction flip absent");
    assert.ok(aMissing < flip && bMissing < flip, "nulls last must precede the asc/desc flip");
  });

  it("advertises nulls last plus aria sort state on every header button", () => {
    assert.ok(source.includes("nulls last"), "header must name nulls last");
    assert.ok(source.includes("aria-sort"), "aria sort state absent");
    assert.ok(source.includes("ascending") && source.includes("descending"), "sort states absent");
  });

  it("supports explicit number and date kinds with inference fallback", () => {
    assert.ok(source.includes('kind?: "number" | "date" | "string"'), "explicit kind prop absent");
    assert.ok(sortHelpers.includes("parseNumericCell"), "numeric parse absent");
    assert.ok(sortHelpers.includes("parseDateCell"), "date parse absent");
    assert.ok(sortHelpers.includes("inferKind"), "kind inference absent");
  });

  it("cycles asc to desc to unsorted instead of sticking on one direction", () => {
    assert.ok(source.includes("nextSortState"), "sort cycle delegation absent");
    assert.ok(sortHelpers.includes('dir: "asc"'), "asc set absent");
    assert.ok(sortHelpers.includes('dir: "desc"'), "desc set absent");
    assert.ok(sortHelpers.includes("return null;"), "third click clear absent");
  });

  it("pins display caps and the export wiring for unit headers", () => {
    assert.ok(source.includes("MAX_TABLE_ROWS = 2000"), "row cap drift");
    assert.ok(source.includes("MAX_TABLE_COLUMNS = 32"), "column cap drift");
    assert.ok(source.includes("exportFilename"), "export filename prop absent");
    assert.ok(source.includes("ExportButton"), "ExportButton wiring absent");
  });

  it("declares number and date columns across curve, funding, and inflation tables", () => {
    for (const rel of ["src/pages/CurvePage.tsx", "src/pages/FundingPage.tsx", "src/pages/InflationPage.tsx"]) {
      const page = readSource(rel);
      assert.ok(page.includes('kind: "number"'), rel + " has no sortable number column");
      assert.ok(page.includes("DataTable"), rel + " misses the shared DataTable");
    }
    const funding = readSource("src/pages/FundingPage.tsx");
    assert.ok(funding.includes('kind: "date"'), "funding spread table misses its sortable date column");
  });
});

describe("phase7 terminal CSV: escaping plus unit headers", () => {
  it("passes plain fields through untouched", () => {
    assert.equal(escapeCsvCell("3.92"), "3.92");
    assert.equal(escapeCsvCell("2Y"), "2Y");
    assert.equal(escapeCsvCell(""), "");
  });

  it("quotes fields holding commas, quotes, CR, or LF with doubled quotes", () => {
    assert.equal(escapeCsvCell("a,b"), '"a,b"');
    assert.equal(escapeCsvCell('say "hi"'), '"say ""hi"""');
    assert.equal(escapeCsvCell("line1\nline2"), '"line1\nline2"');
    assert.equal(escapeCsvCell("cell\rreturn"), '"cell\rreturn"');
    assert.equal(escapeCsvCell("a,b \"c\"\nd"), '"a,b ""c""\nd"');
  });

  it("always carries the unit in the header label", () => {
    assert.equal(csvHeaderLabel({ key: "zero", header: "Zero", unit: "percent_yield" }), "Zero (percent_yield)");
    assert.equal(csvHeaderLabel({ key: "tenor", header: "Tenor" }), "Tenor");
  });

  it("exports missing cells as NA matching the on screen tables", () => {
    const text = toCsv(
      [{ key: "a", header: "A" }, { key: "b", header: "B", unit: "bp" }],
      [{ a: "1.0" }]
    );
    assert.equal(text, "A,B (bp)\r\n1.0,NA\r\n");
  });

  it("uses CRLF line endings with exactly one trailing newline", () => {
    const text = toCsv(
      [{ key: "tenor", header: "Tenor" }, { key: "zero", header: "Zero", unit: "percent_yield" }],
      [
        { tenor: "2Y", zero: "3.31 pct" },
        { tenor: "5Y", zero: 'quoted "yield", revised' },
      ]
    );
    assert.equal(
      text,
      "Tenor,Zero (percent_yield)\r\n2Y,3.31 pct\r\n5Y,\"quoted \"\"yield\"\", revised\"\r\n"
    );
    assert.ok(text.endsWith("\r\n") && !text.endsWith("\r\n\r\n"), "exactly one trailing CRLF");
  });

  it("wires every desk table to an export file with unit bearing columns", () => {
    for (const [rel, file] of [
      ["src/pages/CurvePage.tsx", "curve-knots.csv"],
      ["src/pages/FundingPage.tsx", "funding-spreads.csv"],
      ["src/pages/InflationPage.tsx", "inflation-contributions.csv"],
    ]) {
      const page = readSource(rel);
      assert.ok(page.includes('exportFilename="' + file + '"'), rel + " misses " + file);
    }
    const button = readSource("src/components/ExportButton.tsx");
    assert.ok(button.includes("No rows to export"), "empty export fallback absent");
    assert.ok(button.includes("aria-label"), "export count aria label absent");
  });
});

describe("phase7 terminal overlay: deltaBp plus stepDate", () => {
  it("converts a solved zero gap to basis points with sign", () => {
    assert.ok(Math.abs(deltaBp(3.92, 3.82) - 10.0) < 1e-9, "10 bp up gap");
    assert.ok(Math.abs(deltaBp(3.82, 3.92) + 10.0) < 1e-9, "10 bp down gap");
    assert.equal(deltaBp(3.9, 3.9), 0);
  });

  it("returns null when either overlay leg is missing or non finite", () => {
    assert.equal(deltaBp(null, 3.82), null);
    assert.equal(deltaBp(3.92, null), null);
    assert.equal(deltaBp(undefined, 3.82), null);
    assert.equal(deltaBp(3.92, undefined), null);
    assert.equal(deltaBp(Number.NaN, 3.82), null);
    assert.equal(deltaBp(3.92, Number.POSITIVE_INFINITY), null);
  });

  it("steps through sorted ISO dates and stops at either end", () => {
    const dates = ["2026-10-30", "2026-10-28", "2026-10-29"];
    assert.equal(stepDate(dates, "2026-10-29", 1), "2026-10-30");
    assert.equal(stepDate(dates, "2026-10-29", -1), "2026-10-28");
    assert.equal(stepDate(dates, "2026-10-30", 1), null);
    assert.equal(stepDate(dates, "2026-10-28", -1), null);
  });

  it("refuses to wrap on unknown or absent positions", () => {
    const dates = ["2026-10-28", "2026-10-29", "2026-10-30"];
    assert.equal(stepDate(dates, "2026-10-27", 1), null);
    assert.equal(stepDate(dates, null, 1), null);
    assert.equal(stepDate([], "2026-10-30", 1), null);
  });

  it("aligns compare zeros by tenor and leaves missing legs null", () => {
    const current = {
      knots: [
        { tenor: "2Y", tenor_years: 2 },
        { tenor: "10Y", tenor_years: 10 },
      ],
      zeroYields: { "2Y": { value: 3.31 }, "10Y": { value: null } },
    };
    const compare = {
      knots: [
        { tenor: "2Y", tenor_years: 2 },
        { tenor: "10Y", tenor_years: 10 },
      ],
      zeroYields: { "2Y": { value: 3.21 }, "10Y": { value: 3.9 } },
    };
    const rows = overlayCurves(current, compare);
    assert.equal(rows.length, 2);
    assert.equal(rows[0].tenor, "2Y");
    assert.ok(Math.abs(rows[0].deltaBp - 10.0) < 1e-9, "2Y delta 10 bp");
    assert.equal(rows[1].currentZero, null);
    assert.equal(rows[1].deltaBp, null);
  });

  it("renders NA deltas with no compare curve instead of filling zeros", () => {
    const rows = overlayCurves(knotRow("2Y", 2, 3.31), null);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].currentZero, 3.31);
    assert.equal(rows[0].compareZero, null);
    assert.equal(rows[0].deltaBp, null);
    assert.deepEqual(overlayCurves(null, knotRow("2Y", 2, 3.21)), []);
  });

  it("keeps the toolbar step helpers on a real date axis", () => {
    assert.ok(dateToEpochSec("2026-10-29") < dateToEpochSec("2026-10-30"), "daily axis ordered");
    assert.ok(monthToEpochSec("2026-08") < monthToEpochSec("2026-09"), "monthly axis ordered");
    assert.ok(Number.isNaN(dateToEpochSec("not-a-date")), "bad date is NaN, never a tick");
  });

  it("documents the overlay math and the never block rule on the curve page", () => {
    const page = readSource("src/pages/CurvePage.tsx");
    assert.ok(page.includes("overlayCurves"), "overlay helper not wired");
    assert.ok(page.includes("(current minus compare) times 100"), "delta math caption absent");
    assert.ok(page.includes("Current curve stays"), "compare failure must leave current authoritative");
    assert.ok(page.includes("Compare snapshot unavailable"), "compare error status absent");
  });
});

describe("phase7 terminal compare query validation", () => {
  it("accepts strict ISO dates and rejects traversal plus malformed input", () => {
    assert.equal(isStrictIsoDate("2026-10-30"), true);
    assert.equal(isStrictIsoDate("../"), false);
    assert.equal(isStrictIsoDate("2026-13-01"), false);
    assert.equal(isStrictIsoDate("2026-02-30"), false);
    assert.equal(isStrictIsoDate(""), false);
    assert.equal(isStrictIsoDate("2026-10-30 "), false);
  });

  it("keeps malformed asof distinct from absent so the unknown badge can name it", () => {
    assert.deepEqual(readAsofState("?asof=2026-10-30"), { requested: "2026-10-30", invalid: null });
    assert.deepEqual(readAsofState(""), { requested: null, invalid: null });
    assert.deepEqual(readAsofState("?asof=../"), { requested: null, invalid: "../" });
    assert.deepEqual(readAsofState("?asof="), { requested: null, invalid: null });
  });

  it("resolves known dates and falls back to latest with the unknown named", () => {
    const dates = ["2026-10-28", "2026-10-30"];
    assert.deepEqual(resolveAsof("2026-10-28", null, dates, "2026-10-30"), {
      asof: "2026-10-28",
      unknownDate: null,
    });
    assert.deepEqual(resolveAsof("2026-10-29", null, dates, "2026-10-30"), {
      asof: "2026-10-30",
      unknownDate: "2026-10-29",
    });
    assert.deepEqual(resolveAsof(null, "../", dates, "2026-10-30"), {
      asof: "2026-10-30",
      unknownDate: "../",
    });
  });

  it("validates ?compare= against strict grammar plus the published index", () => {
    const app = readSource("src/App.tsx");
    assert.ok(app.includes("params.get(\"compare\")"), "compare query read absent");
    assert.ok(app.includes("isStrictIsoDate(raw)"), "compare grammar guard absent");
    assert.ok(app.includes("idx.dates.includes(raw)"), "compare index membership guard absent");
    assert.ok(app.includes("unknownCompare"), "unknown compare badge state absent");
    assert.ok(app.includes("unknown compare"), "unknown compare caption absent");
  });

  it("fetches the compare snapshot independently so a bad compare never blocks the desk", () => {
    const app = readSource("src/App.tsx");
    assert.ok(app.includes("compareSnapshot"), "compare resource absent");
    assert.ok(app.includes("No compare"), "compare clear option absent");
    assert.ok(app.includes("compare-select"), "compare picker absent");
  });
});

describe("phase7 terminal synced crosshairs prop", () => {
  const chart = readSource("src/components/Chart.tsx");

  it("declares one sync key per page and syncs series together", () => {
    assert.ok(chart.includes("syncKey?: string"), "syncKey prop absent");
    assert.ok(chart.includes("sync: { key: props.syncKey, setSeries: true }"), "uPlot sync wiring absent");
  });

  it("keeps every chart on a page under that page key alone", () => {
    const expectations = [
      ["src/pages/CurvePage.tsx", "curve", ["funding", "inflation", "breaks", "desk"]],
      ["src/pages/FundingPage.tsx", "funding", ["curve", "inflation", "breaks", "desk"]],
      ["src/pages/InflationPage.tsx", "inflation", ["curve", "funding", "breaks", "desk"]],
      ["src/pages/BreaksPage.tsx", "breaks", ["curve", "funding", "inflation", "desk"]],
      ["src/pages/IndexPage.tsx", "desk", ["curve", "funding", "inflation", "breaks"]],
    ];
    for (const [rel, key, others] of expectations) {
      const page = readSource(rel);
      assert.ok(page.includes('syncKey="' + key + '"'), rel + " misses its " + key + " key");
      for (const other of others) {
        assert.ok(!page.includes('syncKey="' + other + '"'), rel + " leaks the " + other + " key");
      }
    }
  });

  it("renders four curve charts under one key with compare dashed separately", () => {
    const page = readSource("src/pages/CurvePage.tsx");
    const hits = page.match(/syncKey="curve"/g) ?? [];
    assert.equal(hits.length, 4);
    assert.ok(page.includes("dash: [6, 4]"), "compare series must dash apart from the solid zero");
  });

  it("pins chart render caps so crosshair alignment never allocates unbounded grids", () => {
    assert.ok(chart.includes("MAX_CHART_SERIES = 16"), "series cap drift");
    assert.ok(chart.includes("MAX_CHART_POINTS = 2000"), "point cap drift");
    assert.ok(chart.includes('role="img"'), "chart accessible name absent");
  });
});

describe("phase7 terminal full 55 row inflation table", () => {
  it("ships 55 unique components C01 to C55 in the mock snapshot", () => {
    const rows = mockSnapshot.observations.inflation.contributions;
    assert.equal(rows.length, 55);
    const ids = rows.map((row) => row.component_id);
    assert.equal(new Set(ids).size, 55);
    assert.ok(ids.includes("C01") && ids.includes("C55"), "component id range drift");
  });

  it("holds weights at 100 with per row recompute inside 0.01 pp", () => {
    const rows = mockSnapshot.observations.inflation.contributions;
    const weightTotal = rows.reduce((sum, row) => sum + row.weight_percent, 0);
    assert.ok(Math.abs(weightTotal - 100) < 1e-6, "weights sum " + weightTotal);
    let recomputed = 0;
    for (const row of rows) {
      const expected = (row.weight_percent * row.monthly_rate_percent) / 100;
      assert.ok(Math.abs(expected - row.contribution_pp) <= 0.01, "row recompute drift " + row.component_id);
      recomputed += expected;
    }
    const stored = mockSnapshot.observations.inflation.total_contribution_pp;
    assert.ok(Math.abs(stored - recomputed) <= 0.01, "stored total drift");
  });

  it("passes full snapshot validation with the 55 row experimental section", () => {
    assert.doesNotThrow(() => validateSnapshot(mockSnapshot, MOCK_DATE));
    assert.equal(mockSnapshot.observations.inflation.component_count, 55);
    assert.ok(
      mockSnapshot.observations.inflation.contributions.some(
        (row) => row.component_id === mockSnapshot.observations.inflation.latest.median_component
      ),
      "median component must name one table row"
    );
  });

  it("renders the full table sortable by rate, weight, and contribution with nulls last", () => {
    const page = readSource("src/pages/InflationPage.tsx");
    assert.ok(page.includes("component table"), "55 row expander caption absent");
    assert.ok(page.includes("component_count"), "expander must read the live component count");
    assert.ok(page.includes("sortable by rate, weight, or contribution"), "sortable contract caption absent");
    assert.ok(page.includes("nulls last"), "inflation table must promise nulls last");
    for (const key of ['key: "rate"', 'key: "weight"', 'key: "contrib"']) {
      assert.ok(page.includes(key), "inflation column absent: " + key);
    }
    assert.ok(page.includes("inflation-contributions.csv"), "inflation export filename absent");
  });
});
