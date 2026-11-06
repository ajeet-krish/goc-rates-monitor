import { describe, it, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  RANGE_KEYS,
  DEFAULT_RANGE,
  isRangeKey,
  rangeCutoff,
} from "../src/lib/history-range.ts";
import {
  granularityFor,
  aggregateSeries,
  aggregationLabel,
} from "../src/lib/aggregate.ts";
import { percentileSummary } from "../src/lib/percentiles.ts";
import { inversionBands } from "../src/lib/regimes.ts";
import { dateToEpochSec } from "../src/lib/history.ts";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = dirname(here);

/** Epoch seconds of a YYYY-MM-DD date at UTC midnight. */
const day = (isoDate) => dateToEpochSec(isoDate);

const DAY_SEC = 86400;
const DEFAULT_FILL = "rgba(164, 74, 42, 0.10)";

/** Minimal daily row carrying only the fields the regime bands read. */
function slopeRow(date, slope) {
  const slopes_bp = {};
  if (slope !== undefined) slopes_bp["2Y_10Y"] = slope;
  return { date, slopes_bp };
}

/** Ascending series of count points with y equal to x, x from 1 to count. */
function ascendingSeries(count) {
  return Array.from({ length: count }, (_, i) => ({ x: i + 1, y: i + 1 }));
}

describe("phase8.3 range cutoffs", () => {
  it("subtracts calendar years in UTC from the latest epoch", () => {
    const latest = day("2026-11-05");
    assert.equal(rangeCutoff("1Y", latest), day("2025-11-05"));
    assert.equal(rangeCutoff("3Y", latest), day("2023-11-05"));
    assert.equal(rangeCutoff("5Y", latest), day("2021-11-05"));
    assert.equal(rangeCutoff("10Y", latest), day("2016-11-05"));
    assert.equal(rangeCutoff("1Y", day("2028-03-01")), day("2027-03-01"));
  });

  it("clamps month ends: 2028-02-29 minus 1Y is 2027-02-28", () => {
    assert.equal(rangeCutoff("1Y", day("2028-02-29")), day("2027-02-28"));
    assert.equal(rangeCutoff("3Y", day("2028-02-29")), day("2025-02-28"));
    assert.equal(rangeCutoff("5Y", day("2028-02-29")), day("2023-02-28"));
    assert.equal(rangeCutoff("1Y", day("2028-01-31")), day("2027-01-31"));
  });

  it("returns null for Max and for a non finite latest", () => {
    assert.equal(rangeCutoff("Max", day("2026-11-05")), null);
    assert.equal(rangeCutoff("1Y", Number.NaN), null);
    assert.equal(rangeCutoff("10Y", Number.POSITIVE_INFINITY), null);
  });

  it("returns null for keys that only exist on Object.prototype", () => {
    const latest = day("2026-11-05");
    assert.equal(rangeCutoff("constructor", latest), null);
    assert.equal(rangeCutoff("toString", latest), null);
    assert.equal(rangeCutoff("hasOwnProperty", latest), null);
  });

  it("returns null when the cutoff is outside the representable Date range", () => {
    // 1e13 seconds is finite but one year earlier lands past the Date range.
    assert.equal(rangeCutoff("1Y", 1e13), null);
    assert.equal(rangeCutoff("10Y", 1e13), null);
    assert.equal(rangeCutoff("1Y", Number.MAX_VALUE), null);
  });

  it("does not clamp up from 2029-02-28 to leap day 2028-02-29", () => {
    assert.equal(rangeCutoff("1Y", day("2029-02-28")), day("2028-02-28"));
    assert.equal(rangeCutoff("3Y", day("2029-02-28")), day("2026-02-28"));
  });

  it("keeps the cutoff day itself: the cutoff is inclusive", () => {
    const latest = day("2026-11-05");
    const cutoff = rangeCutoff("1Y", latest);
    assert.equal(typeof cutoff, "number");
    const kept = [cutoff - DAY_SEC, cutoff, cutoff + DAY_SEC, latest].filter(
      (x) => x >= cutoff
    );
    assert.deepEqual(kept, [cutoff, cutoff + DAY_SEC, latest]);
  });
});

describe("phase8.3 range signal and persistence", () => {
  const rangeModuleUrl = new URL("../src/lib/history-range.ts", import.meta.url).href;
  let loadCount = 0;

  function installMockStorage(initialStored) {
    const backing = new Map();
    if (initialStored !== undefined) backing.set("goc-history-range", initialStored);
    globalThis.sessionStorage = {
      getItem: (key) => (backing.has(key) ? backing.get(key) : null),
      setItem: (key, value) => backing.set(key, String(value)),
      removeItem: (key) => backing.delete(key),
      clear: () => backing.clear(),
    };
    return backing;
  }

  async function loadRangeModule(initialStored) {
    const backing = installMockStorage(initialStored);
    loadCount += 1;
    const mod = await import(rangeModuleUrl + "?load=" + loadCount);
    return { mod, backing };
  }

  afterEach(() => {
    delete globalThis.sessionStorage;
  });

  it("lists range keys in display order with a 3Y default", () => {
    assert.deepEqual([...RANGE_KEYS], ["1Y", "3Y", "5Y", "10Y", "Max"]);
    assert.equal(DEFAULT_RANGE, "3Y");
  });

  it("defaults to 3Y when storage holds nothing", async () => {
    const { mod } = await loadRangeModule();
    assert.equal(mod.rangeKey(), "3Y");
  });

  it("reads a valid stored range on module init", async () => {
    const { mod } = await loadRangeModule("10Y");
    assert.equal(mod.rangeKey(), "10Y");
  });

  it("falls back to 3Y when the stored value is garbage", async () => {
    const { mod, backing } = await loadRangeModule("banana");
    assert.equal(mod.rangeKey(), "3Y");
    assert.equal(isRangeKey("banana"), false);
    assert.equal(isRangeKey("Max"), true);
    mod.setRangeKey("5Y");
    assert.equal(backing.get("goc-history-range"), "5Y");
  });

  it("persists setter writes through sessionStorage", async () => {
    const { mod, backing } = await loadRangeModule();
    mod.setRangeKey("10Y");
    assert.equal(mod.rangeKey(), "10Y");
    assert.equal(backing.get("goc-history-range"), "10Y");
  });

  it("stays in memory when sessionStorage is missing", async () => {
    delete globalThis.sessionStorage;
    loadCount += 1;
    const mod = await import(rangeModuleUrl + "?load=" + loadCount);
    assert.equal(mod.rangeKey(), "3Y");
    mod.setRangeKey("1Y");
    assert.equal(mod.rangeKey(), "1Y");
  });

  it("never throws when storage access throws", async () => {
    globalThis.sessionStorage = {
      getItem: () => {
        throw new Error("blocked read");
      },
      setItem: () => {
        throw new Error("blocked write");
      },
    };
    loadCount += 1;
    const mod = await import(rangeModuleUrl + "?load=" + loadCount);
    assert.equal(mod.rangeKey(), "3Y");
    mod.setRangeKey("5Y");
    assert.equal(mod.rangeKey(), "5Y");
  });
});

describe("phase8.3 aggregation", () => {
  it("maps ranges to granularity: daily only for 1Y", () => {
    assert.equal(granularityFor("1Y"), "daily");
    assert.equal(granularityFor("3Y"), "weekly");
    assert.equal(granularityFor("5Y"), "weekly");
    assert.equal(granularityFor("10Y"), "weekly");
    assert.equal(granularityFor("Max"), "weekly");
  });

  it("buckets weekly at the UTC Monday epoch with means of finite values only", () => {
    const mondayA = day("2026-01-05");
    const mondayB = day("2026-01-12");
    assert.equal(new Date(mondayA * 1000).getUTCDay(), 1);
    assert.equal(new Date(mondayB * 1000).getUTCDay(), 1);
    const points = [
      { x: day("2026-01-05"), y: 2 },
      { x: day("2026-01-07"), y: 4 },
      { x: day("2026-01-11"), y: 6 },
      { x: day("2026-01-12"), y: null },
      { x: day("2026-01-13"), y: 9 },
      { x: day("2026-01-15"), y: 3 },
      { x: day("2026-01-19"), y: null },
      { x: day("2026-01-20"), y: null },
    ];
    const weekly = aggregateSeries(points, "weekly");
    assert.deepEqual(weekly, [
      { x: mondayA, y: 4 },
      { x: mondayB, y: 6 },
    ]);
    assert.ok(
      weekly.every((p) => typeof p.y === "number"),
      "weekly buckets never emit null y, all null buckets are dropped"
    );
  });

  it("returns the same array reference for daily passthrough", () => {
    const points = [{ x: day("2026-01-05"), y: 2 }];
    assert.equal(aggregateSeries(points, "daily"), points);
  });

  it("drops a weekly bucket whose mean would overflow to Infinity", () => {
    const monday = day("2026-01-05");
    const points = [
      { x: monday, y: 1e308 },
      { x: monday + DAY_SEC, y: 1e308 },
    ];
    assert.deepEqual(aggregateSeries(points, "weekly"), []);
  });

  it("skips points whose epoch does not round trip through Date", () => {
    const points = [
      { x: 1e13, y: 5 },
      { x: -1e13, y: 7 },
      { x: day("2026-01-05"), y: 2 },
    ];
    const weekly = aggregateSeries(points, "weekly");
    assert.deepEqual(weekly, [{ x: day("2026-01-05"), y: 2 }]);
    assert.ok(weekly.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y)));
  });

  it("sorts unsorted input and never emits duplicate x", () => {
    const points = [
      { x: day("2026-01-13"), y: 9 },
      { x: day("2026-01-05"), y: 2 },
      { x: day("2026-01-12"), y: 4 },
      { x: day("2026-01-06"), y: 8 },
      { x: day("2026-01-19"), y: 1 },
    ];
    const weekly = aggregateSeries(points, "weekly");
    const xs = weekly.map((p) => p.x);
    assert.equal(weekly.length, 3);
    assert.deepEqual(xs, [...xs].sort((a, b) => a - b));
    assert.equal(new Set(xs).size, xs.length);
  });

  it("prints the exact on screen labels", () => {
    assert.equal(aggregationLabel("daily"), "daily prints");
    assert.equal(aggregationLabel("weekly"), "weekly mean (UTC Monday buckets)");
  });

  it("keeps 2750 daily rows under MAX_CHART_POINTS after weekly aggregation", () => {
    const chartSource = readFileSync(
      join(webRoot, "src", "components", "Chart.tsx"),
      "utf8"
    );
    const capMatch = chartSource.match(/^export const MAX_CHART_POINTS = (\d+);$/m);
    assert.ok(capMatch, "MAX_CHART_POINTS declaration missing");
    const maxChartPoints = Number(capMatch[1]);
    assert.equal(maxChartPoints, 2000);
    const base = day("2016-01-04");
    let worst = 0;
    for (let startOffset = 0; startOffset < 7; startOffset++) {
      const start = base + startOffset * DAY_SEC;
      const points = [];
      for (let i = 0; i < 2750; i++) {
        points.push({ x: start + i * DAY_SEC, y: i % 40 });
      }
      const weekly = aggregateSeries(points, "weekly");
      if (weekly.length > worst) worst = weekly.length;
    }
    // ceil(2750 / 7) = 393 full weeks, plus at most one extra partial week
    // when the span starts mid week, so 394 is the true upper bound.
    assert.ok(worst <= 394, "expected at most 394 weekly buckets, got " + worst);
    assert.ok(
      worst < maxChartPoints,
      "weekly buckets must stay under MAX_CHART_POINTS for the Phase 8.4 contract"
    );
  });
});

describe("phase8.3 percentiles", () => {
  it("computes nearest rank p10, p50, p90 on a 100 value series", () => {
    const summary = percentileSummary(ascendingSeries(100));
    assert.ok(summary);
    // Index ceil(k * n) over sorted 1 to 100 gives 10, 50, 90, so the
    // values are 11, 51, 91.
    assert.equal(summary.p10, 11);
    assert.equal(summary.p50, 51);
    assert.equal(summary.p90, 91);
    assert.equal(summary.latest, 100);
    assert.equal(summary.latestRankPercent, 100);
    assert.equal(summary.count, 100);
  });

  it("returns null below minCount and at zero finite values", () => {
    assert.equal(percentileSummary(ascendingSeries(59)), null);
    assert.ok(percentileSummary(ascendingSeries(60)));
    assert.equal(percentileSummary(ascendingSeries(60), 61), null);
    assert.equal(percentileSummary([]), null);
  });

  it("nulls latest and rank when the newest point has no finite y", () => {
    const points = ascendingSeries(70);
    points[points.length - 1] = { x: 70, y: null };
    const summary = percentileSummary(points);
    assert.ok(summary);
    assert.equal(summary.latest, null);
    assert.equal(summary.latestRankPercent, null);
    assert.equal(summary.count, 69);
    // Sorted 1 to 69: p50 at index ceil(0.5 * 69) = 35 gives 36.
    assert.equal(summary.p50, 36);
  });

  it("ranks the latest value as the percent of finite values at or below it", () => {
    const points = ascendingSeries(100);
    points.find((p) => p.x === 50).y = 100;
    points.find((p) => p.x === 100).y = 50;
    const summary = percentileSummary(points);
    assert.ok(summary);
    assert.equal(summary.latest, 50);
    // Values 1 to 50 sit at or below 50 out of 100 finite values.
    assert.equal(summary.latestRankPercent, 50);
    assert.equal(summary.count, 100);
    assert.equal(summary.p10, 11);
  });

  it("ignores non finite y values in the count", () => {
    const points = ascendingSeries(70);
    points[0] = { x: 1, y: Number.NaN };
    points[1] = { x: 2, y: Number.POSITIVE_INFINITY };
    const summary = percentileSummary(points);
    assert.ok(summary);
    assert.equal(summary.count, 68);
  });

  it("pins the first point at the greatest x when x ties, even with a null y", () => {
    const points = ascendingSeries(69);
    points.push({ x: 70, y: null });
    points.push({ x: 70, y: 42 });
    const summary = percentileSummary(points);
    assert.ok(summary);
    // The documented rule keeps the first point at the tied greatest x, so a
    // null y there wins over the later finite y and latest stays null.
    assert.equal(summary.latest, null);
    assert.equal(summary.latestRankPercent, null);
    assert.equal(summary.count, 70);
    // Sorted 1 to 41, then 42 twice, then 43 to 69: p50 at index 35 gives 36.
    assert.equal(summary.p50, 36);
  });
});

describe("phase8.3 inversion regimes", () => {
  const rows = [
    slopeRow("2026-01-01", -5),
    slopeRow("2026-01-02", -2),
    slopeRow("2026-01-03", 0),
    slopeRow("2026-01-04", -3),
    slopeRow("2026-01-05"),
    slopeRow("2026-01-06", -1),
    slopeRow("2026-01-07", 2),
    slopeRow("2026-01-08", 1),
  ];

  it("finds maximal runs with zero and missing slopes breaking the run", () => {
    const bands = inversionBands(rows, null);
    assert.deepEqual(bands, [
      { x0: day("2026-01-01"), x1: day("2026-01-02") + DAY_SEC, fill: DEFAULT_FILL },
      { x0: day("2026-01-04"), x1: day("2026-01-04") + DAY_SEC, fill: DEFAULT_FILL },
      { x0: day("2026-01-06"), x1: day("2026-01-06") + DAY_SEC, fill: DEFAULT_FILL },
    ]);
  });

  it("returns ascending bands with x0 strictly below x1", () => {
    const bands = inversionBands(rows, null);
    assert.ok(bands.length >= 3);
    for (let i = 0; i < bands.length; i++) {
      assert.ok(bands[i].x0 < bands[i].x1);
      if (i > 0) assert.ok(bands[i - 1].x0 < bands[i].x0);
    }
  });

  it("keeps only rows at or after an inclusive cutoff", () => {
    const cutoff = day("2026-01-05");
    assert.deepEqual(inversionBands(rows, cutoff), [
      { x0: day("2026-01-06"), x1: day("2026-01-06") + DAY_SEC, fill: DEFAULT_FILL },
    ]);
    // The day at the cutoff itself stays inside the window.
    const atCutoff = inversionBands(rows, day("2026-01-02"));
    assert.equal(atCutoff.length, 3);
    assert.equal(atCutoff[0].x0, day("2026-01-02"));
    assert.equal(atCutoff[0].x1, day("2026-01-02") + DAY_SEC);
    assert.deepEqual(inversionBands(rows, day("2026-01-09")), []);
  });

  it("never bands a zero or positive slope on its own", () => {
    const flat = [slopeRow("2026-02-02", 0), slopeRow("2026-02-03", 1)];
    assert.deepEqual(inversionBands(flat, null), []);
  });

  it("honours a custom fill", () => {
    const bands = inversionBands(rows, null, "rgba(0, 0, 255, 0.20)");
    assert.equal(bands.length, 3);
    for (const band of bands) assert.equal(band.fill, "rgba(0, 0, 255, 0.20)");
  });
});
