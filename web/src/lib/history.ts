import type { HistoryDoc, HistorySlopeKey, HistoryTenor } from "./types";

export interface EpochPoint {
  x: number;
  y: number | null;
}

/** Parse a strict YYYY-MM-DD date to epoch seconds (UTC midnight). NaN when invalid. */
export function dateToEpochSec(date: string): number {
  const ms = Date.parse(date + "T00:00:00Z");
  if (!Number.isFinite(ms)) return NaN;
  return Math.floor(ms / 1000);
}

/** Parse a YYYY-MM month to epoch seconds at the first of the month (UTC). NaN when invalid. */
export function monthToEpochSec(month: string): number {
  const ms = Date.parse(month + "-01T00:00:00Z");
  if (!Number.isFinite(ms)) return NaN;
  return Math.floor(ms / 1000);
}

function finiteOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Daily yield series on a real date axis (epoch seconds). Units: percent. */
export function yieldSeries(
  history: HistoryDoc | null | undefined,
  tenor: HistoryTenor
): EpochPoint[] {
  if (!history) return [];
  return history.daily.map((row) => ({
    x: dateToEpochSec(row.date),
    y: finiteOrNull(row.yields_percent[tenor]),
  }));
}

/** Daily slope series on a real date axis (epoch seconds). Units: basis_points. */
export function slopeSeries(
  history: HistoryDoc | null | undefined,
  key: HistorySlopeKey
): EpochPoint[] {
  if (!history) return [];
  return history.daily.map((row) => ({
    x: dateToEpochSec(row.date),
    y: finiteOrNull(row.slopes_bp[key]),
  }));
}

/** Daily CA-US spread series on a real date axis (epoch seconds). Units: basis_points. */
export function spreadSeries(
  history: HistoryDoc | null | undefined,
  tenor: HistoryTenor
): EpochPoint[] {
  if (!history) return [];
  return history.daily.map((row) => ({
    x: dateToEpochSec(row.date),
    y: row.spreads_bp[tenor] === null ? null : finiteOrNull(row.spreads_bp[tenor]),
  }));
}

/** Monthly core inflation series on a real month axis (epoch seconds). Units: percent_per_month. */
export function cpiSeries(
  history: HistoryDoc | null | undefined,
  pick: "trim" | "median"
): EpochPoint[] {
  if (!history) return [];
  return history.cpi.map((row) => ({
    x: monthToEpochSec(row.month),
    y:
      pick === "trim"
        ? finiteOrNull(row.trim_mom_percent)
        : finiteOrNull(row.median_mom_percent),
  }));
}

/** Split one numeric daily field into verified (solid) and backfilled (dashed) spans on a real date axis. */
export function splitSeries(
  history: HistoryDoc | null | undefined,
  pick: (row: HistoryDoc["daily"][number]) => number | null
): { verified: EpochPoint[]; backfilled: EpochPoint[] } {
  const verified: EpochPoint[] = [];
  const backfilled: EpochPoint[] = [];
  if (!history) return { verified, backfilled };
  history.daily.forEach((row) => {
    const value = pick(row);
    const point = { x: dateToEpochSec(row.date), y: value };
    if (row.verified) {
      verified.push(point);
      backfilled.push({ x: point.x, y: null });
    } else {
      verified.push({ x: point.x, y: null });
      backfilled.push(point);
    }
  });
  return { verified, backfilled };
}

/** Split one CPI monthly field into verified and backfilled spans on a real month axis. */
export function splitCpiSeries(
  history: HistoryDoc | null | undefined,
  pick: (row: HistoryDoc["cpi"][number]) => number | null
): { verified: EpochPoint[]; backfilled: EpochPoint[] } {
  const verified: EpochPoint[] = [];
  const backfilled: EpochPoint[] = [];
  if (!history) return { verified, backfilled };
  history.cpi.forEach((row) => {
    const value = pick(row);
    const point = { x: monthToEpochSec(row.month), y: value };
    if (row.verified) {
      verified.push(point);
      backfilled.push({ x: point.x, y: null });
    } else {
      verified.push({ x: point.x, y: null });
      backfilled.push(point);
    }
  });
  return { verified, backfilled };
}
export interface CurveOverlayRow {
  tenor: string;
  years: number;
  currentZero: number | null;
  compareZero: number | null;
  deltaBp: number | null;
}

/**
 * Align two solved zero curves by tenor for the compare overlay. Zeros are
 * semiannual percent_yield solves, so the delta converts to basis points.
 * Missing legs stay null and render as NA, never filled.
 */
export function overlayCurves(
  current: { knots: Array<{ tenor: string; tenor_years: number }>; zeroYields: Record<string, { value: number | null }> } | null | undefined,
  compare: { knots: Array<{ tenor: string; tenor_years: number }>; zeroYields: Record<string, { value: number | null }> } | null | undefined
): CurveOverlayRow[] {
  if (!current) return [];
  return current.knots.map((knot) => {
    const currentZero = finiteOrNull(current.zeroYields[knot.tenor]?.value);
    const compareZero = compare
      ? finiteOrNull(compare.zeroYields[knot.tenor]?.value)
      : null;
    return {
      tenor: knot.tenor,
      years: knot.tenor_years,
      currentZero,
      compareZero,
      deltaBp: deltaBp(currentZero, compareZero),
    };
  });
}

/**
 * Day over day style step through sorted ISO dates. Returns null at either
 * end so prev and next buttons disable instead of wrapping around.
 */
export function stepDate(
  dates: string[],
  current: string | null,
  step: 1 | -1
): string | null {
  if (!current) return null;
  const sorted = [...dates].sort();
  const index = sorted.indexOf(current);
  if (index < 0) return null;
  const next = sorted[index + step];
  return next ?? null;
}

/**
 * Percent to basis point delta for overlay columns. Null when either leg
 * is missing or non finite, so gaps name themselves instead of computing
 * against a filled zero.
 */
export function deltaBp(
  current: number | null | undefined,
  compare: number | null | undefined
): number | null {
  if (
    typeof current !== "number" ||
    typeof compare !== "number" ||
    !Number.isFinite(current) ||
    !Number.isFinite(compare)
  ) {
    return null;
  }
  return (current - compare) * 100;
}

/** Solved zero curve points for chart overlays. X is tenor years, Y is percent_yield. */
export function zeroSeries(
  knots: Array<{ tenor_years: number; tenor: string }>,
  zeroYields: Record<string, { value: number | null }> | undefined | null
): EpochPoint[] {
  const map = zeroYields ?? {};
  return knots.map((knot) => ({
    x: knot.tenor_years,
    y: finiteOrNull(map[knot.tenor]?.value),
  }));
}
