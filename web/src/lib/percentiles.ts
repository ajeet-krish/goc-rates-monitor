import type { EpochPoint } from "./history";
import type { PercentileSummary } from "./types";

export type { PercentileSummary };

/**
 * Nearest rank percentile summary over the finite y values of points. Units:
 * p10, p50, p90, and latest carry the series unit of the input points, for
 * example percent or basis_points; latestRankPercent is a percent from 0 to
 * 100; count is a count of finite y values.
 *
 * Exact formula: sort the finite values ascending and take the value at index
 * ceil(k * n) clamped to [0, n - 1] for k in {0.10, 0.50, 0.90}, where n is
 * the count. With 100 values sorted 1 to 100 that gives p10 at index 10, p50
 * at index 50, and p90 at index 90, so p10 is 11, p50 is 51, and p90 is 91.
 *
 * latest is the y of the point with the greatest x, the first such point when
 * x ties, and is null when that y is null or not finite. latestRankPercent is
 * the count of finite values less than or equal to latest, divided by count,
 * times 100, and is null when latest is null. Returns null when fewer than
 * minCount finite values exist, or when there are none at all.
 */
export function percentileSummary(points: EpochPoint[], minCount = 60): PercentileSummary | null {
  const values: number[] = [];
  for (const point of points) {
    if (typeof point.y === "number" && Number.isFinite(point.y)) values.push(point.y);
  }
  const count = values.length;
  if (count === 0 || count < minCount) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const rank = (k: number): number =>
    sorted[Math.min(count - 1, Math.max(0, Math.ceil(k * count)))];
  let latestX = -Infinity;
  let latest: number | null = null;
  for (const point of points) {
    if (point.x > latestX) {
      latestX = point.x;
      latest = typeof point.y === "number" && Number.isFinite(point.y) ? point.y : null;
    }
  }
  let latestRankPercent: number | null = null;
  if (latest !== null) {
    let atOrBelow = 0;
    for (const value of values) {
      if (value <= latest) atOrBelow += 1;
    }
    latestRankPercent = (atOrBelow / count) * 100;
  }
  return { p10: rank(0.1), p50: rank(0.5), p90: rank(0.9), latest, latestRankPercent, count };
}
