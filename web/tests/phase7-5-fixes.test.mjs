import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { escapeCsvCell, toCsv } from "../src/lib/csv.ts";
import {
  compareCells,
  inferKind,
  isStrictTableDate,
  nextSortState,
  parseDateCell,
  parseNumericCell,
  sortRows,
} from "../src/lib/table-sort.ts";
import { canonicalSearch } from "../src/lib/asof.ts";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = dirname(here);
const readSource = (rel) => readFileSync(join(webRoot, rel), "utf8");

describe("phase7.5 medium1: csv formula injection guard", () => {
  it("prefixes one apostrophe on equals, plus, minus, and at triggers", () => {
    assert.equal(escapeCsvCell("=1+1"), "'=1+1");
    assert.equal(escapeCsvCell("+cmd"), "'+cmd");
    assert.equal(escapeCsvCell("-cmd"), "'-cmd");
    assert.equal(escapeCsvCell("@cmd"), "'@cmd");
  });

  it("detects the trigger past leading spaces and tabs", () => {
    assert.equal(escapeCsvCell("  =1+1"), "'  =1+1");
    assert.equal(escapeCsvCell("\t=1+1"), "'\t=1+1");
    assert.equal(escapeCsvCell(" \t +cmd"), "' \t +cmd");
  });

  it("leaves plain ledger cells untouched", () => {
    assert.equal(escapeCsvCell("3.92"), "3.92");
    assert.equal(escapeCsvCell("2Y"), "2Y");
    assert.equal(escapeCsvCell("NA"), "NA");
    assert.equal(escapeCsvCell(""), "");
  });

  it("quotes after guarding, so guarded commas still escape", () => {
    assert.equal(escapeCsvCell("=SUM(A1), note"), "\"'=SUM(A1), note\"");
    assert.equal(escapeCsvCell("a,b"), '"a,b"');
  });

  it("guards formula cells inside a built document", () => {
    const text = toCsv(
      [{ key: "tenor", header: "Tenor" }, { key: "zero", header: "Zero" }],
      [{ tenor: "2Y", zero: "=1+1" }]
    );
    assert.equal(text, "Tenor,Zero\r\n2Y,'=1+1\r\n");
  });
});

describe("phase7.5 low2: numeric full token plus strict dates first", () => {
  it("rejects ISO dates as numeric while keeping full tokens", () => {
    assert.equal(parseNumericCell("2026-10-30"), null);
    assert.equal(parseNumericCell("2026-09"), null);
    assert.equal(parseNumericCell("2Y"), null);
    assert.equal(parseNumericCell("10Y"), null);
    assert.equal(parseNumericCell("3.31"), 3.31);
    assert.equal(parseNumericCell("2026"), 2026);
  });

  it("keeps desk unit suffixes numeric with sign and exponent support", () => {
    assert.equal(parseNumericCell("3.31 pct"), 3.31);
    assert.equal(parseNumericCell("+10.0 bp"), 10.0);
    assert.equal(parseNumericCell("-2.5 pp"), -2.5);
    assert.ok(Math.abs((parseNumericCell("1e3") ?? 0) - 1000) < 1e-9);
    assert.equal(parseNumericCell("NA"), null);
    assert.equal(parseNumericCell(""), null);
  });

  it("recognizes strict calendar dates before numeric inference", () => {
    assert.equal(isStrictTableDate("2026-10-30"), true);
    assert.equal(isStrictTableDate("2026-09"), true);
    assert.equal(isStrictTableDate("3.31"), false);
    assert.equal(isStrictTableDate("2Y"), false);
    assert.equal(isStrictTableDate("2026-13-01"), false);
  });

  it("infers ISO date columns as dates, never as leading year numbers", () => {
    const rows = [{ d: "2026-10-28" }, { d: "2026-10-30" }, { d: "2026-10-29" }];
    assert.equal(inferKind("d", rows), "date");
    assert.equal(
      inferKind("v", [{ v: "3.31 pct" }, { v: "+10.0 bp" }, { v: "NA" }]),
      "number"
    );
    assert.equal(inferKind("t", [{ t: "2Y" }, { t: "10Y" }]), "string");
  });

  it("sorts strict dates chronologically once inferred", () => {
    const rows = [{ d: "2026-10-30" }, { d: "NA" }, { d: "2026-10-28" }];
    const ordered = sortRows(rows, [{ key: "d" }], { key: "d", dir: "asc" });
    assert.deepEqual(
      ordered.map((r) => r.d),
      ["2026-10-28", "2026-10-30", "NA"]
    );
  });

  it("still parses lenient dates for explicit date columns", () => {
    assert.ok((parseDateCell("2026-10-30") ?? Number.NaN) > 0);
    assert.equal(parseDateCell("NA"), null);
  });
});

describe("phase7.5 low3: sort click cycle helper", () => {
  it("cycles null to asc to desc to cleared on the same key", () => {
    assert.deepEqual(nextSortState(null, "rate"), { key: "rate", dir: "asc" });
    assert.deepEqual(nextSortState({ key: "rate", dir: "asc" }, "rate"), {
      key: "rate",
      dir: "desc",
    });
    assert.equal(nextSortState({ key: "rate", dir: "desc" }, "rate"), null);
  });

  it("restarts at asc when a different column is picked", () => {
    assert.deepEqual(nextSortState({ key: "rate", dir: "desc" }, "weight"), {
      key: "weight",
      dir: "asc",
    });
  });

  it("orders numbers with missing cells last in both directions", () => {
    const rows = [{ v: "NA" }, { v: "3.31 pct" }, { v: "+10.0 bp" }, { v: "1.00 pct" }];
    const cols = [{ key: "v", kind: "number" }];
    assert.deepEqual(
      sortRows(rows, cols, { key: "v", dir: "asc" }).map((r) => r.v),
      ["1.00 pct", "3.31 pct", "+10.0 bp", "NA"]
    );
    assert.deepEqual(
      sortRows(rows, cols, { key: "v", dir: "desc" }).map((r) => r.v),
      ["+10.0 bp", "3.31 pct", "1.00 pct", "NA"]
    );
  });

  it("returns the published order when the sort is cleared", () => {
    const rows = [{ v: "b" }, { v: "a" }];
    assert.equal(sortRows(rows, [{ key: "v" }], null), rows);
  });

  it("compares cells with nulls last before the direction flip", () => {
    assert.ok(compareCells("1.0", "NA", "number", "asc") < 0);
    assert.ok(compareCells("NA", "1.0", "number", "asc") > 0);
    assert.equal(compareCells("NA", "NA", "number", "asc"), 0);
  });
});

describe("phase7.5 low1: export follows the sorted row order", () => {
  it("renders the csv from sorted rows, not the published order", () => {
    const columns = [
      { key: "component", header: "Component" },
      { key: "rate", header: "Rate" },
    ];
    const rows = [
      { component: "C02", rate: "0.300" },
      { component: "C01", rate: "0.100" },
      { component: "C03", rate: "NA" },
    ];
    const sorted = sortRows(rows, [{ key: "rate", kind: "number" }], {
      key: "rate",
      dir: "asc",
    });
    assert.equal(
      toCsv(columns, sorted),
      "Component,Rate\r\nC01,0.100\r\nC02,0.300\r\nC03,NA\r\n"
    );
  });

  it("wires the export button to the sorted memo", () => {
    const source = readSource("src/components/DataTable.tsx");
    assert.ok(source.includes("rows={sortedRows()}"), "export must read the sorted memo");
    assert.ok(!source.includes("rows={props.rows}"), "unsorted export wiring remains");
  });
});

describe("phase7.5 medium3: canonical asof nav preserves compare", () => {
  it("carries both params in ledger order", () => {
    assert.equal(
      canonicalSearch("/curve", "2026-10-30", "2026-10-29"),
      "/curve?asof=2026-10-30&compare=2026-10-29"
    );
  });

  it("omits either param when absent", () => {
    assert.equal(canonicalSearch("/curve", "2026-10-30", null), "/curve?asof=2026-10-30");
    assert.equal(canonicalSearch("/curve", null, "2026-10-29"), "/curve?compare=2026-10-29");
    assert.equal(canonicalSearch("/curve", null, null), "/curve");
  });

  it("keeps the canonical redirect on the shared builder", () => {
    const app = readSource("src/App.tsx");
    assert.ok(app.includes("canonicalSearch"), "canonical builder absent");
    assert.ok(
      app.includes("canonicalSearch(location.pathname, r.asof, rawCompare || null)"),
      "canonical redirect drops compare"
    );
  });
});

describe("phase7.5 medium2: chart rebuilds on presentation change", () => {
  it("tracks a presentation signature beyond the series count", () => {
    const chart = readSource("src/components/Chart.tsx");
    assert.ok(chart.includes("lastSignature"), "signature state absent");
    assert.ok(chart.includes("sig !== lastSignature"), "signature compare absent");
    assert.ok(chart.includes("s.dash"), "dash absent from signature inputs");
    assert.ok(chart.includes("syncKey"), "sync key absent from signature inputs");
    assert.ok(chart.includes("xKind()"), "axis kind absent from signature inputs");
  });
});
