import { isStrictIsoDate } from "./asof";
import type { DataIndex, SnapshotDoc, VerifyReport } from "./types";

export class ValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ValidationError";
  }
}

/** Mirrors Python ALLOWED_UNITS in src/goc_rates/models.py. */
export const ALLOWED_UNITS: ReadonlySet<string> = new Set([
  "percent",
  "basis_points",
  "index_points",
  "business_days",
  "price_units_per_100_face",
  "days",
  "percent_yield",
  "bp",
  "bp_per_annum",
  "duration_years",
  "dv01_per_million",
  "unitless_ratio",
  "percent_per_month",
  "percentage_points",
]);

/** Mirrors the closed Quality set in src/goc_rates/models.py. */
const ALLOWED_QUALITIES: ReadonlySet<string> = new Set([
  "observed",
  "missing",
  "stale",
  "revised",
]);

/** Expected check ids for a passing verify report, mirrors V01 to V22 in verify.py. */
export const EXPECTED_VERIFY_IDS: ReadonlyArray<string> = Array.from(
  { length: 22 },
  (_, i) => "V" + String(i + 1).padStart(2, "0")
);
/** Collection caps mirroring the Python pipeline in src/goc_rates/limits.py. */
export const MAX_KNOTS = 10;
export const MAX_SPREAD_RECORDS = 2000;
export const MAX_BACKTEST_OBS = 2000;
export const MAX_VERIFY_CHECKS = 22;
export const MAX_CPI_COMPONENTS = 128;
export const MAX_CPI_MONTHS = 240;
export const MAX_QUANTITIES = 10000;
export const MAX_INDEX_DATES = 2000;
export const MAX_PROVENANCE_ENTRIES = 64;
export const MAX_PROVENANCE_STRING = 2048;
export const MAX_WARNINGS = 256;
export const MAX_WARNING_LENGTH = 1024;
export const MAX_CHECK_DETAIL_LENGTH = 4096;
export const MAX_RULE_LENGTH = 256;
/**
 * Traversal guards for collectQuantities: the depth bound stops
 * pathological nesting from overflowing the call stack, and the node
 * bound stops wide payloads from exhausting memory before the
 * quantity cap can reject them.
 */
export const MAX_COLLECT_DEPTH = 64;
export const MAX_COLLECT_NODES = 200000;
/** Mirrors SOURCE_ID_PATTERN in src/goc_rates/models.py. */
const SOURCE_ID_PATTERN =
  /^(derived|valet|fred|statcan):[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;
const MAX_SOURCE_ID_LENGTH = 80;
const SHA256_HEX = /^[0-9a-f]{64}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function fail(path: string, detail: string): never {
  throw new ValidationError(path + ": " + detail);
}

function assertFiniteNumber(value: unknown, path: string): asserts value is number {
  if (typeof value === "boolean" || typeof value !== "number" || !Number.isFinite(value)) {
    fail(path, "must be a finite number, got non numeric or non finite value");
  }
}

function assertSourceId(value: unknown, path: string): asserts value is string {
  if (typeof value !== "string" || value.length === 0) {
    fail(path, "source_id must be a non empty string");
  }
  const text = value as string;
  if (text.length > MAX_SOURCE_ID_LENGTH) {
    fail(path, "source_id exceeds " + MAX_SOURCE_ID_LENGTH + " characters");
  }
  if (!SOURCE_ID_PATTERN.test(text)) {
    fail(path, "source_id uses an unknown grammar: " + JSON.stringify(text));
  }
}

/** Validate one quantity dict. Mirrors validate_quantity in models.py. */
export function assertQuantity(node: unknown, path: string): void {
  if (!isRecord(node)) {
    fail(path, "quantity must be an object");
  }
  for (const key of ["value", "unit", "quality", "source_id"]) {
    if (!(key in node)) {
      fail(path, "quantity is missing required key: " + key);
    }
  }
  const { value, unit, quality, source_id } = node;
  if (typeof unit !== "string" || !ALLOWED_UNITS.has(unit)) {
    fail(path, "unit is not in the closed unit set: " + JSON.stringify(unit));
  }
  if (typeof quality !== "string" || !ALLOWED_QUALITIES.has(quality)) {
    fail(path, "quality is not in the closed quality set: " + JSON.stringify(quality));
  }
  assertSourceId(source_id, path + ".source_id");
  if (quality === "missing") {
    if (value !== null) {
      fail(path, "missing quality quantity must have value null");
    }
    return;
  }
  assertFiniteNumber(value, path + ".value");
}

function assertDerivedSource(sourceId: string, path: string): void {
  if (!sourceId.startsWith("derived:")) {
    fail(
      path,
      "derived quantity source_id must use the derived prefix: " + JSON.stringify(sourceId)
    );
  }
}

/**
 * Collect every quantity shaped node, mirroring _quantities in verify.py.
 * Bounded by MAX_COLLECT_DEPTH (nesting), MAX_COLLECT_NODES (visited
 * nodes), and MAX_QUANTITIES (collected quantities): any excess rejects
 * the payload instead of recursing or allocating without limit.
 */
function collectQuantities(
  node: unknown,
  found: Array<{ node: unknown; path: string }>,
  path: string,
  depth: number,
  seen: { visited: number }
): void {
  seen.visited += 1;
  if (seen.visited > MAX_COLLECT_NODES) {
    fail(path, "observations exceed the " + MAX_COLLECT_NODES + " node traversal cap");
  }
  if (depth > MAX_COLLECT_DEPTH) {
    fail(path, "observations exceed the " + MAX_COLLECT_DEPTH + " level nesting cap");
  }
  if (Array.isArray(node)) {
    node.forEach((child, i) => collectQuantities(child, found, path + "[" + i + "]", depth + 1, seen));
    return;
  }
  if (isRecord(node)) {
    if ("value" in node && "unit" in node && "quality" in node && "source_id" in node) {
      if (found.length >= MAX_QUANTITIES) {
        fail(path, "observations exceed the " + MAX_QUANTITIES + " quantity cap");
      }
      found.push({ node, path });
      return;
    }
    for (const [key, child] of Object.entries(node)) {
      collectQuantities(child, found, path + "." + key, depth + 1, seen);
    }
  }
}

function assertIsoDate(value: unknown, path: string): asserts value is string {
  if (typeof value !== "string" || !isStrictIsoDate(value)) {
    fail(path, "must be a strict ISO YYYY-MM-DD date: " + JSON.stringify(value));
  }
}

/** Validate a snapshot document. Rejects malformed payloads and asof mismatches. */
export function validateSnapshot(doc: unknown, expectedAsof: string): SnapshotDoc {
  if (!isRecord(doc)) {
    fail("snapshot", "document must be an object");
  }
  const metadata = doc.metadata;
  if (!isRecord(metadata)) {
    fail("snapshot.metadata", "metadata must be an object");
  }
  assertIsoDate(metadata.snapshot_date, "snapshot.metadata.snapshot_date");
  if (metadata.snapshot_date !== expectedAsof) {
    fail(
      "snapshot.metadata.snapshot_date",
      "snapshot_date " +
        JSON.stringify(metadata.snapshot_date) +
        " does not match requested asof " +
        JSON.stringify(expectedAsof)
    );
  }
  const observations = doc.observations;
  if (!isRecord(observations)) {
    fail("snapshot.observations", "observations must be an object");
  }

  const benchmarks = observations.benchmarks;
  if (benchmarks !== undefined) {
    if (!isRecord(benchmarks)) {
      fail("snapshot.observations.benchmarks", "benchmarks must be an object");
    }
    for (const [tenor, entry] of Object.entries(benchmarks)) {
      if (!isRecord(entry)) {
        fail("snapshot.observations.benchmarks." + tenor, "benchmark entry must be an object");
      }
      if (typeof entry.valet_label !== "string" || entry.valet_label.length === 0) {
        fail("snapshot.observations.benchmarks." + tenor, "valet_label must be a non empty string");
      }
      assertQuantity(entry.valet, "snapshot.observations.benchmarks." + tenor + ".valet");
    }
  }

  const diff = observations.cross_source_diff_bp;
  if (diff !== undefined) {
    if (!isRecord(diff)) {
      fail("snapshot.observations.cross_source_diff_bp", "must be an object");
    }
    assertFiniteNumber(diff.value_bp, "snapshot.observations.cross_source_diff_bp.value_bp");
    if (typeof diff.unit !== "string" || !ALLOWED_UNITS.has(diff.unit)) {
      fail("snapshot.observations.cross_source_diff_bp.unit", "unit is not in the closed unit set");
    }
  }

  const staleness = observations.staleness;
  if (staleness !== undefined) {
    if (!isRecord(staleness)) {
      fail("snapshot.observations.staleness", "must be an object");
    }
    assertFiniteNumber(
      staleness.max_age_business_days,
      "snapshot.observations.staleness.max_age_business_days"
    );
    if (typeof staleness.unit !== "string" || !ALLOWED_UNITS.has(staleness.unit)) {
      fail("snapshot.observations.staleness.unit", "unit is not in the closed unit set");
    }
  }

  const curve = observations.curve;
  if (curve !== undefined) {
    if (!isRecord(curve)) {
      fail("snapshot.observations.curve", "curve must be an object");
    }
    if (typeof curve.method !== "string" || curve.method.length === 0) {
      fail("snapshot.observations.curve.method", "method must be a non empty string");
    }
    if (typeof curve.is_par_approx !== "boolean" || typeof curve.is_zero !== "boolean") {
      fail("snapshot.observations.curve", "is_par_approx and is_zero must be booleans");
    }
    if (!Array.isArray(curve.knots)) {
      fail("snapshot.observations.curve.knots", "knots must be an array");
    }
    if (curve.knots.length > MAX_KNOTS) {
      fail(
        "snapshot.observations.curve.knots",
        "knots exceed the " + MAX_KNOTS + " entry cap, got " + curve.knots.length
      );
    }
    curve.knots.forEach((knot: unknown, i: number) => {
      const path = "snapshot.observations.curve.knots[" + i + "]";
      if (!isRecord(knot)) {
        fail(path, "knot must be an object");
      }
      if (typeof knot.tenor !== "string" || knot.tenor.length === 0) {
        fail(path + ".tenor", "tenor must be a non empty string");
      }
      assertFiniteNumber(knot.tenor_years, path + ".tenor_years");
      assertFiniteNumber(knot.yield_percent, path + ".yield_percent");
      assertFiniteNumber(knot.discount, path + ".discount");
      for (const key of ["tenor_unit", "yield_unit", "discount_unit"]) {
        if (typeof knot[key] !== "string" || !ALLOWED_UNITS.has(knot[key] as string)) {
          fail(path + "." + key, "unit is not in the closed unit set");
        }
      }
      assertSourceId(knot.source_id, path + ".source_id");
    });
    for (const key of ["discounts", "zero_yields"]) {
      const mapping = curve[key];
      if (mapping !== undefined) {
        if (!isRecord(mapping)) {
          fail("snapshot.observations.curve." + key, "must be an object");
        }
        const names = Object.keys(mapping);
        if (names.length > MAX_KNOTS) {
          fail(
            "snapshot.observations.curve." + key,
            "entries exceed the " + MAX_KNOTS + " entry cap, got " + names.length
          );
        }
        for (const [tenor, quantity] of Object.entries(mapping)) {
          const path = "snapshot.observations.curve." + key + "." + tenor;
          assertQuantity(quantity, path);
          assertDerivedSource((quantity as Record<string, unknown>).source_id as string, path);
        }
      }
    }
    if (typeof curve.curve_source_id !== "string") {
      fail("snapshot.observations.curve.curve_source_id", "must be a string");
    }
    assertSourceId(curve.curve_source_id, "snapshot.observations.curve.curve_source_id");
    assertDerivedSource(curve.curve_source_id, "snapshot.observations.curve.curve_source_id");
  }

  const spreads = observations.spreads;
  if (spreads !== undefined) {
    if (!Array.isArray(spreads)) {
      fail("snapshot.observations.spreads", "spreads must be an array");
    }
    if (spreads.length > MAX_SPREAD_RECORDS) {
      fail(
        "snapshot.observations.spreads",
        "spreads exceed the " + MAX_SPREAD_RECORDS + " record cap, got " + spreads.length
      );
    }
    spreads.forEach((record: unknown, i: number) => {
      const path = "snapshot.observations.spreads[" + i + "]";
      if (!isRecord(record)) {
        fail(path, "spread record must be an object");
      }
      assertIsoDate(record.date, path + ".date");
      assertIsoDate(record.ca_date, path + ".ca_date");
      assertIsoDate(record.us_date, path + ".us_date");
      if (record.ca_date !== record.date || record.us_date !== record.date) {
        fail(path, "ca_date and us_date must equal date");
      }
      assertFiniteNumber(record.ca_yield_percent, path + ".ca_yield_percent");
      assertFiniteNumber(record.us_yield_percent, path + ".us_yield_percent");
      assertFiniteNumber(record.spread_bp, path + ".spread_bp");
    });
  }

  const carry = observations.carry;
  if (carry !== undefined) {
    if (!isRecord(carry)) {
      fail("snapshot.observations.carry", "carry must be an object");
    }
    assertFiniteNumber(carry.yield_at_maturity_percent, "snapshot.observations.carry.yield_at_maturity_percent");
    assertFiniteNumber(
      carry.yield_at_rolled_tenor_percent,
      "snapshot.observations.carry.yield_at_rolled_tenor_percent"
    );
    assertFiniteNumber(carry.horizon_years, "snapshot.observations.carry.horizon_years");
    assertFiniteNumber(carry.carry_roll_bp, "snapshot.observations.carry.carry_roll_bp");
  }

  const risk = observations.risk;
  if (risk !== undefined) {
    if (!isRecord(risk)) {
      fail("snapshot.observations.risk", "risk must be an object");
    }
    assertFiniteNumber(risk.yield_percent, "snapshot.observations.risk.yield_percent");
    assertFiniteNumber(risk.tenor_years, "snapshot.observations.risk.tenor_years");
    assertFiniteNumber(risk.price, "snapshot.observations.risk.price");
    assertFiniteNumber(risk.modified_duration_years, "snapshot.observations.risk.modified_duration_years");
    assertFiniteNumber(risk.dv01_per_million, "snapshot.observations.risk.dv01_per_million");
  }

  const backtest = observations.backtest;
  if (backtest !== undefined) {    if (!isRecord(backtest)) {
      fail("snapshot.observations.backtest", "backtest must be an object");
    }
    if (typeof backtest.rule !== "string" || backtest.rule.length === 0) {
      fail("snapshot.observations.backtest.rule", "rule must be a non empty string");
    }
    if (backtest.rule.length > MAX_RULE_LENGTH) {
      fail(
        "snapshot.observations.backtest.rule",
        "rule exceeds the " + MAX_RULE_LENGTH + " character cap"
      );
    }
    if (!Array.isArray(backtest.dates) || !Array.isArray(backtest.slopes_bp)) {
      fail("snapshot.observations.backtest", "dates and slopes_bp must be arrays");
    }
    if (backtest.dates.length !== backtest.slopes_bp.length) {
      fail(
        "snapshot.observations.backtest",
        "dates (" + backtest.dates.length + ") and slopes_bp (" +
          backtest.slopes_bp.length + ") must have equal length"
      );
    }
    if (backtest.dates.length > MAX_BACKTEST_OBS) {
      fail(
        "snapshot.observations.backtest",
        "observations exceed the " + MAX_BACKTEST_OBS + " backtest cap, got " +
          backtest.dates.length
      );
    }
    backtest.dates.forEach((d: unknown, i: number) =>
      assertIsoDate(d, "snapshot.observations.backtest.dates[" + i + "]")
    );
    backtest.slopes_bp.forEach((s: unknown, i: number) =>
      assertFiniteNumber(s, "snapshot.observations.backtest.slopes_bp[" + i + "]")
    );
    assertFiniteNumber(backtest.total_pnl_bp, "snapshot.observations.backtest.total_pnl_bp");
  }

  assertInflation(observations.inflation);

  const provenance = doc.provenance;
  if (!isRecord(provenance)) {
    fail("snapshot.provenance", "provenance must be an object");
  }
  const provenanceNames = Object.keys(provenance);
  if (provenanceNames.length > MAX_PROVENANCE_ENTRIES) {
    fail(
      "snapshot.provenance",
      "provenance exceeds the " + MAX_PROVENANCE_ENTRIES + " entry cap, got " +
        provenanceNames.length
    );
  }
  for (const [name, entry] of Object.entries(provenance)) {
    if (!isRecord(entry)) {
      fail("snapshot.provenance." + name, "provenance entry must be an object");
    }
    for (const key of ["source_url", "retrieved_utc", "vintage"]) {
      if (typeof entry[key] !== "string" || (entry[key] as string).length === 0) {
        fail("snapshot.provenance." + name + "." + key, "must be a non empty string");
      }
      if ((entry[key] as string).length > MAX_PROVENANCE_STRING) {
        fail(
          "snapshot.provenance." + name + "." + key,
          "exceeds the " + MAX_PROVENANCE_STRING + " character cap"
        );
      }
    }
  }

  if (!Array.isArray(doc.warnings) || !doc.warnings.every((w) => typeof w === "string")) {
    fail("snapshot.warnings", "warnings must be an array of strings");
  }
  if (doc.warnings.length > MAX_WARNINGS) {
    fail(
      "snapshot.warnings",
      "warnings exceed the " + MAX_WARNINGS + " entry cap, got " + doc.warnings.length
    );
  }
  doc.warnings.forEach((w: string, i: number) => {
    if (w.length > MAX_WARNING_LENGTH) {
      fail(
        "snapshot.warnings[" + i + "]",
        "warning exceeds the " + MAX_WARNING_LENGTH + " character cap"
      );
    }
  });

  const found: Array<{ node: unknown; path: string }> = [];
  collectQuantities(observations, found, "snapshot.observations", 0, { visited: 0 });
  if (found.length > MAX_QUANTITIES) {
    fail(
      "snapshot.observations",
      "quantities exceed the " + MAX_QUANTITIES + " quantity cap, got " + found.length
    );
  }
  for (const { node, path } of found) {
    assertQuantity(node, path);
  }

  return doc as unknown as SnapshotDoc;
}

/** Pinned CPI registry facts mirrored from config/cpi_components.yaml. */
const CPI_COMPONENT_COUNT = 55;
const CPI_HISTORY_MONTHS = 12;
const CPI_INDEX_MONTHS = 2;
const CPI_LINK_MONTH = "2025-05";
const CPI_EXPENDITURE_YEAR = 2024;
const CPI_GATE_PP = 0.1;
const CPI_MIN_MONTHS = 24;
const CPI_METHOD = "cpi_trim_median_weighted_sa_v1";
const CPI_HEADLINE_SOURCE = "derived:cpi_trim_median";
const CPI_BULK_PRODUCT_IDS: Record<string, number> = {
  cpi_monthly: 18100004,
  core_statistics: 18100256,
  basket_weights: 18100007,
};
const MONTH_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/;

function assertMonth(value: unknown, path: string): asserts value is string {
  if (typeof value !== "string" || !MONTH_PATTERN.test(value)) {
    fail(path, "must be a YYYY-MM month: " + JSON.stringify(value));
  }
}

/** Validate the experimental inflation section, mirroring V19 to V22 in verify.py. */
function assertInflation(node: unknown): void {
  if (node === undefined) return;
  const path = "snapshot.observations.inflation";
  if (!isRecord(node)) {
    fail(path, "inflation must be an object");
  }
  if (node.label !== "experimental") {
    fail(path + ".label", "label must be experimental, got " + JSON.stringify(node.label));
  }
  if (node.is_official !== false) {
    fail(path + ".is_official", "is_official must be false");
  }
  if (node.method !== CPI_METHOD) {
    fail(
      path + ".method",
      "method must pin " + CPI_METHOD + ", got " + JSON.stringify(node.method)
    );
  }
  if (node.owns_seasonal_adjustment !== false) {
    fail(path + ".owns_seasonal_adjustment", "must be false: SA is reused as published");
  }
  if (node.seasonally_adjusted_source !== "statcan") {
    fail(path + ".seasonally_adjusted_source", "must be statcan");
  }
  if (node.component_count !== CPI_COMPONENT_COUNT) {
    fail(
      path + ".component_count",
      "must pin " + CPI_COMPONENT_COUNT + " components, got " + JSON.stringify(node.component_count)
    );
  }
  const vintage = node.weight_vintage;
  if (!isRecord(vintage)) {
    fail(path + ".weight_vintage", "weight_vintage must be an object");
  }
  if (vintage.expenditure_year !== CPI_EXPENDITURE_YEAR) {
    fail(path + ".weight_vintage.expenditure_year", "must pin " + CPI_EXPENDITURE_YEAR);
  }
  if (vintage.link_month !== CPI_LINK_MONTH) {
    fail(path + ".weight_vintage.link_month", "must pin " + CPI_LINK_MONTH);
  }
  if (typeof vintage.provisional !== "boolean") {
    fail(path + ".weight_vintage.provisional", "must be a boolean");
  }
  assertMonth(node.reference_month, path + ".reference_month");

  const indexes = node.indexes;
  if (!isRecord(indexes)) {
    fail(path + ".indexes", "indexes must be an object");
  }
  if (!Array.isArray(indexes.months) || indexes.months.length !== CPI_INDEX_MONTHS) {
    fail(path + ".indexes.months", "must hold exactly " + CPI_INDEX_MONTHS + " months");
  }
  indexes.months.forEach((m: unknown, i: number) => assertMonth(m, path + ".indexes.months[" + i + "]"));
  for (const key of ["trim", "median"]) {
    const series = (indexes as Record<string, unknown>)[key];
    if (!Array.isArray(series) || series.length !== CPI_INDEX_MONTHS) {
      fail(path + ".indexes." + key, "must hold exactly " + CPI_INDEX_MONTHS + " quantities");
    }
    series.forEach((q: unknown, i: number) => assertQuantity(q, path + ".indexes." + key + "[" + i + "]"));
  }

  const latest = node.latest;
  if (!isRecord(latest)) {
    fail(path + ".latest", "latest must be an object");
  }
  assertMonth(latest.month, path + ".latest.month");
  assertQuantity(latest.trim_mom, path + ".latest.trim_mom");
  assertQuantity(latest.median_mom, path + ".latest.median_mom");
  assertQuantity(latest.trim_yoy, path + ".latest.trim_yoy");
  assertQuantity(latest.median_yoy, path + ".latest.median_yoy");
  if ((latest.trim_mom as { unit: unknown }).unit !== "percent_per_month") {
    fail(path + ".latest.trim_mom", "unit must be percent_per_month");
  }
  if (typeof latest.median_component !== "string" || latest.median_component.length === 0) {
    fail(path + ".latest.median_component", "must be a non empty string");
  }

  if (!Array.isArray(node.history) || node.history.length !== CPI_HISTORY_MONTHS) {
    fail(path + ".history", "must hold exactly " + CPI_HISTORY_MONTHS + " months");
  }
  node.history.forEach((row: unknown, i: number) => {
    const rowPath = path + ".history[" + i + "]";
    if (!isRecord(row)) {
      fail(rowPath, "history row must be an object");
    }
    assertMonth(row.month, rowPath + ".month");
    assertFiniteNumber(row.trim_mom_percent, rowPath + ".trim_mom_percent");
    assertFiniteNumber(row.median_mom_percent, rowPath + ".median_mom_percent");
  });

  if (!Array.isArray(node.contributions) || node.contributions.length !== CPI_COMPONENT_COUNT) {
    fail(path + ".contributions", "must list one row per component");
  }
  if (node.contributions.length > MAX_CPI_COMPONENTS) {
    fail(path + ".contributions", "exceeds the " + MAX_CPI_COMPONENTS + " component cap");
  }
  let weightTotal = 0;
  let recomputedTotal = 0;
  let worstRowDiff = 0;
  const seenComponents = new Set<string>();
  const componentIds: string[] = [];
  node.contributions.forEach((row: unknown, i: number) => {
    const rowPath = path + ".contributions[" + i + "]";
    if (!isRecord(row)) {
      fail(rowPath, "contribution row must be an object");
    }
    if (typeof row.component_id !== "string" || row.component_id.length === 0) {
      fail(rowPath + ".component_id", "must be a non empty string");
    }
    if (seenComponents.has(row.component_id as string)) {
      fail(rowPath + ".component_id", "duplicate component_id " + JSON.stringify(row.component_id));
    }
    seenComponents.add(row.component_id as string);
    componentIds.push(row.component_id as string);
    assertFiniteNumber(row.monthly_rate_percent, rowPath + ".monthly_rate_percent");
    assertFiniteNumber(row.weight_percent, rowPath + ".weight_percent");
    assertFiniteNumber(row.contribution_pp, rowPath + ".contribution_pp");
    const expected = ((row.weight_percent as number) * (row.monthly_rate_percent as number)) / 100;
    const rowDiff = Math.abs(expected - (row.contribution_pp as number));
    worstRowDiff = Math.max(worstRowDiff, rowDiff);
    if (rowDiff > 0.01) {
      fail(
        rowPath + ".contribution_pp",
        "must recompute as weight_percent * monthly_rate_percent / 100 within 0.01 pp, " +
          "expected " + expected + " got " + (row.contribution_pp as number)
      );
    }
    recomputedTotal += expected;
    weightTotal += row.weight_percent as number;
  });
  if (Math.abs(weightTotal - 100) > 1e-6) {
    fail(path + ".contributions", "weights sum to " + weightTotal + ", expected 100 within 1e-6");
  }
  assertFiniteNumber(node.total_contribution_pp, path + ".total_contribution_pp");
  if (Math.abs((node.total_contribution_pp as number) - recomputedTotal) > 0.01) {
    fail(
      path + ".total_contribution_pp",
      "must match recomputed weight * rate / 100 total within 0.01 pp, " +
        "recomputed " + recomputedTotal + " stored " + (node.total_contribution_pp as number)
    );
  }
  if (!isRecord(node.headline_mom)) {
    fail(path + ".headline_mom", "headline_mom quantity is missing");
  }
  assertQuantity(node.headline_mom, path + ".headline_mom");
  if ((node.headline_mom as { unit: unknown }).unit !== "percent_per_month") {
    fail(path + ".headline_mom", "unit must be percent_per_month");
  }
  if ((node.headline_mom as { source_id: unknown }).source_id !== CPI_HEADLINE_SOURCE) {
    fail(path + ".headline_mom", "source_id must be " + CPI_HEADLINE_SOURCE);
  }
  if (Math.abs(((node.headline_mom as { value: number }).value as number) - recomputedTotal) > 0.01) {
    fail(
      path + ".headline_mom",
      "value must match the recomputed weighted mean within 0.01 pp"
    );
  }
  if (!componentIds.includes(latest.median_component as string)) {
    fail(
      path + ".latest.median_component",
      "must name one contribution row, got " + JSON.stringify(latest.median_component)
    );
  }
  {
    const rows = node.contributions as Array<{
      component_id: string;
      monthly_rate_percent: number;
      median_component?: unknown;
      weight_percent: number;
    }>;
    const ordered = [...rows].sort((a, b) => {
      if (a.monthly_rate_percent !== b.monthly_rate_percent) {
        return (
          (a.monthly_rate_percent as number) - (b.monthly_rate_percent as number)
        );
      }
      return a.component_id < b.component_id ? -1 : a.component_id > b.component_id ? 1 : 0;
    });
    let cumulative = 0;
    let medianRate = 0;
    let medianId = "";
    let trimNumerator = 0;
    let keptTotal = 0;
    for (const row of ordered) {
      const fraction = (row.weight_percent as number) / 100;
      const previous = cumulative;
      cumulative += fraction;
      if (medianId === "" && cumulative > 0.5) {
        medianRate = row.monthly_rate_percent as number;
        medianId = row.component_id as string;
      }
      const kept = Math.max(
        0,
        Math.min(cumulative, 0.8) - Math.max(previous, 0.2)
      );
      trimNumerator += (row.monthly_rate_percent as number) * kept;
      keptTotal += kept;
    }
    const recomputedTrim = trimNumerator / keptTotal;
    const storedTrim = ((latest.trim_mom as unknown as { value: number }).value as number);
    const storedMedian = ((latest.median_mom as unknown as { value: number }).value as number);
    if (medianId !== (latest.median_component as string)) {
      fail(
        path + ".latest.median_component",
        "must match the recomputed weighted median " + JSON.stringify(medianId) +
          ", got " + JSON.stringify(latest.median_component)
      );
    }
    if (Math.abs(recomputedTrim - storedTrim) > 0.01) {
      fail(
        path + ".latest.trim_mom",
        "must match the recomputed weighted trim within 0.01, recomputed " +
          recomputedTrim + " stored " + storedTrim
      );
    }
    if (Math.abs(medianRate - storedMedian) > 0.01) {
      fail(
        path + ".latest.median_mom",
        "must match the recomputed weighted median within 0.01, recomputed " +
          medianRate + " stored " + storedMedian
      );
    }
  }
  {
    const historyRows = node.history as Array<{ trim_mom_percent: number; median_mom_percent: number }>;
    const compound = (monthly: number[]): number => {
      let factor = 1;
      for (const m of monthly) factor *= 1 + m / 100;
      return (factor - 1) * 100;
    };
    const trailingTrim = historyRows.map((r) => r.trim_mom_percent as number);
    const trailingMedian = historyRows.map((r) => r.median_mom_percent as number);
    const expectedTrimYoy = compound(trailingTrim.slice(-12));
    const expectedMedianYoy = compound(trailingMedian.slice(-12));
    if (Math.abs(expectedTrimYoy - ((latest.trim_yoy as { value: number }).value as number)) > 0.01) {
      fail(
        path + ".latest.trim_yoy",
        "must compound the trailing 12 history moms within 0.01, expected " +
          expectedTrimYoy
      );
    }
    if (
      Math.abs(expectedMedianYoy - ((latest.median_yoy as { value: number }).value as number)) > 0.01
    ) {
      fail(
        path + ".latest.median_yoy",
        "must compound the trailing 12 history moms within 0.01, expected " +
          expectedMedianYoy
      );
    }
  }
  assertFiniteNumber(node.kept_weight_fraction, path + ".kept_weight_fraction");
  assertFiniteNumber(node.excluded_weight_fraction, path + ".excluded_weight_fraction");
  if (Math.abs((node.excluded_weight_fraction as number) - 0.4) > 1e-6) {
    fail(path + ".excluded_weight_fraction", "must pin 0.40 within 1e-6");
  }

  const validation = node.validation;
  if (!isRecord(validation)) {
    fail(path + ".validation", "validation must be an object");
  }
  if (
    typeof validation.months !== "number" ||
    !Number.isInteger(validation.months) ||
    validation.months < CPI_MIN_MONTHS
  ) {
    fail(path + ".validation.months", "must be an integer of at least " + CPI_MIN_MONTHS);
  }
  if (Math.abs((validation.gate_pp as number) - CPI_GATE_PP) > 1e-12) {
    fail(path + ".validation.gate_pp", "must pin " + CPI_GATE_PP);
  }
  for (const key of ["trim", "median"]) {
    const block = (validation as Record<string, unknown>)[key];
    const residuals = (validation as Record<string, unknown>)["residuals_" + key + "_pp"];
    if (!isRecord(block)) {
      fail(path + ".validation." + key, "must be an object");
    }
    if (!Array.isArray(residuals) || residuals.length !== validation.months) {
      fail(path + ".validation.residuals_" + key + "_pp", "must match validation months");
    }
    const numbers = (residuals as unknown[]).map((r, i) => {
      assertFiniteNumber(r, path + ".validation.residuals_" + key + "_pp[" + i + "]");
      return r as number;
    });
    const mae = numbers.reduce((a, b) => a + Math.abs(b), 0) / numbers.length;
    const bias = numbers.reduce((a, b) => a + b, 0) / numbers.length;
    const maxAbs = Math.max(...numbers.map((r) => Math.abs(r)));
    if (Math.abs(mae - (block.mae_pp as number)) > 1e-9) {
      fail(path + ".validation." + key, "MAE does not recompute from residuals");
    }
    if (Math.abs(bias - (block.bias_pp as number)) > 1e-9) {
      fail(path + ".validation." + key, "bias does not recompute from residuals");
    }
    if (Math.abs(maxAbs - (block.max_abs_resid_pp as number)) > 1e-9) {
      fail(path + ".validation." + key, "max residual does not recompute");
    }
  }
  const trimMae = (validation.trim as { mae_pp: number }).mae_pp;
  const medianMae = (validation.median as { mae_pp: number }).mae_pp;
  const expectedExceeds = trimMae > CPI_GATE_PP || medianMae > CPI_GATE_PP;
  if (validation.exceeds_gate !== expectedExceeds) {
    fail(path + ".validation.exceeds_gate", "must match the recomputed gate outcome");
  }
  const expectedFlag = expectedExceeds ? "exceeds_gate_needs_explanation" : "within_gate";
  if (validation.flag !== expectedFlag) {
    fail(
      path + ".validation.flag",
      "must pin " + expectedFlag + " for the recomputed gate outcome, got " +
        JSON.stringify(validation.flag)
    );
  }

  const bulk = node.bulk;
  if (!isRecord(bulk)) {
    fail(path + ".bulk", "bulk must be an object");
  }
  const names = Object.keys(bulk).sort();
  const expected = ["basket_weights", "core_statistics", "cpi_monthly"];
  if (JSON.stringify(names) !== JSON.stringify(expected)) {
    fail(path + ".bulk", "must pin the three products, got " + JSON.stringify(names));
  }
  for (const [name, entry] of Object.entries(bulk)) {
    const entryPath = path + ".bulk." + name;
    if (!isRecord(entry)) {
      fail(entryPath, "bulk entry must be an object");
    }
    assertFiniteNumber(entry.product_id, entryPath + ".product_id");
    if (!Number.isInteger(entry.product_id) || !/^[1-9][0-9]{7}$/.test(String(entry.product_id))) {
      fail(entryPath + ".product_id", "must be an 8 digit product id");
    }
    if ((entry.product_id as number) !== CPI_BULK_PRODUCT_IDS[name]) {
      fail(
        entryPath + ".product_id",
        "must pin " + CPI_BULK_PRODUCT_IDS[name] + " for " + name +
          ", got " + (entry.product_id as number)
      );
    }
    if (typeof entry.zip_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(entry.zip_sha256)) {
      fail(entryPath + ".zip_sha256", "must be a 64 character lowercase hex digest");
    }
    if (entry.zip_sha12 !== (entry.zip_sha256 as string).slice(0, 12)) {
      fail(entryPath + ".zip_sha12", "must prefix its sha256");
    }
  }
}

/** Validate a verify report, including count consistency and digest match. */
export function validateVerify(doc: unknown, expectedDigest?: string): VerifyReport {
  if (!isRecord(doc)) {
    fail("verify", "report must be an object");
  }
  assertFiniteNumber(doc.tolerance_bp, "verify.tolerance_bp");
  if (typeof doc.tolerance_unit !== "string" || !ALLOWED_UNITS.has(doc.tolerance_unit)) {
    fail("verify.tolerance_unit", "tolerance unit is not in the closed unit set");
  }
  for (const key of ["passed_count", "failed_count"]) {
    const value = doc[key];
    if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
      fail("verify." + key, "must be a non negative integer");
    }
  }
  if (typeof doc.passed !== "boolean") {
    fail("verify.passed", "must be a boolean");
  }
  if (!Array.isArray(doc.checks)) {
    fail("verify.checks", "checks must be an array");
  }
  doc.checks.forEach((check: unknown, i: number) => {
    const path = "verify.checks[" + i + "]";
    if (!isRecord(check)) {
      fail(path, "check must be an object");
    }
    if (typeof check.id !== "string" || check.id.length === 0) {
      fail(path + ".id", "id must be a non empty string");
    }
    if (typeof check.passed !== "boolean") {
      fail(path + ".passed", "passed must be a boolean");
    }
    if (typeof check.detail !== "string") {
      fail(path + ".detail", "detail must be a string");
    }
    if (check.detail.length > MAX_CHECK_DETAIL_LENGTH) {
      fail(
        path + ".detail",
        "detail exceeds the " + MAX_CHECK_DETAIL_LENGTH + " character cap"
      );
    }
  });
  if ((doc.checks as unknown[]).length !== MAX_VERIFY_CHECKS) {
    fail(
      "verify.checks",
      "report must contain exactly " + MAX_VERIFY_CHECKS + " checks (V01 to V22), got " +
        (doc.checks as unknown[]).length
    );
  }
  const passedCount = doc.passed_count as number;
  const failedCount = doc.failed_count as number;
  const checks = doc.checks as Array<{ passed: boolean; id: string }>;
  const ids = checks.map((c) => c.id);
  const unique = new Set(ids);
  if (unique.size !== ids.length) {
    fail("verify.checks", "report check ids must be unique");
  }
  const missing = EXPECTED_VERIFY_IDS.filter((id) => !unique.has(id));
  const extra = ids.filter((id) => !(EXPECTED_VERIFY_IDS as ReadonlyArray<string>).includes(id));
  if (missing.length > 0 || extra.length > 0) {
    fail(
      "verify.checks",
      "report must contain exactly V01 to V22, missing " +
        JSON.stringify(missing) +
        " extra " +
        JSON.stringify(extra)
    );
  }
  const actualPassed = checks.filter((c) => c.passed).length;
  if (passedCount !== actualPassed || failedCount !== checks.length - actualPassed) {
    fail(
      "verify",
      "passed_count " +
        passedCount +
        " and failed_count " +
        failedCount +
        " are inconsistent with checks array (" +
        actualPassed +
        " passed of " +
        checks.length +
        ")"
    );
  }
  if (doc.passed !== (failedCount === 0)) {
    fail("verify.passed", "passed flag is inconsistent with failed_count " + failedCount);
  }
  if (doc.snapshot_sha256 !== undefined) {
    if (typeof doc.snapshot_sha256 !== "string" || !SHA256_HEX.test(doc.snapshot_sha256)) {
      fail("verify.snapshot_sha256", "must be a 64 character lowercase hex digest");
    }
  }
  if (expectedDigest !== undefined) {
    if (doc.snapshot_sha256 !== expectedDigest) {
      fail(
        "verify.snapshot_sha256",
        "verify digest does not match the published snapshot digest for this date"
      );
    }
  }
  return doc as unknown as VerifyReport;
}

/** Validate the publish index. */
export function validateIndex(doc: unknown): DataIndex {
  if (!isRecord(doc)) {
    fail("index", "index must be an object");
  }
  if (!Array.isArray(doc.dates)) {
    fail("index.dates", "dates must be an array");
  }
  if (doc.dates.length > MAX_INDEX_DATES) {
    fail(
      "index.dates",
      "dates exceed the " + MAX_INDEX_DATES + " date cap, got " + doc.dates.length
    );
  }
  doc.dates.forEach((d: unknown, i: number) => assertIsoDate(d, "index.dates[" + i + "]"));
  if (doc.latest !== null) {
    assertIsoDate(doc.latest, "index.latest");
    if (!(doc.dates as string[]).includes(doc.latest as string)) {
      fail("index.latest", "latest date is not listed in dates");
    }
  }
  if (!isRecord(doc.entries)) {
    fail("index.entries", "entries must be an object");
  }
  for (const date of doc.dates as string[]) {
    const entry = (doc.entries as Record<string, unknown>)[date];
    if (!isRecord(entry)) {
      fail("index.entries." + date, "entry must be an object");
    }
    if (typeof entry.snapshot_sha256 !== "string" || !SHA256_HEX.test(entry.snapshot_sha256)) {
      fail("index.entries." + date + ".snapshot_sha256", "must be a 64 character lowercase hex digest");
    }
    if (typeof entry.verify_passed !== "boolean" && entry.verify_passed !== null) {
      fail("index.entries." + date + ".verify_passed", "must be a boolean or null");
    }
    if (
      typeof entry.bytes_utf8 !== "number" ||
      !Number.isInteger(entry.bytes_utf8) ||
      entry.bytes_utf8 <= 0
    ) {
      fail("index.entries." + date + ".bytes_utf8", "must be a positive integer");
    }
  }
  return doc as unknown as DataIndex;
}
