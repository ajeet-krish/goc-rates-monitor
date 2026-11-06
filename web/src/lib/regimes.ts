import { dateToEpochSec } from "./history";
import type { ChartBand, HistoryDoc } from "./types";

export type { ChartBand };

/** Seconds in one day, used to extend a band to a full day. Units: seconds. */
const SECONDS_PER_DAY = 86400;

/**
 * Shaded runs of 2s10s inversion on the daily history rows, in ascending
 * order. A day is inverted when slopes_bp["2Y_10Y"] is finite and strictly
 * below zero, so exactly zero is not inverted. A missing or non finite slope
 * skips the day, contributes no band, and breaks the run, and a zero or
 * positive slope also ends the run. Runs of a single day still produce a
 * band.
 *
 * x0 is the first inverted day epoch of the run and x1 is the last inverted
 * day epoch plus one day (86400 seconds). That extra day is a rendering span
 * only, so a one day run still draws as a visible band and x0 < x1 always
 * holds; it implies no data beyond the run. A non inverted day always sits
 * between two runs, so the extension never makes bands overlap.
 *
 * cutoffEpochSec filters to rows with x >= cutoff, inclusive, so the cutoff
 * day itself can start a band; null keeps every row. An inverted run that
 * starts before the cutoff is trimmed to the cutoff day. Rows are read in
 * document order, which validateHistory keeps strictly increasing by date.
 *
 * Units: x0 and x1 are epoch seconds, fill is a CSS color such as
 * rgba(164, 74, 42, 0.10).
 */
export function inversionBands(
  rows: HistoryDoc["daily"],
  cutoffEpochSec: number | null,
  fill = "rgba(164, 74, 42, 0.10)"
): ChartBand[] {
  const bands: ChartBand[] = [];
  let runStart: number | null = null;
  let runEnd: number | null = null;
  const closeRun = () => {
    if (runStart !== null && runEnd !== null) {
      bands.push({ x0: runStart, x1: runEnd + SECONDS_PER_DAY, fill });
    }
    runStart = null;
    runEnd = null;
  };
  for (const row of rows) {
    const x = dateToEpochSec(row.date);
    if (!Number.isFinite(x)) {
      closeRun();
      continue;
    }
    if (cutoffEpochSec !== null && x < cutoffEpochSec) {
      closeRun();
      continue;
    }
    const slope = row.slopes_bp?.["2Y_10Y"];
    const inverted = typeof slope === "number" && Number.isFinite(slope) && slope < 0;
    if (!inverted) {
      closeRun();
      continue;
    }
    if (runStart === null) runStart = x;
    runEnd = x;
  }
  closeRun();
  bands.sort((a, b) => a.x0 - b.x0);
  return bands;
}
