import { createSignal } from "solid-js";
import type { RangeKey } from "./types";

export type { RangeKey };

/** Range keys in display order for the long range history selector. */
export const RANGE_KEYS: readonly RangeKey[] = ["1Y", "3Y", "5Y", "10Y", "Max"];

/** Range used when nothing valid is stored. Units: none, it is a key. */
export const DEFAULT_RANGE: RangeKey = "3Y";

/** sessionStorage key for the persisted range choice. Units: none. */
const STORAGE_KEY = "goc-history-range";

/**
 * True when value is one of the closed set of range keys. Units: none, it is
 * a key. Used to validate stored values before they reach the signal.
 */
export function isRangeKey(value: unknown): value is RangeKey {
  return typeof value === "string" && (RANGE_KEYS as readonly string[]).includes(value);
}

/**
 * Read the persisted range, never throwing. Privacy mode can make storage
 * access throw, and a missing or invalid stored value falls back to the
 * default, so a garbage stored value always yields the default range.
 */
function readStoredRange(): RangeKey {
  try {
    const store = globalThis.sessionStorage;
    if (!store) return DEFAULT_RANGE;
    const stored = store.getItem(STORAGE_KEY);
    return isRangeKey(stored) ? stored : DEFAULT_RANGE;
  } catch {
    return DEFAULT_RANGE;
  }
}

/**
 * Persist the range, never throwing. The in memory signal already holds the
 * value, so a blocked write only loses the choice across refreshes.
 */
function writeStoredRange(value: RangeKey): void {
  try {
    const store = globalThis.sessionStorage;
    if (!store) return;
    store.setItem(STORAGE_KEY, value);
  } catch {
    // Blocked storage is expected in privacy mode and is not an error.
  }
}

/**
 * Shared range signal, initialized from storage on module load. Units: none,
 * it holds a range key. The getter and setter are the public surface so every
 * page reads the same value.
 */
const [range, setRange] = createSignal<RangeKey>(readStoredRange());

/** Current history range choice. Units: none, it is a key. */
export function rangeKey(): RangeKey {
  return range();
}

/**
 * Set the range and persist it when storage is available. A value outside the
 * closed set falls back to the default. Never throws.
 */
export function setRangeKey(next: RangeKey): void {
  const value = isRangeKey(next) ? next : DEFAULT_RANGE;
  setRange(value);
  writeStoredRange(value);
}

/**
 * Calendar cutoff for a range, in UTC epoch seconds. Subtract 1, 3, 5, or 10
 * calendar years from latestEpochSec with month end clamping, so 2028-02-29
 * minus 1Y is 2027-02-28. Max and a non finite latest return null, meaning no
 * cutoff, and a key outside the closed step map also returns null, which
 * covers strings inherited from Object.prototype such as "constructor". A
 * cutoff that computes to a non finite value, for example a latest epoch
 * whose Date round trip is invalid, also returns null rather than NaN. The
 * cutoff is inclusive: points with x >= cutoff stay in the window, so the
 * cutoff day itself is part of the view.
 */
export function rangeCutoff(range: RangeKey, latestEpochSec: number): number | null {
  if (!Number.isFinite(latestEpochSec)) return null;
  // A Map lookup never reads Object.prototype, so a stray key yields undefined.
  const yearStep = new Map<string, number>([
    ["1Y", 1],
    ["3Y", 3],
    ["5Y", 5],
    ["10Y", 10],
  ]);
  const years = yearStep.get(range);
  if (years === undefined) return null;
  const latest = new Date(latestEpochSec * 1000);
  const targetYear = latest.getUTCFullYear() - years;
  const month = latest.getUTCMonth();
  const daysInTargetMonth = new Date(Date.UTC(targetYear, month + 1, 0)).getUTCDate();
  const day = Math.min(latest.getUTCDate(), daysInTargetMonth);
  const cutoffMs = Date.UTC(
    targetYear,
    month,
    day,
    latest.getUTCHours(),
    latest.getUTCMinutes(),
    latest.getUTCSeconds(),
    latest.getUTCMilliseconds()
  );
  if (!Number.isFinite(cutoffMs)) return null;
  return Math.floor(cutoffMs / 1000);
}
