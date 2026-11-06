import { aggregationLabel, aggregateSeries, granularityFor } from "./aggregate";
import {
  dateToEpochSec,
  monthToEpochSec,
  splitCpiSeries,
  splitSeries,
} from "./history";
import type { EpochPoint } from "./history";
import { rangeCutoff } from "./history-range";
import { inversionBands } from "./regimes";
import type {
  ChartBand,
  CpiHistoryRow,
  Granularity,
  HistoryDoc,
  HistoryRow,
  PercentileSummary,
  RangeKey,
} from "./types";

/**
 * Newest daily row epoch in UTC seconds at midnight, read from the last row
 * because validateHistory keeps dates strictly increasing. Null when history
 * is absent or no date parses. Callers hand this to rangeCutoff and never
 * Date.now(), because a cutoff of today would drop the newest day from a
 * window whose cutoff is inclusive.
 */
export function latestDailyEpoch(history: HistoryDoc | null | undefined): number | null {
  if (!history) return null;
  for (let i = history.daily.length - 1; i >= 0; i -= 1) {
    const x = dateToEpochSec(history.daily[i].date);
    if (Number.isFinite(x)) return x;
  }
  return null;
}

/** Daily rows inside the range plus the inclusive cutoff that produced them. */
export interface HistoryWindow {
  rows: HistoryRow[];
  cutoff: number | null;
}

/**
 * Filter daily history to the range window. The cutoff comes from the newest
 * daily row at midnight UTC and is inclusive, so the boundary day stays in.
 * Max, a history without a parseable newest date, and an absent history all
 * yield a null cutoff, and rows keep document order.
 */
export function historyWindow(
  history: HistoryDoc | null | undefined,
  range: RangeKey
): HistoryWindow {
  const cutoff = rangeCutoff(range, latestDailyEpoch(history) ?? Number.NaN);
  const rows: HistoryRow[] = [];
  if (history) {
    for (const row of history.daily) {
      const x = dateToEpochSec(row.date);
      if (!Number.isFinite(x)) continue;
      if (cutoff !== null && x < cutoff) continue;
      rows.push(row);
    }
  }
  return { rows, cutoff };
}

/** Filtered window plus the plotted spans and the percentile input. */
export interface WindowedSpans extends HistoryWindow {
  granularity: Granularity;
  label: string;
  windowPoints: EpochPoint[];
  verified: EpochPoint[];
  backfilled: EpochPoint[];
}

/**
 * Build one history chart pair of spans for a range. Rows filter to the
 * window first, splitSeries then separates verified from backfilled
 * provenance, and aggregateSeries buckets each span on its own, so a week
 * that holds both provenances yields one point per span and the two never
 * blend. windowPoints stay unaggregated and are the percentile input.
 * granularity defaults to granularityFor(range): daily at 1Y, weekly above.
 */
export function windowSeries(
  history: HistoryDoc | null | undefined,
  range: RangeKey,
  pick: (row: HistoryRow) => number | null,
  granularity: Granularity = granularityFor(range)
): WindowedSpans {
  const { rows, cutoff } = historyWindow(history, range);
  const windowPoints: EpochPoint[] = rows.map((row) => ({
    x: dateToEpochSec(row.date),
    y: pick(row),
  }));
  let verified: EpochPoint[] = [];
  let backfilled: EpochPoint[] = [];
  if (history) {
    const split = splitSeries({ ...history, daily: rows }, pick);
    verified = aggregateSeries(split.verified, granularity);
    backfilled = aggregateSeries(split.backfilled, granularity);
  }
  return {
    rows,
    cutoff,
    granularity,
    label: aggregationLabel(granularity),
    windowPoints,
    verified,
    backfilled,
  };
}

/**
 * Inversion shading for a window. Bands come from the window rows and the
 * same inclusive cutoff, so shading and series can never disagree on the
 * window. An absent history yields no bands instead of an empty overlay, and
 * the fill stays the constant regimes default, never a value read from data.
 */
export function windowBands(window: HistoryWindow): ChartBand[] {
  if (window.rows.length === 0) return [];
  return inversionBands(window.rows, window.cutoff);
}

/** Filtered CPI window plus the plotted spans and the percentile input. */
export interface WindowedCpiSpans {
  rows: CpiHistoryRow[];
  cutoff: number | null;
  granularity: Granularity;
  label: string;
  windowPoints: EpochPoint[];
  verified: EpochPoint[];
  backfilled: EpochPoint[];
}

/**
 * Build the monthly CPI chart spans for a range. The cutoff is the daily
 * range cutoff, and a month counts as inside when it starts on or after the
 * cutoff month, so the month that contains the cutoff day stays in, matching
 * the inclusive rule used for daily rows. granularity is always daily: CPI
 * prints monthly and weekly buckets would invent values the publisher never
 * published, so no range can trigger weekly aggregation here.
 */
export function windowCpiSeries(
  history: HistoryDoc | null | undefined,
  range: RangeKey,
  pick: (row: CpiHistoryRow) => number | null
): WindowedCpiSpans {
  const cutoff = rangeCutoff(range, latestDailyEpoch(history) ?? Number.NaN);
  const cutoffMonth =
    cutoff === null ? null : new Date(cutoff * 1000).toISOString().slice(0, 7);
  const granularity: Granularity = "daily";
  const rows: CpiHistoryRow[] = [];
  const windowPoints: EpochPoint[] = [];
  if (history) {
    for (const row of history.cpi) {
      const x = monthToEpochSec(row.month);
      if (!Number.isFinite(x)) continue;
      if (cutoffMonth !== null && row.month < cutoffMonth) continue;
      rows.push(row);
      windowPoints.push({ x, y: pick(row) });
    }
  }
  let verified: EpochPoint[] = [];
  let backfilled: EpochPoint[] = [];
  if (history) {
    const split = splitCpiSeries({ ...history, cpi: rows }, pick);
    verified = aggregateSeries(split.verified, granularity);
    backfilled = aggregateSeries(split.backfilled, granularity);
  }
  return {
    rows,
    cutoff,
    granularity,
    label: aggregationLabel(granularity),
    windowPoints,
    verified,
    backfilled,
  };
}

/**
 * Percentile line for a chart note. The value always prints with its unit,
 * the rank prints as a plain integer with no ordinal suffix, and the count
 * names its obs unit. A null summary means the window held fewer than the 60
 * finite values that percentileSummary requires. A null or non finite latest
 * or rank falls back to the unavailable caption instead of printing NaN or
 * Infinity.
 */
export function percentileCaption(
  summary: PercentileSummary | null,
  unit: string
): string {
  if (!summary) return "Insufficient history for percentile (needs 60 obs).";
  if (
    summary.latest === null ||
    summary.latestRankPercent === null ||
    !Number.isFinite(summary.latest) ||
    !Number.isFinite(summary.latestRankPercent)
  ) {
    return "Latest unavailable in this range.";
  }
  const rank = Math.round(summary.latestRankPercent);
  return (
    "Latest " +
    summary.latest.toFixed(2) +
    " " +
    unit +
    ", " +
    rank +
    " percentile of selected range (" +
    summary.count +
    " obs)."
  );
}

/**
 * Aggregation sentence for a chart note, built from aggregationLabel so the
 * on screen wording and the label module can never drift apart.
 */
export function aggregationNote(granularity: Granularity): string {
  const label = aggregationLabel(granularity);
  const sentence = label.charAt(0).toUpperCase() + label.slice(1);
  return granularity === "weekly"
    ? sentence + ", daily source data."
    : sentence + ", one value per date.";
}

/** Note for the monthly CPI chart, which is never aggregated. */
export function cpiAggregationNote(): string {
  return "Monthly prints, no aggregation.";
}

/** Join caption sentences with one space, skipping empty parts. */
export function joinNote(...parts: Array<string | null | undefined>): string {
  return parts
    .filter((part): part is string => typeof part === "string" && part.length > 0)
    .join(" ");
}
