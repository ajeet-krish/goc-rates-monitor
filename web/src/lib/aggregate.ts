import type { EpochPoint } from "./history";
import type { Granularity, RangeKey } from "./types";

export type { Granularity };

/** Seconds in one day, used for UTC week arithmetic. Units: seconds. */
const SECONDS_PER_DAY = 86400;

/**
 * Granularity for a range. Ranges above 2Y are weekly per the approved plan,
 * so only 1Y stays daily. Units: none, these are names.
 */
export function granularityFor(range: RangeKey): Granularity {
  return range === "1Y" ? "daily" : "weekly";
}

/**
 * Epoch seconds of the UTC Monday 00:00 that contains epochSec. Uses the UTC
 * calendar, so it is exact for negative epochs and for days near week edges.
 * Units: epoch seconds in, epoch seconds out.
 */
function utcMondayStart(epochSec: number): number {
  const date = new Date(epochSec * 1000);
  const dayOfWeek = date.getUTCDay();
  const daysSinceMonday = (dayOfWeek + 6) % 7;
  const dayStart = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()) / 1000;
  return dayStart - daysSinceMonday * SECONDS_PER_DAY;
}

/**
 * Aggregate points to the requested granularity. daily returns the input array
 * unchanged, the same reference, because every day already is one print, and
 * it keeps the input order exactly as given. weekly buckets points into UTC
 * Monday weeks and emits the mean of the finite y values at the bucket start,
 * in epoch seconds, and that weekly output is sorted by x ascending. Buckets
 * with no finite y are dropped rather than emitted as null, buckets whose mean
 * is not finite are dropped too, and buckets never carry duplicate x. Non
 * finite x and y values are ignored, as are points whose epoch does not round
 * trip through Date. Units: x is epoch seconds, y carries the series unit of
 * the input points.
 */
export function aggregateSeries(points: EpochPoint[], granularity: Granularity): EpochPoint[] {
  if (granularity === "daily") return points;
  const buckets = new Map<number, { sum: number; count: number }>();
  for (const point of points) {
    if (!Number.isFinite(point.x)) continue;
    if (typeof point.y !== "number" || !Number.isFinite(point.y)) continue;
    const start = utcMondayStart(point.x);
    if (!Number.isFinite(start)) continue;
    const bucket = buckets.get(start);
    if (bucket) {
      bucket.sum += point.y;
      bucket.count += 1;
    } else {
      buckets.set(start, { sum: point.y, count: 1 });
    }
  }
  const out: EpochPoint[] = [];
  for (const [x, bucket] of buckets) {
    const mean = bucket.sum / bucket.count;
    if (!Number.isFinite(mean)) continue;
    out.push({ x, y: mean });
  }
  out.sort((a, b) => a.x - b.x);
  return out;
}

/**
 * On screen label for the aggregation in effect. Units: none, these are
 * display strings, and the exact wording is asserted by tests because it
 * appears on the chart caption in Phase 8.4.
 */
export function aggregationLabel(granularity: Granularity): string {
  return granularity === "daily" ? "daily prints" : "weekly mean (UTC Monday buckets)";
}
