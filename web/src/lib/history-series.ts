import type { HistoryDoc } from "./types";

export interface SplitPair {
  verified: { x: number; y: number | null }[];
  backfilled: { x: number; y: number | null }[];
}

/** Split one numeric history field into verified (solid) and backfilled (dashed) spans. */
export function splitHistory(
  history: HistoryDoc | null | undefined,
  pick: (date: string, index: number, row: HistoryDoc["daily"][number]) => number | null
): SplitPair {
  const verified: { x: number; y: number | null }[] = [];
  const backfilled: { x: number; y: number | null }[] = [];
  if (!history) return { verified, backfilled };
  history.daily.forEach((row, i) => {
    const value = pick(row.date, i, row);
    if (row.verified) {
      verified.push({ x: i, y: value });
      backfilled.push({ x: i, y: null });
    } else {
      verified.push({ x: i, y: null });
      backfilled.push({ x: i, y: value });
    }
  });
  return { verified, backfilled };
}

export interface SplitCpiPair {
  verified: { x: number; y: number | null }[];
  backfilled: { x: number; y: number | null }[];
}

/** Split one CPI monthly field into verified and backfilled spans. */
export function splitCpi(
  history: HistoryDoc | null | undefined,
  pick: (month: string, index: number, row: HistoryDoc["cpi"][number]) => number | null
): SplitCpiPair {
  const verified: { x: number; y: number | null }[] = [];
  const backfilled: { x: number; y: number | null }[] = [];
  if (!history) return { verified, backfilled };
  history.cpi.forEach((row, i) => {
    const value = pick(row.month, i, row);
    if (row.verified) {
      verified.push({ x: i, y: value });
      backfilled.push({ x: i, y: null });
    } else {
      verified.push({ x: i, y: null });
      backfilled.push({ x: i, y: value });
    }
  });
  return { verified, backfilled };
}

export function historyRangeLabel(history: HistoryDoc | null | undefined): string {
  if (!history || history.daily.length === 0) return "history unavailable";
  const first = history.daily[0].date;
  const last = history.daily[history.daily.length - 1].date;
  const verifiedCount = history.daily.filter((r) => r.verified).length;
  return first + " to " + last + " (" + verifiedCount + " verified of " + history.daily.length + ")";
}
