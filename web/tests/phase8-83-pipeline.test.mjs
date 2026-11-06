import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { RANGE_KEYS, rangeCutoff } from "../src/lib/history-range.ts";
import {
  granularityFor,
  aggregateSeries,
  aggregationLabel,
} from "../src/lib/aggregate.ts";
import { percentileSummary } from "../src/lib/percentiles.ts";
import { inversionBands } from "../src/lib/regimes.ts";
import { dateToEpochSec, slopeSeries } from "../src/lib/history.ts";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = dirname(here);

const DAY_SEC = 86400;
const DEFAULT_FILL = "rgba(164, 74, 42, 0.10)";

/** Epoch seconds of a YYYY-MM-DD date at UTC midnight. */
const day = (isoDate) => dateToEpochSec(isoDate);

/** MAX_CHART_POINTS read from the chart component, same pattern as phase8-range. */
function maxChartPoints() {
  const source = readFileSync(
    join(webRoot, "src", "components", "Chart.tsx"),
    "utf8"
  );
  const match = source.match(/^export const MAX_CHART_POINTS = (\d+);$/m);
  assert.ok(match, "MAX_CHART_POINTS declaration missing");
  return Number(match[1]);
}

/** True for Monday through Friday, matching the weekday only backfill shape. */
function isWeekday(ms) {
  const dow = new Date(ms).getUTCDay();
  return dow !== 0 && dow !== 6;
}

function isoOf(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

/** Ascending weekday dates from fromISO to toISO inclusive. */
function weekdayRange(fromISO, toISO) {
  const out = [];
  let ms = day(fromISO) * 1000;
  const end = day(toISO) * 1000;
  while (ms <= end) {
    if (isWeekday(ms)) out.push(isoOf(ms));
    ms += DAY_SEC * 1000;
  }
  return out;
}

/**
 * 300 weekday rows over about 14 months, 2025-09-01 through 2026-10-23.
 * The 2Y_10Y slope is positive by default with four negative runs: one
 * entirely before the 1Y cutoff, one long run inside the window, one single
 * day run inside the window, and one short run inside the window. Five
 * window rows carry a null slope so the percentile count must drop them.
 */
function buildSyntheticRows() {
  const slopeByDate = new Map();
  for (const date of weekdayRange("2026-03-02", "2026-03-27")) {
    slopeByDate.set(date, -5);
  }
  slopeByDate.set("2026-04-20", -1);
  for (const date of weekdayRange("2026-05-04", "2026-05-08")) {
    slopeByDate.set(date, -2);
  }
  for (const date of weekdayRange("2025-09-08", "2025-09-19")) {
    slopeByDate.set(date, -7);
  }
  for (const date of [
    "2025-12-10",
    "2026-01-14",
    "2026-04-15",
    "2026-06-10",
    "2026-08-05",
  ]) {
    slopeByDate.set(date, null);
  }
  const rows = [];
  let ms = Date.UTC(2025, 8, 1); // Monday 2025-09-01.
  while (rows.length < 300) {
    if (isWeekday(ms)) {
      const date = isoOf(ms);
      const slope = slopeByDate.has(date)
        ? slopeByDate.get(date)
        : 15 + (rows.length % 17);
      rows.push({ date, slopes_bp: { "2Y_10Y": slope } });
    }
    ms += DAY_SEC * 1000;
  }
  return rows;
}

// The Phase 8.4 pipeline in pure form: range filter, then weekly buckets,
// then percentiles over the unaggregated window, then bands on the window.
const syntheticRows = buildSyntheticRows();
const syntheticPoints = syntheticRows.map((row) => ({
  x: dateToEpochSec(row.date),
  y: row.slopes_bp["2Y_10Y"],
}));
const latestEpoch = syntheticPoints[syntheticPoints.length - 1].x;
const cutoff1Y = rangeCutoff("1Y", latestEpoch);
const windowRows = syntheticRows.filter(
  (row) => dateToEpochSec(row.date) >= cutoff1Y
);
const windowPoints = syntheticPoints.filter((point) => point.x >= cutoff1Y);
const weeklyWindow = aggregateSeries(windowPoints, "weekly");

describe("phase8.3 cross module pipeline on a synthetic history", () => {
  it("builds 300 weekday rows over about 14 months with an inclusive 1Y window", () => {
    assert.equal(syntheticRows.length, 300);
    const spanDays = (latestEpoch - syntheticPoints[0].x) / DAY_SEC + 1;
    assert.ok(
      spanDays >= 410 && spanDays <= 430,
      "expected about 14 months, got " + spanDays + " days"
    );
    assert.equal(cutoff1Y, day("2025-10-23"));
    assert.equal(
      windowRows[0].date,
      "2025-10-23",
      "the cutoff day itself stays in the window"
    );
    assert.equal(windowRows.length, 262);
    assert.ok(windowRows.length < syntheticRows.length);
  });

  it("keeps weekly buckets at or below the daily window count and under the chart cap", () => {
    const cap = maxChartPoints();
    assert.equal(cap, 2000);
    assert.equal(
      weeklyWindow.length,
      53,
      "262 weekday rows over 53 UTC Monday weeks"
    );
    assert.ok(
      weeklyWindow.length <= windowPoints.length,
      "weekly bucket count must not exceed the daily window count"
    );
    assert.ok(
      weeklyWindow.length < cap,
      "weekly buckets must stay under MAX_CHART_POINTS for the Phase 8.4 contract"
    );
    const xs = weeklyWindow.map((point) => point.x);
    assert.deepEqual(xs, [...xs].sort((a, b) => a - b));
    assert.equal(new Set(xs).size, xs.length, "weekly buckets never duplicate x");
    assert.ok(
      weeklyWindow.every(
        (point) => typeof point.y === "number" && Number.isFinite(point.y)
      ),
      "weekly buckets carry finite means only"
    );
  });

  it("counts non null daily window values in the percentile summary, not weekly buckets", () => {
    const summary = percentileSummary(windowPoints);
    assert.ok(summary, "262 window rows clear the 60 value minimum");
    const nonNullCount = windowPoints.filter(
      (point) => typeof point.y === "number" && Number.isFinite(point.y)
    ).length;
    assert.equal(
      nonNullCount,
      windowRows.length - 5,
      "exactly five window rows carry a null slope"
    );
    assert.equal(
      summary.count,
      nonNullCount,
      "percentiles run over the unaggregated window per the approved plan"
    );
    assert.ok(
      summary.count > weeklyWindow.length,
      "the count must come from daily rows, never from the weekly buckets"
    );
    assert.ok(summary.p10 <= summary.p50, "p10 must not exceed p50");
    assert.ok(summary.p50 <= summary.p90, "p50 must not exceed p90");
  });

  it("bands every negative run inside the window and keeps spans inside it", () => {
    const bands = inversionBands(windowRows, cutoff1Y);
    assert.deepEqual(bands, [
      {
        x0: day("2026-03-02"),
        x1: day("2026-03-27") + DAY_SEC,
        fill: DEFAULT_FILL,
      },
      {
        x0: day("2026-04-20"),
        x1: day("2026-04-20") + DAY_SEC,
        fill: DEFAULT_FILL,
      },
      {
        x0: day("2026-05-04"),
        x1: day("2026-05-08") + DAY_SEC,
        fill: DEFAULT_FILL,
      },
    ]);
    const lastWindowDay = windowPoints[windowPoints.length - 1].x;
    for (let i = 0; i < bands.length; i++) {
      assert.ok(bands[i].x0 < bands[i].x1, "every band spans a positive width");
      assert.ok(bands[i].x0 >= cutoff1Y, "every band starts inside the window");
      assert.ok(
        bands[i].x1 <= lastWindowDay + DAY_SEC,
        "every band ends inside the window"
      );
      if (i > 0) {
        assert.ok(bands[i - 1].x0 < bands[i].x0, "bands ascend by x0");
        assert.ok(bands[i].x0 >= bands[i - 1].x1, "bands never overlap");
      }
    }
  });

  it("drops the pre window inversion run only through the range cutoff", () => {
    const fullSeries = inversionBands(syntheticRows, null);
    assert.equal(
      fullSeries.length,
      4,
      "the full series carries one extra run before the cutoff"
    );
    assert.equal(fullSeries[0].x0, day("2025-09-08"));
    assert.equal(fullSeries[0].x1, day("2025-09-19") + DAY_SEC);
    assert.ok(
      fullSeries[0].x1 <= cutoff1Y,
      "the pre window run sits entirely before the cutoff"
    );
    const windowed = inversionBands(syntheticRows, cutoff1Y);
    assert.equal(windowed.length, 3, "the cutoff trims exactly one run");
    assert.equal(windowed[0].x0, day("2026-03-02"));
  });
});

// The same pipeline at Max range on the real committed artifact.
const historyPath = join(webRoot, "public", "data", "history.json");
const history = JSON.parse(readFileSync(historyPath, "utf8"));
const dailyRows = history.daily;
const dailyPoints = slopeSeries(history, "2Y_10Y");
const firstDayX = dailyPoints[0].x;
const lastDayX = dailyPoints[dailyPoints.length - 1].x;
const nullSlopeCount = dailyPoints.filter((point) => point.y === null).length;
const finiteSlopeCount = dailyPoints.length - nullSlopeCount;
const spanDays = (lastDayX - firstDayX) / DAY_SEC + 1;

describe("phase8.3 real published history pipeline at Max range", () => {
  it("reads the committed 2494 row history with a finite 2Y_10Y slope on every row", () => {
    assert.equal(dailyRows.length, 2494);
    assert.equal(history.metadata.daily_count, 2494);
    assert.equal(
      nullSlopeCount,
      0,
      "every committed row carries a 2Y_10Y slope"
    );
    assert.equal(finiteSlopeCount, 2494);
    assert.equal(
      rangeCutoff("Max", lastDayX),
      null,
      "Max never cuts the window"
    );
  });

  it("aggregates the full daily series to weekly buckets under the chart cap", () => {
    const cap = maxChartPoints();
    const weekly = aggregateSeries(dailyPoints, granularityFor("Max"));
    assert.ok(
      weekly.length <= finiteSlopeCount,
      "bucket count must not exceed the daily row count"
    );
    assert.ok(
      weekly.length < cap,
      "weekly buckets must stay under MAX_CHART_POINTS for the Phase 8.4 contract"
    );
    // The consecutive day model gives ceil(2750 / 7) + 1 = 394, but the
    // committed history holds business days only: 2494 rows span 3654
    // calendar days and touch every UTC Monday week. The structural bound is
    // ceil(span / 7) + 1, and the current artifact lands exactly on it.
    const structuralBound = Math.ceil(spanDays / 7) + 1;
    assert.equal(spanDays, 3654);
    assert.equal(structuralBound, 523);
    assert.ok(
      weekly.length <= structuralBound,
      "expected at most " + structuralBound + " weekly buckets, got " + weekly.length
    );
    assert.equal(
      weekly.length,
      523,
      "current artifact pin: business days across the ten year span"
    );
    const xs = weekly.map((point) => point.x);
    assert.deepEqual(xs, [...xs].sort((a, b) => a - b));
    assert.equal(new Set(xs).size, xs.length);
  });

  it("summarizes percentiles over the full unaggregated daily series", () => {
    const summary = percentileSummary(dailyPoints);
    assert.ok(summary, "the full history clears the 60 value minimum");
    assert.equal(summary.count, dailyRows.length - nullSlopeCount);
    assert.equal(
      summary.count,
      2494,
      "2494 rows minus zero rows with a null slope"
    );
    assert.ok(summary.p10 <= summary.p50, "p10 must not exceed p50");
    assert.ok(summary.p50 <= summary.p90, "p50 must not exceed p90");
    assert.ok(
      typeof summary.latest === "number" && Number.isFinite(summary.latest),
      "the newest row carries a finite slope"
    );
    assert.ok(summary.latestRankPercent >= 0 && summary.latestRankPercent <= 100);
  });

  it("finds ascending non overlapping inversion bands with a two day minimum gap", () => {
    const bands = inversionBands(dailyRows, null);
    assert.ok(bands.length >= 1, "the committed history carries inversion runs");
    assert.ok(
      bands[bands.length - 1].x1 <= lastDayX + DAY_SEC,
      "the last band ends inside the history window"
    );
    for (let i = 0; i < bands.length; i++) {
      assert.ok(bands[i].x0 < bands[i].x1, "every band spans a positive width");
      assert.ok(bands[i].x0 >= firstDayX, "every band starts inside the history");
      if (i > 0) {
        const gapDays = (bands[i].x0 - bands[i - 1].x1) / DAY_SEC;
        assert.ok(
          gapDays >= 2,
          "gap between band " + (i - 1) + " and band " + i + " is " +
            gapDays +
            " days, expected at least 2"
        );
        assert.ok(bands[i].x0 > bands[i - 1].x0, "bands ascend by x0");
      }
    }
  });
});

describe("phase8.3 label and aggregation wiring for phase 8.4", () => {
  const sample = [
    { x: day("2026-01-05"), y: 2 },
    { x: day("2026-01-07"), y: 4 },
    { x: day("2026-01-12"), y: 6 },
  ];

  it("pins daily granularity for 1Y and weekly for every other range key", () => {
    assert.equal(granularityFor("1Y"), "daily");
    for (const key of ["3Y", "5Y", "10Y", "Max"]) {
      assert.equal(granularityFor(key), "weekly", key);
    }
  });

  it("wires each range key to its aggregation behavior and on screen label", () => {
    assert.deepEqual([...RANGE_KEYS], ["1Y", "3Y", "5Y", "10Y", "Max"]);
    for (const key of RANGE_KEYS) {
      const granularity = granularityFor(key);
      assert.equal(granularity, key === "1Y" ? "daily" : "weekly", key);
      const aggregated = aggregateSeries(sample, granularity);
      if (granularity === "daily") {
        assert.equal(
          aggregated,
          sample,
          key + " daily passthrough returns the same reference"
        );
      } else {
        assert.equal(
          aggregated.length,
          2,
          key + " weekly buckets the two UTC Monday weeks"
        );
        assert.ok(
          aggregated.every((point) => typeof point.y === "number"),
          key + " weekly buckets carry finite means"
        );
      }
      assert.equal(
        aggregationLabel(granularity),
        granularity === "daily"
          ? "daily prints"
          : "weekly mean (UTC Monday buckets)",
        key
      );
    }
  });
});
