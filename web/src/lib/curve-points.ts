import type { CurveKnotRow, CurveSection } from "./types";

export interface ZeroPoint {
  x: number;
  y: number | null;
}

/** Tenor map for solved zeros in percent_yield. Null marks unavailable. */
export type ZeroYieldMap = Record<string, { value: number | null }>;

/**
 * Build chart points from the solved zero mapping, never from input YTM.
 * A knot without a finite solved zero plots as null, which the chart
 * renders as a gap, and the caller names as unavailable.
 */
export function zeroCurvePoints(
  knots: CurveKnotRow[],
  zeroYields: CurveSection["zero_yields"] | ZeroYieldMap | undefined | null,
): ZeroPoint[] {
  const map: ZeroYieldMap = zeroYields ?? {};
  return knots.map((knot) => {
    const raw = map[knot.tenor]?.value;
    const zero = typeof raw === "number" && Number.isFinite(raw) ? raw : null;
    return { x: knot.tenor_years, y: zero };
  });
}

/**
 * Tenors whose solved zero is absent or non finite, in knot order.
 * Units: input knots carry duration_years, zeros carry percent_yield.
 */
export function missingZeroTenors(
  knots: CurveKnotRow[],
  zeroYields: CurveSection["zero_yields"] | ZeroYieldMap | undefined | null,
): string[] {
  const map: ZeroYieldMap = zeroYields ?? {};
  return knots
    .filter((knot) => {
      const raw = map[knot.tenor]?.value;
      return !(typeof raw === "number" && Number.isFinite(raw));
    })
    .map((knot) => knot.tenor);
}
