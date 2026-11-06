import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { RANGE_KEYS, rangeCutoff } from "../src/lib/history-range.ts";
import { aggregationLabel, granularityFor } from "../src/lib/aggregate.ts";
import { percentileSummary } from "../src/lib/percentiles.ts";
import { dateToEpochSec } from "../src/lib/history.ts";
import {
  aggregationNote,
  cpiAggregationNote,
  historyWindow,
  joinNote,
  latestDailyEpoch,
  percentileCaption,
  windowBands,
  windowCpiSeries,
  windowSeries,
} from "../src/lib/history-window.ts";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = dirname(here);
const readSource = (rel) => readFileSync(join(webRoot, rel), "utf8");

const DAY_SEC = 86400;

/** Epoch seconds of a YYYY-MM-DD date at UTC midnight. */
const day = (isoDate) => dateToEpochSec(isoDate);

/** Ascending dates from fromISO to toISO, both inclusive. */
function dayRange(fromISO, toISO) {
  const out = [];
  let ms = Date.parse(fromISO + "T00:00:00Z");
  const end = Date.parse(toISO + "T00:00:00Z");
  while (ms <= end) {
    out.push(new Date(ms).toISOString().slice(0, 10));
    ms += DAY_SEC * 1000;
  }
  return out;
}

/** Ascending YYYY-MM months from fromMonth to toMonth, both inclusive. */
function monthRange(fromMonth, toMonth) {
  const out = [];
  const [startYear, startMonth] = fromMonth.split("-").map(Number);
  const [endYear, endMonth] = toMonth.split("-").map(Number);
  let year = startYear;
  let month = startMonth;
  while (year < endYear || (year === endYear && month <= endMonth)) {
    out.push(String(year).padStart(4, "0") + "-" + String(month).padStart(2, "0"));
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
  }
  return out;
}

/** Daily row carrying the fields the window helpers and picks read. */
function dailyRow(date, verified, values = {}) {
  return {
    date,
    yields_percent: {
      "2Y": values.y2 ?? null,
      "5Y": null,
      "10Y": values.y10 ?? null,
      "30Y": null,
    },
    yields_unit: "percent",
    slopes_bp: {
      "2Y_5Y": 0,
      "2Y_10Y": values.slope ?? null,
      "5Y_30Y": 0,
      "10Y_30Y": 0,
    },
    slopes_unit: "basis_points",
    spreads_bp: { "2Y": null, "5Y": null, "10Y": values.spread ?? null, "30Y": null },
    spreads_unit: "basis_points",
    spreads_status: "ok",
    switch_in_window: false,
    switch_by_tenor: { "2Y": false, "5Y": false, "10Y": false, "30Y": false },
    calendar_gap: false,
    verified,
    source: verified ? "derived:history_verified_v1" : "derived:backfill_v1",
    snapshot_sha256: null,
    input_digest_sha256: null,
    row_digest: "d",
  };
}

/** Monthly CPI row carrying the fields the CPI window helper reads. */
function cpiRow(month, verified, trim, median) {
  return {
    month,
    trim_mom_percent: trim,
    median_mom_percent: median,
    median_component: "C32",
    trim_yoy_percent: null,
    median_yoy_percent: null,
    mom_unit: "percent_per_month",
    yoy_unit: "percent",
    verified,
    source: verified ? "derived:history_verified_v1" : "derived:backfill_v1",
    snapshot_sha256: null,
    row_digest: "d",
  };
}

function buildHistory(dailyRows, cpiRows = []) {
  return {
    metadata: {
      asof: "2026-11-04",
      schema_version: 2,
      method: "history_merge_v1",
      daily_count: dailyRows.length,
      daily_count_unit: "count",
      cpi_count: cpiRows.length,
      cpi_count_unit: "count",
    },
    daily: dailyRows,
    cpi: cpiRows,
    provenance: {},
    exclusions: [],
  };
}

const pick2Y = (row) => row.yields_percent["2Y"];
const pickSlope = (row) => row.slopes_bp["2Y_10Y"];
const pickTrim = (row) => row.trim_mom_percent;

/**
 * 430 consecutive daily rows from 2025-09-01 to 2026-11-04, so the 1Y
 * cutoff lands inside the source instead of before it. Every seventh row is
 * backfilled so both provenance spans exist, the 2Y yield never goes null,
 * the 10Y spread goes null on every eleventh row, and one negative 2s10s
 * run sits inside the 1Y window for the shading test.
 */
function buildWindowRows() {
  const dates = dayRange("2025-09-01", "2026-11-04");
  return dates.map((date, i) =>
    dailyRow(date, i % 7 !== 3, {
      y2: 3 + (i % 10) * 0.1,
      y10: 4 + (i % 10) * 0.1,
      spread: i % 11 === 0 ? null : 15 + (i % 6),
      slope: date >= "2026-03-02" && date <= "2026-03-06" ? -4 : 12,
    })
  );
}

const windowRows = buildWindowRows();
const windowHistory = buildHistory(windowRows);

describe("phase8.4 range window wiring", () => {
  it("reads the newest daily row at midnight and windows 1Y daily with an inclusive cutoff", () => {
    assert.equal(latestDailyEpoch(windowHistory), day("2026-11-04"));
    assert.equal(latestDailyEpoch(null), null);
    assert.equal(latestDailyEpoch(buildHistory([])), null);

    const spans = windowSeries(windowHistory, "1Y", pick2Y);
    assert.equal(spans.granularity, "daily");
    assert.equal(spans.label, aggregationLabel("daily"));
    assert.equal(spans.label, "daily prints");
    assert.equal(spans.cutoff, rangeCutoff("1Y", latestDailyEpoch(windowHistory)));
    assert.equal(spans.cutoff, day("2025-11-04"));
    assert.equal(spans.rows[0].date, "2025-11-04", "the cutoff day itself stays in the window");
    assert.equal(spans.windowPoints[0].x, day("2025-11-04"));
    assert.ok(
      spans.rows.some((row) => row.date === "2025-11-04"),
      "the boundary day is present"
    );
    assert.ok(
      !spans.rows.some((row) => row.date === "2025-11-03"),
      "the day before the boundary is gone"
    );
    const expectedCount = (day("2026-11-04") - day("2025-11-04")) / DAY_SEC + 1;
    assert.equal(expectedCount, 366);
    assert.equal(spans.rows.length, expectedCount);
    assert.equal(spans.windowPoints.length, expectedCount, "daily granularity keeps one point per day");
    assert.equal(
      granularityFor("1Y"),
      "daily",
      "1Y is the only daily range in the shared map"
    );
  });

  it("keeps Max unfiltered with a null cutoff", () => {
    const win = historyWindow(windowHistory, "Max");
    assert.equal(win.cutoff, null);
    assert.equal(win.rows.length, windowHistory.daily.length);
    const spans = windowSeries(windowHistory, "Max", pick2Y);
    assert.equal(spans.cutoff, null);
    assert.equal(spans.granularity, "weekly");
    assert.equal(spans.label, "weekly mean (UTC Monday buckets)");
    assert.equal(spans.windowPoints.length, windowHistory.daily.length, "Max never drops a row");
    const plotted =
      spans.verified.filter((p) => p.y !== null).length +
      spans.backfilled.filter((p) => p.y !== null).length;
    assert.ok(
      plotted < spans.windowPoints.length,
      "weekly buckets must shrink the plotted point count"
    );
  });

  it("aggregates each provenance span on its own so a boundary week yields two points", () => {
    const boundary = buildHistory([
      dailyRow("2026-01-05", true, { y2: 2 }),
      dailyRow("2026-01-06", true, { y2: 4 }),
      dailyRow("2026-01-07", false, { y2: 10 }),
      dailyRow("2026-01-08", false, { y2: 30 }),
      dailyRow("2026-03-01", true, { y2: 5 }),
    ]);
    const spans = windowSeries(boundary, "3Y", pick2Y);
    assert.equal(spans.granularity, "weekly");
    const monday = day("2026-01-05");
    assert.equal(new Date(monday * 1000).getUTCDay(), 1, "2026-01-05 is a UTC Monday");

    const verifiedAtWeek = spans.verified.filter((p) => p.x === monday);
    const backfilledAtWeek = spans.backfilled.filter((p) => p.x === monday);
    assert.equal(verifiedAtWeek.length, 1);
    assert.equal(backfilledAtWeek.length, 1);
    assert.equal(verifiedAtWeek[0].y, 3, "(2 + 4) / 2, never blended with backfilled days");
    assert.equal(backfilledAtWeek[0].y, 20, "(10 + 30) / 2, never blended with verified days");
    const atWeek = [...spans.verified, ...spans.backfilled].filter((p) => p.x === monday);
    assert.equal(atWeek.length, 2, "the boundary week is two points, not one merged point");

    for (const span of [spans.verified, spans.backfilled]) {
      const xs = span.map((p) => p.x);
      assert.equal(new Set(xs).size, xs.length, "one point per week inside a span");
      assert.deepEqual(xs, [...xs].sort((a, b) => a - b));
    }
    assert.equal(spans.windowPoints.length, 5, "the percentile input stays unaggregated");
  });

  it("summarizes percentiles over the unaggregated window, never the weekly buckets", () => {
    const spans = windowSeries(windowHistory, "Max", pick2Y);
    const summary = percentileSummary(spans.windowPoints);
    assert.ok(summary, "the window clears the 60 value minimum");
    const finite = spans.windowPoints.filter(
      (p) => typeof p.y === "number" && Number.isFinite(p.y)
    ).length;
    assert.equal(summary.count, finite, "count comes from daily window points");
    const plotted =
      spans.verified.filter((p) => p.y !== null).length +
      spans.backfilled.filter((p) => p.y !== null).length;
    assert.ok(
      summary.count > plotted,
      "the count must come from daily rows, never from the weekly buckets"
    );
    assert.equal(summary.latest, spans.windowPoints[spans.windowPoints.length - 1].y);
  });
});

describe("phase8.4 caption strings", () => {
  const base = {
    p10: 1.5,
    p50: 2.5,
    p90: 3.5,
    latest: 3.26,
    latestRankPercent: 42,
    count: 2520,
  };

  it("prints the normal caption with unit, plain integer rank, and obs count", () => {
    assert.equal(
      percentileCaption(base, "percent"),
      "Latest 3.26 percent, 42 percentile of selected range (2520 obs)."
    );
    assert.equal(
      percentileCaption({ ...base, latest: -14.5, latestRankPercent: 7 }, "basis_points"),
      "Latest -14.50 basis_points, 7 percentile of selected range (2520 obs)."
    );
    assert.equal(
      percentileCaption(
        { ...base, latest: 0.412, latestRankPercent: 42.4 },
        "percent_per_month"
      ),
      "Latest 0.41 percent_per_month, 42 percentile of selected range (2520 obs)."
    );
  });

  it("names a thin window and a missing latest as distinct captions", () => {
    assert.equal(
      percentileCaption(null, "percent"),
      "Insufficient history for percentile (needs 60 obs)."
    );
    assert.equal(
      percentileCaption({ ...base, latest: null, latestRankPercent: null }, "percent"),
      "Latest unavailable in this range."
    );
  });

  it("never throws on a non finite latest or rank and falls back (defense in depth)", () => {
    // history-window.ts guards null and non finite values, so a crafted
    // summary with NaN or Infinity in latest or latestRankPercent must take
    // the unavailable path rather than print NaN or Infinity. percentileSummary
    // itself only produces a finite latest or null, so the gap needs a
    // crafted summary to reach.
    const fallback = "Latest unavailable in this range.";
    for (const latest of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
      assert.equal(
        percentileCaption({ ...base, latest }, "percent"),
        fallback,
        "non finite latest must fall back, got " + String(latest)
      );
      assert.doesNotThrow(
        () => percentileCaption({ ...base, latest }, "percent"),
        "non finite latest must not throw, got " + String(latest)
      );
    }
    for (const latestRankPercent of [
      Number.NaN,
      Number.POSITIVE_INFINITY,
      Number.NEGATIVE_INFINITY,
    ]) {
      assert.equal(
        percentileCaption({ ...base, latestRankPercent }, "percent"),
        fallback,
        "non finite rank must fall back, got " + String(latestRankPercent)
      );
      assert.doesNotThrow(
        () => percentileCaption({ ...base, latestRankPercent }, "percent"),
        "non finite rank must not throw, got " + String(latestRankPercent)
      );
    }
  });

  it("builds the caption from a real summary over an unaggregated window", () => {
    const points = Array.from({ length: 100 }, (_, i) => ({ x: i + 1, y: i + 1 }));
    const summary = percentileSummary(points);
    assert.equal(
      percentileCaption(summary, "percent"),
      "Latest 100.00 percent, 100 percentile of selected range (100 obs)."
    );
    assert.equal(
      percentileCaption(percentileSummary(points.slice(0, 59)), "percent"),
      "Insufficient history for percentile (needs 60 obs)."
    );
  });

  it("labels aggregation from the shared wording and keeps CPI monthly", () => {
    assert.equal(
      aggregationNote("weekly"),
      "Weekly mean (UTC Monday buckets), daily source data."
    );
    assert.equal(aggregationNote("daily"), "Daily prints, one value per date.");
    assert.ok(
      aggregationNote("weekly")
        .toLowerCase()
        .includes(aggregationLabel("weekly").toLowerCase()),
      "the weekly note must carry the shared label"
    );
    assert.ok(
      aggregationNote("daily")
        .toLowerCase()
        .includes(aggregationLabel("daily").toLowerCase()),
      "the daily note must carry the shared label"
    );
    assert.equal(cpiAggregationNote(), "Monthly prints, no aggregation.");
  });

  it("joins note parts with one space and skips empty parts", () => {
    assert.equal(joinNote("A.", "B."), "A. B.");
    assert.equal(joinNote("A.", null, undefined, "", "B."), "A. B.");
    assert.equal(joinNote(null, ""), "");
  });
});

describe("phase8.4 inversion bands on the window", () => {
  it("carries no bands when history is absent", () => {
    assert.deepEqual(windowBands(historyWindow(null, "3Y")), []);
    assert.deepEqual(windowBands(historyWindow(buildHistory([]), "Max")), []);
    const spans = windowSeries(null, "3Y", pick2Y);
    assert.deepEqual(spans.rows, []);
    assert.deepEqual(spans.windowPoints, []);
    assert.deepEqual(spans.verified, []);
    assert.deepEqual(spans.backfilled, []);
  });

  it("bands the negative runs inside the window with a constant fill", () => {
    const win = historyWindow(windowHistory, "1Y");
    const bands = windowBands(win);
    assert.deepEqual(bands, [
      {
        x0: day("2026-03-02"),
        x1: day("2026-03-06") + DAY_SEC,
        fill: "rgba(164, 74, 42, 0.10)",
      },
    ]);
    const lastDay = day("2026-11-04");
    for (const band of bands) {
      assert.ok(band.x0 < band.x1, "every band spans a positive width");
      assert.ok(band.x0 >= win.cutoff, "every band starts inside the window");
      assert.ok(band.x1 <= lastDay + DAY_SEC, "every band ends inside the window");
      assert.ok(band.fill.startsWith("rgba("), "bands carry a constant CSS fill");
    }
    assert.deepEqual(
      windowBands(historyWindow(windowHistory, "Max")).map((b) => b.x0),
      [day("2026-03-02")],
      "Max keeps the same run, the source never changes"
    );
  });
});

describe("phase8.4 CPI monthly window", () => {
  const cpiRows = monthRange("2021-10", "2026-09").map((month, i) =>
    cpiRow(month, i % 3 === 0, 0.1 + (i % 7) * 0.05, 0.2 + (i % 5) * 0.05)
  );
  const cpiHistory = buildHistory(windowRows, cpiRows);

  it("forces daily granularity for every range so monthly prints are never bucketed", () => {
    for (const range of RANGE_KEYS) {
      const cpi = windowCpiSeries(cpiHistory, range, pickTrim);
      assert.equal(cpi.granularity, "daily", range);
      assert.equal(cpi.label, "daily prints", range);
      const finite = [...cpi.verified, ...cpi.backfilled].filter((p) => p.y !== null);
      assert.equal(finite.length, cpi.rows.length, range + " plots one point per month");
      for (const point of finite) {
        assert.equal(
          new Date(point.x * 1000).getUTCDate(),
          1,
          range + " keeps month starts, never a weekly bucket"
        );
      }
    }
    const atMax = windowCpiSeries(cpiHistory, "Max", pickTrim);
    assert.equal(atMax.rows.length, 60, "all 60 published style months at Max");
    assert.equal(atMax.windowPoints.length, 60);
    const at10Y = windowCpiSeries(cpiHistory, "10Y", pickTrim);
    assert.equal(at10Y.rows.length, 60, "10Y never cuts a 60 month series");
  });

  it("filters months by the cutoff month so the month holding the cutoff day stays in", () => {
    const at1Y = windowCpiSeries(cpiHistory, "1Y", pickTrim);
    assert.equal(at1Y.cutoff, day("2025-11-04"));
    assert.equal(at1Y.rows[0].month, "2025-11", "the month containing the cutoff day stays in");
    assert.equal(at1Y.rows.length, 11, "2025-11 through 2026-09");
    assert.ok(at1Y.rows.every((row) => row.month >= "2025-11"));
    assert.ok(at1Y.rows.every((row) => row.month <= "2026-09"));
  });

  it("keeps verified and backfilled CPI months separate", () => {
    const cpi = windowCpiSeries(cpiHistory, "Max", pickTrim);
    const verifiedMonths = cpi.verified.filter((p) => p.y !== null).length;
    const backfilledMonths = cpi.backfilled.filter((p) => p.y !== null).length;
    assert.ok(verifiedMonths > 0, "the fixture carries verified months");
    assert.ok(backfilledMonths > 0, "the fixture carries backfilled months");
    assert.equal(verifiedMonths + backfilledMonths, 60, "the spans never merge a month");
  });
});

/** The committed artifact, same pattern as the phase8.3 pipeline test. */
const historyPath = join(webRoot, "public", "data", "history.json");
const published = JSON.parse(readFileSync(historyPath, "utf8"));

/** MAX_CHART_POINTS read from the chart source so the cap check tracks drift. */
function maxChartPoints() {
  const chart = readSource("src/components/Chart.tsx");
  const match = chart.match(/MAX_CHART_POINTS = (\d+)/);
  assert.ok(match, "MAX_CHART_POINTS constant absent from Chart.tsx");
  return Number(match[1]);
}

describe("phase8.4 wiring on the committed history artifact", () => {
  it("windows the published history at Max without a cutoff", () => {
    // Absolute pins match the project convention of pinning the artifact;
    // a future refresh phase migrates these to relative checks first.
    assert.equal(published.daily.length, 2494);
    assert.equal(latestDailyEpoch(published), day("2026-11-04"));
    const win = historyWindow(published, "Max");
    assert.equal(win.cutoff, null);
    assert.equal(win.rows.length, 2494);
    // Relative checks that survive an artifact refresh with a new row count.
    assert.ok(published.daily.length > 0, "the artifact carries daily rows");
    assert.equal(
      win.rows.length,
      published.daily.length,
      "the Max window keeps every published row"
    );
    const lastRow = published.daily[published.daily.length - 1];
    assert.equal(
      latestDailyEpoch(published),
      dateToEpochSec(lastRow.date),
      "the latest epoch equals the last row date"
    );
  });

  it("keeps the 1Y daily window inclusive and under the chart cap", () => {
    const spans = windowSeries(published, "1Y", pick2Y);
    assert.equal(spans.granularity, "daily");
    assert.equal(spans.cutoff, rangeCutoff("1Y", latestDailyEpoch(published)));
    assert.ok(spans.cutoff !== null);
    const expected = published.daily.filter(
      (row) => dateToEpochSec(row.date) >= spans.cutoff
    ).length;
    assert.equal(spans.rows.length, expected);
    assert.equal(spans.windowPoints.length, expected);
    assert.ok(
      spans.rows.length > 200 && spans.rows.length < 400,
      "about one year of business days, got " + spans.rows.length
    );
    assert.ok(spans.rows[0].date === new Date(spans.cutoff * 1000).toISOString().slice(0, 10));
  });

  it("keeps the Max weekly spans and the percentile count inside the contract", () => {
    const spans = windowSeries(published, "Max", pickSlope);
    assert.equal(spans.granularity, "weekly");
    const cap = 2000;
    assert.ok(spans.verified.length <= cap, "verified span over cap: " + spans.verified.length);
    assert.ok(
      spans.backfilled.length <= cap,
      "backfilled span over cap: " + spans.backfilled.length
    );
    // Relative check: total weekly buckets stay under the chart point cap
    // read from the source, so an artifact refresh keeps this contract.
    const chartCap = maxChartPoints();
    const buckets = spans.verified.length + spans.backfilled.length;
    assert.ok(
      buckets < chartCap,
      "weekly buckets " + buckets + " must stay under MAX_CHART_POINTS " + chartCap
    );
    const summary = percentileSummary(spans.windowPoints);
    assert.ok(summary);
    assert.equal(
      summary.count,
      2494,
      "the 2Y_10Y slope is finite on every published row"
    );
    // Relative check alongside the 2494 pin: the percentile count equals
    // the unfiltered Max window row count, whatever the artifact holds.
    const maxWin = historyWindow(published, "Max");
    assert.equal(
      summary.count,
      maxWin.rows.length,
      "the percentile count equals the Max window row count"
    );
    assert.ok(
      summary.count > spans.verified.length + spans.backfilled.length,
      "percentiles run over the unaggregated window"
    );
  });

  it("bands the published inversions inside a 10Y window", () => {
    const win = historyWindow(published, "10Y");
    const bands = windowBands(win);
    assert.ok(bands.length >= 1, "the published history carries inversion runs");
    for (const band of bands) {
      assert.ok(band.x0 >= win.cutoff, "every band starts inside the window");
      assert.ok(band.x0 < band.x1, "every band spans a positive width");
    }
    const shorter = windowBands(historyWindow(published, "1Y")).length;
    assert.ok(
      shorter <= bands.length,
      "a shorter window can only shrink the band count, got " +
        shorter +
        " inside " +
        bands.length
    );
  });

  it("windows the published CPI months without weekly buckets", () => {
    const cpi = windowCpiSeries(published, "1Y", pickTrim);
    assert.equal(cpi.granularity, "daily");
    assert.ok(
      cpi.rows.length >= 10 && cpi.rows.length <= 12,
      "about one year of monthly prints, got " + cpi.rows.length
    );
    const finite = [...cpi.verified, ...cpi.backfilled].filter((p) => p.y !== null);
    assert.equal(finite.length, cpi.rows.length, "one point per month, never a bucket");
    assert.equal(
      windowCpiSeries(published, "Max", pickTrim).rows.length,
      published.cpi.length
    );
  });
});

describe("phase8.4 source wiring", () => {
  const selector = readSource("src/components/RangeSelector.tsx");
  const chart = readSource("src/components/Chart.tsx");
  const css = readSource("src/index.css");

  it("ships one radiogroup switch with roving tabindex and arrow selection", () => {
    assert.ok(selector.includes('role="radiogroup"'), "radiogroup role absent");
    assert.ok(selector.includes('role="radio"'), "radio role absent");
    assert.ok(selector.includes("aria-checked"), "aria-checked absent");
    assert.ok(selector.includes("tabIndex"), "roving tabindex absent");
    assert.ok(selector.includes("ArrowRight") && selector.includes("ArrowLeft"));
    assert.ok(selector.includes('"Home"') && selector.includes('"End"'));
    assert.ok(selector.includes("rangeKey()"), "must read the shared signal");
    assert.ok(selector.includes("setRangeKey("), "must write the shared signal");
    assert.ok(selector.includes('aria-label="Range"'), "group label absent");
    assert.ok(selector.includes("{key}"), "segment labels come from RANGE_KEYS");
  });

  it("pins every keyboard branch in source, the only automated coverage", () => {
    // Honest coverage note: the project has no DOM test framework, so the
    // keyboard contract has no runtime test. The wrap index math is inline
    // in the component and not exported, so it cannot be tested without
    // touching the component. These source assertions plus manual browser
    // verification are the whole contract.
    assert.ok(RANGE_KEYS.length >= 2, "the wrap math needs at least two segments");
    assert.ok(selector.includes("ArrowDown"), "ArrowDown branch absent");
    assert.ok(selector.includes("ArrowUp"), "ArrowUp branch absent");
    assert.ok(
      selector.includes("(index + 1) % count"),
      "forward wrap index math absent"
    );
    assert.ok(
      selector.includes("(index - 1 + count) % count"),
      "backward wrap index math absent"
    );
    assert.ok(selector.includes("selectAt(0)"), "Home jump to first absent");
    assert.ok(selector.includes("selectAt(count - 1)"), "End jump to last absent");
    assert.ok(selector.includes("event.preventDefault()"), "preventDefault absent");
    assert.ok(
      selector.includes("rangeKey() === key ? 0 : -1"),
      "roving tabindex ternary absent"
    );
    assert.ok(selector.includes("target.focus()"), "focus move after select absent");
    assert.ok(
      selector.includes("key === undefined"),
      "out of range index guard absent"
    );
    assert.ok(selector.includes("index()"), "index from the For scope absent");
  });

  it("styles the switch like the toolbar with 44px targets and reduced motion", () => {
    assert.ok(css.includes(".range-selector"), "range selector styles absent");
    const block = css.match(/\.range-selector-option \{[^}]*\}/);
    assert.ok(block, "option block absent");
    assert.match(block[0], /min-height: 44px/, "44px touch target absent");
    assert.match(block[0], /min-width: 44px/, "44px touch target absent");
    assert.match(block[0], /font-family: var\(--mono\)/, "mono type absent");
    assert.ok(css.includes("button:focus-visible"), "focus ring absent");
    assert.ok(css.includes("prefers-reduced-motion"), "reduced motion guard absent");
  });

  it("adds band and note props to the chart behind a drawClear hook", () => {
    assert.ok(chart.includes("bands?: ChartBand[]"), "bands prop absent");
    assert.ok(chart.includes("note?: string"), "note prop absent");
    assert.ok(chart.includes("drawClear"), "band draw hook absent");
    assert.ok(chart.includes("paintBands"), "band painter absent");
    assert.ok(chart.includes("props.note"), "note not appended to the caption");
    assert.ok(chart.includes("MAX_CHART_POINTS = 2000"), "point cap drift");
  });

  it("places one range switch above the first history chart on each page", () => {
    for (const rel of [
      "src/pages/CurvePage.tsx",
      "src/pages/FundingPage.tsx",
      "src/pages/InflationPage.tsx",
      "src/pages/BreaksPage.tsx",
    ]) {
      const page = readSource(rel);
      const hits = page.match(/<RangeSelector \/>/g) ?? [];
      assert.equal(hits.length, 1, rel + " must render exactly one RangeSelector");
      assert.ok(
        page.includes("windowSeries(") || page.includes("windowCpiSeries("),
        rel + " misses the window helper"
      );
      assert.ok(page.includes("rangeKey()"), rel + " must read the range reactively");
      assert.ok(page.includes("percentileCaption("), rel + " misses the percentile caption");
    }
  });

  it("keeps inversion shading on the yield and slope charts only", () => {
    const curve = readSource("src/pages/CurvePage.tsx");
    const bandProps = curve.match(/bands=\{bands\(\)\}/g) ?? [];
    assert.equal(bandProps.length, 2, "yield chart and slope chart both shade");
    assert.ok(
      curve.includes("Shaded: 2s10s inverted (slope below 0 bp)."),
      "band legend line absent"
    );
    for (const rel of [
      "src/pages/FundingPage.tsx",
      "src/pages/InflationPage.tsx",
      "src/pages/BreaksPage.tsx",
    ]) {
      const page = readSource(rel);
      assert.ok(!page.includes("bands="), rel + " must not shade spreads, CPI, or breaks");
    }
  });

  it("uses plain punctuation in the new copy and code", () => {
    const emDash = String.fromCharCode(0x2014);
    const enDash = String.fromCharCode(0x2013);
    const doubled = "-".concat("-");
    for (const rel of [
      "src/components/RangeSelector.tsx",
      "src/lib/history-window.ts",
      "src/components/Chart.tsx",
    ]) {
      const text = readSource(rel);
      assert.ok(!text.includes(emDash), rel + " holds an em dash");
      assert.ok(!text.includes(enDash), rel + " holds an en dash");
      assert.ok(!text.includes(doubled), rel + " holds a double hyphen");
    }
  });
});
