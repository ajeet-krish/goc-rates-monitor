import { isStrictIsoDate } from "./asof";
import type { DataIndex, SnapshotDoc, SpreadTenor, VerifyReport } from "./types";

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
  "count",
]);

/** Mirrors the closed Quality set in src/goc_rates/models.py. */
const ALLOWED_QUALITIES: ReadonlySet<string> = new Set([
  "observed",
  "missing",
  "stale",
  "revised",
]);

/** Expected check ids for a passing verify report, mirrors V01 to V25 in verify.py. */
export const EXPECTED_VERIFY_IDS: ReadonlyArray<string> = Array.from(
  { length: 25 },
  (_, i) => "V" + String(i + 1).padStart(2, "0")
);
/** Closed spread tenor set, mirrors the benchmark map in config/benchmark_map.yaml. */
export const ALLOWED_SPREAD_TENORS: ReadonlyArray<SpreadTenor> = ["2Y", "5Y", "10Y", "30Y"];
/** Collection caps mirroring the Python pipeline in src/goc_rates/limits.py. */
export const MAX_KNOTS = 10;
export const MAX_SPREAD_RECORDS = 2000;
export const MAX_BACKTEST_OBS = 2000;
export const MAX_VERIFY_CHECKS = 25;
export const MAX_CPI_COMPONENTS = 128;
export const MAX_CPI_MONTHS = 240;
export const MAX_SWITCH_EVENTS = 64;
export const MAX_DOD_RECORDS = 4;
export const MAX_HISTORY_OBS = 2000;
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
/** Curve method ids mirrored from src/goc_rates/curve.py and bootstrap.py. */
const PAR_METHOD = "par_approx_semiannual_log_discount_v1";
const BOOTSTRAP_METHOD = "true_bootstrap_semiannual_log_discount_v1";
/** Bootstrap instrument and anchor caps mirror limits.py cashflow and knot caps. */
const MAX_CASHFLOWS_PER_INSTRUMENT = 130;
const MAX_BOOTSTRAP_ROWS = 10;
const MAX_TENOR_YEARS = 60;

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

/**
 * Validate true bootstrap fields, mirroring build_bootstrap_curve_section
 * in src/goc_rates/bootstrap.py. Fields validate when present so legacy
 * par approx snapshots still load, but the bootstrap method id requires
 * the full contract: is_par_approx false, is_zero true, a settlement
 * date, per instrument cashflows with dirty prices and reprice errors
 * in bp, and solved discount anchors. Knot, instrument, and anchor
 * tenor sets must agree when all three are present.
 */
function assertBootstrapInstrument(node: unknown, path: string): void {
  if (!isRecord(node)) {
    fail(path, "instrument must be an object");
  }
  if (typeof node.tenor !== "string" || node.tenor.length === 0) {
    fail(path + ".tenor", "tenor must be a non empty string");
  }
  assertIsoDate(node.maturity_date, path + ".maturity_date");
  assertFiniteNumber(node.coupon_percent, path + ".coupon_percent");
  if (node.coupon_unit !== "percent") {
    fail(path + ".coupon_unit", "coupon unit must be percent, got " + JSON.stringify(node.coupon_unit));
  }
  if (node.yield_percent !== undefined) {
    assertFiniteNumber(node.yield_percent, path + ".yield_percent");
  }
  if (node.yield_unit !== undefined && node.yield_unit !== "percent_yield" && node.yield_unit !== "percent") {
    fail(path + ".yield_unit", "yield unit must be percent_yield or percent");
  }
  const count = node.cashflow_count;
  if (typeof count !== "number" || !Number.isInteger(count) || count <= 0) {
    fail(path + ".cashflow_count", "cashflow_count must be a positive integer");
  }
  if (count > MAX_CASHFLOWS_PER_INSTRUMENT) {
    fail(
      path + ".cashflow_count",
      "cashflow_count exceeds the " + MAX_CASHFLOWS_PER_INSTRUMENT + " cap, got " + count
    );
  }
  if (node.cashflow_count_unit !== undefined && node.cashflow_count_unit !== "count") {
    fail(path + ".cashflow_count_unit", "cashflow_count unit must be count");
  }
  const dirty = node.dirty_price;
  if (isRecord(dirty)) {
    assertFiniteNumber(dirty.value, path + ".dirty_price.value");
    if ((dirty.value as number) <= 0) {
      fail(path + ".dirty_price.value", "dirty price must be positive");
    }
    if (dirty.unit !== "price_units_per_100_face") {
      fail(path + ".dirty_price.unit", "dirty price unit must be price_units_per_100_face");
    }
  } else if (typeof dirty === "number") {
    assertFiniteNumber(dirty, path + ".dirty_price");
    if (node.dirty_price_unit !== "price_units_per_100_face") {
      fail(path + ".dirty_price_unit", "dirty price unit must be price_units_per_100_face");
    }
  } else {
    fail(path + ".dirty_price", "dirty_price must be a quantity object or a number with dirty_price_unit");
  }
  const reprice = node.reprice_error_bp;
  if (isRecord(reprice)) {
    assertFiniteNumber(reprice.value, path + ".reprice_error_bp.value");
    if (Math.abs(reprice.value as number) > 1.0 + 1e-9) {
      fail(
        path + ".reprice_error_bp.value",
        "reprice error exceeds the 1.0 bp bootstrap tolerance, got " + (reprice.value as number)
      );
    }
    if (reprice.unit !== "bp") {
      fail(path + ".reprice_error_bp.unit", "reprice error unit must be bp");
    }
  } else if (typeof reprice === "number") {
    assertFiniteNumber(reprice, path + ".reprice_error_bp");
    if (node.reprice_error_unit !== undefined && node.reprice_error_unit !== "bp") {
      fail(path + ".reprice_error_unit", "reprice error unit must be bp");
    }
  } else {
    fail(path + ".reprice_error_bp", "reprice_error_bp must be a quantity object or a number in bp");
  }
  assertSourceId(node.source_id, path + ".source_id");
  assertDerivedSource(node.source_id as string, path + ".source_id");
}

function assertBootstrapAnchor(node: unknown, path: string): void {
  if (!isRecord(node)) {
    fail(path, "anchor must be an object");
  }
  const dateValue = node.payment_date ?? node.date;
  if (dateValue === undefined) {
    fail(path, "anchor needs a payment_date (or date) field");
  }
  assertIsoDate(dateValue, path + ".payment_date");
  assertFiniteNumber(node.years_from_settlement, path + ".years_from_settlement");
  if ((node.years_from_settlement as number) <= 0) {
    fail(path + ".years_from_settlement", "years_from_settlement must be positive (unit: duration_years)");
  }
  if ((node.years_from_settlement as number) > MAX_TENOR_YEARS) {
    fail(path + ".years_from_settlement", "years_from_settlement exceeds the tenor cap (unit: duration_years)");
  }
  if (node.years_unit !== "duration_years") {
    fail(path + ".years_unit", "years unit must be duration_years");
  }
  assertFiniteNumber(node.discount, path + ".discount");
  if (!((node.discount as number) > 0) || !((node.discount as number) <= 1)) {
    fail(path + ".discount", "anchor discount must be in (0, 1] (unit: unitless_ratio)");
  }
  if (node.discount_unit !== "unitless_ratio") {
    fail(path + ".discount_unit", "discount unit must be unitless_ratio");
  }
}

function assertBootstrapFields(curve: Record<string, unknown>): void {
  const base = "snapshot.observations.curve";
  const method = curve.method;
  const isBootstrap = method === BOOTSTRAP_METHOD;
  if (method === PAR_METHOD) {
    if (curve.is_par_approx !== true) {
      fail(base, "par approx curve is_par_approx must be true");
    }
    if (curve.is_zero !== false) {
      fail(base, "par approx curve is_zero must be false");
    }
  }
  if (isBootstrap) {
    if (curve.is_par_approx !== false) {
      fail(base, "true bootstrap curve is_par_approx must be false");
    }
    if (curve.is_zero !== true) {
      fail(base, "true bootstrap curve is_zero must be true");
    }
  }
  if (curve.settlement_date !== undefined) {
    assertIsoDate(curve.settlement_date, base + ".settlement_date");
  } else if (isBootstrap) {
    fail(base + ".settlement_date", "true bootstrap curve needs a settlement_date");
  }
  let instruments: unknown[] | null = null;
  if (curve.instruments !== undefined) {
    if (!Array.isArray(curve.instruments)) {
      fail(base + ".instruments", "instruments must be an array");
    }
    if (curve.instruments.length === 0 || curve.instruments.length > MAX_BOOTSTRAP_ROWS) {
      fail(
        base + ".instruments",
        "instruments must hold 1 to " + MAX_BOOTSTRAP_ROWS + " rows, got " + curve.instruments.length
      );
    }
    instruments = curve.instruments as unknown[];
    instruments.forEach((row, i) => assertBootstrapInstrument(row, base + ".instruments[" + i + "]"));
  } else if (isBootstrap) {
    fail(base + ".instruments", "true bootstrap curve needs an instruments array");
  }
  let anchors: unknown[] | null = null;
  if (curve.anchors !== undefined) {
    if (!Array.isArray(curve.anchors)) {
      fail(base + ".anchors", "anchors must be an array");
    }
    if (curve.anchors.length === 0 || curve.anchors.length > MAX_BOOTSTRAP_ROWS) {
      fail(
        base + ".anchors",
        "anchors must hold 1 to " + MAX_BOOTSTRAP_ROWS + " rows, got " + curve.anchors.length
      );
    }
    anchors = curve.anchors as unknown[];
    anchors.forEach((row, i) => assertBootstrapAnchor(row, base + ".anchors[" + i + "]"));
    const years = anchors.map((row) =>
      isRecord(row) ? Number((row as Record<string, unknown>).years_from_settlement) : NaN
    );
    for (let i = 1; i < years.length; i++) {
      if (!(years[i] > years[i - 1])) {
        fail(base + ".anchors", "anchor years_from_settlement must be strictly increasing");
      }
    }
    const discounts = anchors.map((row) =>
      isRecord(row) ? Number((row as Record<string, unknown>).discount) : NaN
    );
    for (let i = 1; i < discounts.length; i++) {
      if (!(discounts[i - 1] > discounts[i])) {
        fail(base + ".anchors", "anchor discounts must be strictly decreasing");
      }
    }
  } else if (isBootstrap) {
    fail(base + ".anchors", "true bootstrap curve needs an anchors array");
  }
  if (isBootstrap && Array.isArray(curve.knots) && instruments && anchors) {
    const knotTenors = (curve.knots as unknown[]).map((row) =>
      isRecord(row) ? String((row as Record<string, unknown>).tenor ?? "") : ""
    );
    const instrumentTenors = instruments.map((row) =>
      isRecord(row) ? String((row as Record<string, unknown>).tenor ?? "") : ""
    );
    if (JSON.stringify(knotTenors) !== JSON.stringify(instrumentTenors)) {
      fail(
        base + ".instruments",
        "instrument tenor set must match knots " + JSON.stringify(knotTenors) +
          ", got " + JSON.stringify(instrumentTenors)
      );
    }
    if (anchors.length !== instruments.length || anchors.length !== knotTenors.length) {
      fail(
        base + ".anchors",
        "anchors, instruments, and knots must agree in length, got " +
          anchors.length + ", " + instruments.length + ", " + knotTenors.length
      );
    }
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
    assertBootstrapFields(curve);
  }

  const spreads = observations.spreads;
  if (spreads !== undefined) {
    if (!isRecord(spreads)) {
      fail("snapshot.observations.spreads", "spreads must be an envelope object");
    }
    if (spreads.status !== "ok" && spreads.status !== "missing") {
      fail(
        "snapshot.observations.spreads.status",
        "status must be ok or missing, got " + JSON.stringify(spreads.status)
      );
    }
    if (!Array.isArray(spreads.records)) {
      fail("snapshot.observations.spreads.records", "records must be an array");
    }
    if (spreads.records.length > MAX_SPREAD_RECORDS) {
      fail(
        "snapshot.observations.spreads.records",
        "spreads exceed the " + MAX_SPREAD_RECORDS + " record cap, got " + spreads.records.length
      );
    }
    if (spreads.status === "ok") {
      if (spreads.reason !== null) {
        fail(
          "snapshot.observations.spreads.reason",
          "ok status must carry a null reason, got " + JSON.stringify(spreads.reason)
        );
      }
      if (spreads.records.length === 0) {
        fail(
          "snapshot.observations.spreads.records",
          "ok status must hold at least one record"
        );
      }
    } else {
      if (typeof spreads.reason !== "string" || spreads.reason.trim().length === 0) {
        fail(
          "snapshot.observations.spreads.reason",
          "missing status must carry a non empty reason"
        );
      }
      if (spreads.records.length !== 0) {
        fail(
          "snapshot.observations.spreads.records",
          "missing status must hold zero records, got " + spreads.records.length
        );
      }
    }
    spreads.records.forEach((record: unknown, i: number) => {
      const path = "snapshot.observations.spreads.records[" + i + "]";
      if (!isRecord(record)) {
        fail(path, "spread record must be an object");
      }
      assertIsoDate(record.date, path + ".date");
      if (typeof record.tenor !== "string" || !(ALLOWED_SPREAD_TENORS as ReadonlyArray<string>).includes(record.tenor)) {
        fail(
          path + ".tenor",
          "tenor must be one of " + JSON.stringify(ALLOWED_SPREAD_TENORS) + ", got " + JSON.stringify(record.tenor)
        );
      }
      assertIsoDate(record.ca_date, path + ".ca_date");
      assertIsoDate(record.us_date, path + ".us_date");
      if (record.ca_date !== record.date || record.us_date !== record.date) {
        fail(path, "ca_date and us_date must equal date");
      }
      assertFiniteNumber(record.ca_yield_percent, path + ".ca_yield_percent");
      assertFiniteNumber(record.us_yield_percent, path + ".us_yield_percent");
      assertFiniteNumber(record.spread_bp, path + ".spread_bp");
    });
    if (spreads.status === "ok") {
      const tenors = (spreads.records as Array<unknown>).map((record) =>
        isRecord(record) ? String(record.tenor ?? "") : ""
      );
      const unique = new Set(tenors);
      const sortedUnique = [...unique].sort();
      const expected = [...ALLOWED_SPREAD_TENORS].sort();
      if (
        tenors.length !== ALLOWED_SPREAD_TENORS.length ||
        unique.size !== tenors.length ||
        JSON.stringify(sortedUnique) !== JSON.stringify(expected)
      ) {
        fail(
          "snapshot.observations.spreads.records",
          "ok envelope tenor set must be exactly " +
            JSON.stringify(ALLOWED_SPREAD_TENORS) +
            " with no duplicates, got " +
            JSON.stringify(tenors)
        );
      }
    }
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

  assertBreaks(observations.breaks);

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
  if (isRecord(observations.breaks)) {
    const breaksNode = observations.breaks as Record<string, unknown>;
    const switchProv = (provenance as Record<string, unknown>)["benchmark_switches"];
    if (!isRecord(switchProv)) {
      fail("snapshot.provenance.benchmark_switches", "provenance benchmark_switches is missing beside breaks");
    }
    if (switchProv["vintage"] !== breaksNode["feed_vintage"]) {
      fail(
        "snapshot.provenance.benchmark_switches.vintage",
        "vintage must match breaks feed_vintage " +
          JSON.stringify(breaksNode["feed_vintage"]) +
          ", got " +
          JSON.stringify(switchProv["vintage"])
      );
    }
    if (
      typeof switchProv["sha256"] !== "string" ||
      (switchProv["sha256"] as string).trim() !== (breaksNode["feed_sha256"] as string).trim()
    ) {
      fail(
        "snapshot.provenance.benchmark_switches.sha256",
        "sha256 must match breaks feed_sha256 " +
          JSON.stringify(breaksNode["feed_sha256"]) +
          ", got " +
          JSON.stringify(switchProv["sha256"])
      );
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

/** Pinned breaks facts mirrored from src/goc_rates/breaks.py and the switch feed. */
const BREAKS_METHOD = "benchmark_switch_dod_gate_v1";
const BREAKS_FEED_SOURCE = "bench_CDN.pdf";
const BREAKS_FEED_VINTAGE = "2026-11-01";
const BREAKS_THRESHOLD_BP = 15.0;
const BREAKS_TENORS: ReadonlyArray<string> = ["2Y", "5Y", "10Y", "30Y"];
const FEED_ALLOWED_TENORS: ReadonlyArray<string> = [
  "2Y",
  "3Y",
  "5Y",
  "7Y",
  "10Y",
  "30Y",
  "LONG",
];
const BREAKS_GATES: ReadonlyArray<string> = [
  "comparable",
  "switch_break",
  "calendar_gap",
  "missing_prev",
  "insufficient_history",
];
const BREAKS_SOURCE_ID = "derived:dod_gate";
const NULL_GATES: ReadonlyArray<string> = [
  "switch_break",
  "missing_prev",
  "insufficient_history",
];
const HEX64 = /^[0-9a-f]{64}$/;

function assertNullableFinite(
  value: unknown,
  path: string
): asserts value is number | null {
  if (value === null) return;
  assertFiniteNumber(value, path);
}

/**
 * Validate the breaks section, mirroring V23 in verify.py.
 * Structural only: pins method, dates, feed digest grammar, tenor closure,
 * gate closure, and nullness rules. Joint calendar dates are never
 * recomputed here, the pipeline owns the Toronto joint calendar.
 */
function assertBreaks(node: unknown): void {
  if (node === undefined) return;
  const path = "snapshot.observations.breaks";
  if (!isRecord(node)) {
    fail(path, "breaks must be an object");
  }
  if (node.method !== BREAKS_METHOD) {
    fail(
      path + ".method",
      "method must pin " + BREAKS_METHOD + ", got " + JSON.stringify(node.method)
    );
  }
  assertIsoDate(node.snapshot_date, path + ".snapshot_date");
  assertIsoDate(node.print_date, path + ".print_date");
  assertIsoDate(node.feed_vintage, path + ".feed_vintage");
  if (node.feed_vintage !== BREAKS_FEED_VINTAGE) {
    fail(
      path + ".feed_vintage",
      "feed_vintage must pin " + BREAKS_FEED_VINTAGE + ", got " + JSON.stringify(node.feed_vintage)
    );
  }
  if (typeof node.feed_source !== "string" || node.feed_source.trim() !== BREAKS_FEED_SOURCE) {
    fail(
      path + ".feed_source",
      "feed_source must pin " + BREAKS_FEED_SOURCE + ", got " + JSON.stringify(node.feed_source)
    );
  }
  if (typeof node.feed_sha256 !== "string" || !HEX64.test(node.feed_sha256.trim())) {
    fail(path + ".feed_sha256", "must be a 64 character lowercase hex digest");
  }
  assertFiniteNumber(node.threshold_bp, path + ".threshold_bp");
  if (Math.abs((node.threshold_bp as number) - BREAKS_THRESHOLD_BP) > 1e-12) {
    fail(path + ".threshold_bp", "must pin " + BREAKS_THRESHOLD_BP + " bp");
  }
  if (node.threshold_unit !== "basis_points") {
    fail(path + ".threshold_unit", "unit must be basis_points");
  }
  if (!Array.isArray(node.events)) {
    fail(path + ".events", "events must be an array");
  }
  if (node.events.length === 0 || node.events.length > MAX_SWITCH_EVENTS) {
    fail(
      path + ".events",
      "events must hold 1 to " + MAX_SWITCH_EVENTS + " rows, got " + node.events.length
    );
  }
  const seenEvents = new Set<string>();
  node.events.forEach((row: unknown, i: number) => {
    const rowPath = path + ".events[" + i + "]";
    if (!isRecord(row)) {
      fail(rowPath, "event row must be an object");
    }
    if (typeof row.tenor !== "string" || !FEED_ALLOWED_TENORS.includes(row.tenor)) {
      fail(
        rowPath + ".tenor",
        "tenor must be one of " + JSON.stringify(FEED_ALLOWED_TENORS) + ", got " + JSON.stringify(row.tenor)
      );
    }
    assertIsoDate(row.effective_date, rowPath + ".effective_date");
    assertIsoDate(row.effective_joint_date, rowPath + ".effective_joint_date");
    const key = (row.tenor as string) + "|" + (row.effective_date as string);
    if (seenEvents.has(key)) {
      fail(rowPath, "duplicate switch event " + JSON.stringify(key));
    }
    seenEvents.add(key);
    assertNullableFinite(row.incoming_coupon_percent, rowPath + ".incoming_coupon_percent");
    assertNullableFinite(row.outgoing_coupon_percent, rowPath + ".outgoing_coupon_percent");
    for (const name of ["incoming_coupon_unit", "outgoing_coupon_unit"]) {
      const unit = (row as Record<string, unknown>)[name];
      if (unit !== "percent") {
        fail(rowPath + "." + name, "unit must be percent, got " + JSON.stringify(unit));
      }
      if (typeof unit !== "string" || !ALLOWED_UNITS.has(unit)) {
        fail(rowPath + "." + name, "unit is not in the closed unit set");
      }
    }
    for (const name of ["incoming_maturity", "outgoing_maturity"]) {
      const maturity = (row as Record<string, unknown>)[name];
      if (maturity !== null && maturity !== undefined) {
        assertIsoDate(maturity, rowPath + "." + name);
      }
    }
  });
  if (!Array.isArray(node.records) || node.records.length !== MAX_DOD_RECORDS) {
    fail(
      path + ".records",
      "must hold exactly " + MAX_DOD_RECORDS + " tenor records in 2Y 5Y 10Y 30Y order"
    );
  }
  const labels = (node.records as unknown[]).map((item) =>
    isRecord(item) ? String((item as Record<string, unknown>).tenor ?? "") : ""
  );
  if (JSON.stringify(labels) !== JSON.stringify(BREAKS_TENORS)) {
    fail(
      path + ".records",
      "tenor set must be " + JSON.stringify(BREAKS_TENORS) + ", got " + JSON.stringify(labels)
    );
  }
  node.records.forEach((record: unknown, i: number) => {
    const recordPath = path + ".records[" + i + "]";
    if (!isRecord(record)) {
      fail(recordPath, "record must be an object");
    }
    assertIsoDate(record.prev_date, recordPath + ".prev_date");
    assertIsoDate(record.current_date, recordPath + ".current_date");
    if ((record.current_date as string) <= (record.prev_date as string)) {
      fail(recordPath, "current_date must exceed prev_date");
    }
    assertNullableFinite(record.prev_yield_percent, recordPath + ".prev_yield_percent");
    assertNullableFinite(record.current_yield_percent, recordPath + ".current_yield_percent");
    for (const name of ["prev_yield_unit", "current_yield_unit"]) {
      const unit = (record as Record<string, unknown>)[name];
      if (unit !== "percent") {
        fail(recordPath + "." + name, "unit must be percent, got " + JSON.stringify(unit));
      }
      if (typeof unit !== "string" || !ALLOWED_UNITS.has(unit)) {
        fail(recordPath + "." + name, "unit is not in the closed unit set");
      }
    }
    if (record.history_count_unit !== "count") {
      fail(
        recordPath + ".history_count_unit",
        "unit must be count, got " + JSON.stringify(record.history_count_unit)
      );
    }
    if (typeof record.history_count_unit !== "string" || !ALLOWED_UNITS.has(record.history_count_unit)) {
      fail(recordPath + ".history_count_unit", "unit is not in the closed unit set");
    }
    assertNullableFinite(record.dod_bp, recordPath + ".dod_bp");
    if (record.dod_unit !== "basis_points") {
      fail(recordPath + ".dod_unit", "unit must be basis_points");
    }
    if (typeof record.gate !== "string" || !BREAKS_GATES.includes(record.gate)) {
      fail(
        recordPath + ".gate",
        "gate must be one of " + JSON.stringify(BREAKS_GATES) + ", got " + JSON.stringify(record.gate)
      );
    }
    if (typeof record.switch_in_window !== "boolean" || typeof record.calendar_gap !== "boolean") {
      fail(recordPath, "switch_in_window and calendar_gap must be booleans without coercion");
    }
    if (
      typeof record.history_count !== "number" ||
      !Number.isInteger(record.history_count) ||
      (record.history_count as number) < 0 ||
      (record.history_count as number) > MAX_HISTORY_OBS
    ) {
      fail(
        recordPath + ".history_count",
        "must be an integer in [0, " +
          MAX_HISTORY_OBS +
          "] without coercion, got " +
          JSON.stringify(record.history_count)
      );
    }
    const gate = record.gate as string;
    const dod = record.dod_bp as number | null;
    const needsNull = NULL_GATES.includes(gate);
    if (needsNull && dod !== null) {
      fail(
        recordPath + ".dod_bp",
        "gate " + gate + " must suppress dod_bp to null, got " + String(dod)
      );
    }
    if (!needsNull && dod === null) {
      fail(recordPath + ".dod_bp", "gate " + gate + " must keep a numeric dod_bp");
    }
    if (!isRecord(record.dod_quantity)) {
      fail(recordPath + ".dod_quantity", "dod_quantity is missing");
    }
    assertQuantity(record.dod_quantity, recordPath + ".dod_quantity");
    const quantity = record.dod_quantity as unknown as {
      value: number | null;
      unit: unknown;
      quality: unknown;
      source_id: unknown;
    };
    if (quantity.unit !== "basis_points") {
      fail(recordPath + ".dod_quantity", "unit must be basis_points");
    }
    if (quantity.source_id !== BREAKS_SOURCE_ID) {
      fail(recordPath + ".dod_quantity", "source_id must be " + BREAKS_SOURCE_ID);
    }
    if (dod === null) {
      if (quantity.value !== null || quantity.quality !== "missing") {
        fail(recordPath + ".dod_quantity", "null dod_bp needs a missing null quantity");
      }
    } else {
      if (quantity.quality !== "observed") {
        fail(recordPath + ".dod_quantity", "numeric dod_bp needs an observed quantity");
      }
      if (typeof quantity.value !== "number" || Math.abs(quantity.value - dod) > 1e-9) {
        fail(recordPath + ".dod_quantity", "quantity value must match dod_bp");
      }
    }
    if (record.source_id !== BREAKS_SOURCE_ID) {
      fail(recordPath + ".source_id", "source_id must be " + BREAKS_SOURCE_ID);
    }
  });
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
      "report must contain exactly " + MAX_VERIFY_CHECKS + " checks (V01 to V25), got " +
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
      "report must contain exactly V01 to V25, missing " +
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
  const history = (doc as Record<string, unknown>).history;
  if (history !== undefined) {
    if (!isRecord(history)) {
      fail("index.history", "history entry must be an object");
    }
    if (typeof history.sha256 !== "string" || !SHA256_HEX.test(history.sha256)) {
      fail("index.history.sha256", "must be a 64 character lowercase hex digest");
    }
    for (const key of ["bytes_utf8", "daily_count", "cpi_count", "trimmed_backfilled_count"]) {
      const value = (history as Record<string, unknown>)[key];
      if (typeof value !== "number" || !Number.isInteger(value) || (value as number) < 0) {
        fail("index.history." + key, "must be a non negative integer");
      }
    }
    if ((history.daily_count as number) > MAX_HISTORY_DAILY) {
      fail("index.history.daily_count", "exceeds the daily history cap");
    }
    if ((history.cpi_count as number) > MAX_HISTORY_CPI) {
      fail("index.history.cpi_count", "exceeds the CPI history cap");
    }
  }
  return doc as unknown as DataIndex;
}

/** History caps mirror the backfill bounds in src/goc_rates/limits.py. */
export const MAX_HISTORY_DAILY = 1250;
export const MAX_HISTORY_CPI = 60;
export const MAX_HISTORY_BYTES = 5 * 1024 * 1024;
export const HISTORY_METHOD = "history_merge_v1";
export const HISTORY_SOURCES: ReadonlyArray<string> = [
  "derived:backfill_v1",
  "derived:history_verified_v1",
];
const HISTORY_TENORS: ReadonlyArray<string> = ["2Y", "5Y", "10Y", "30Y"];
const HISTORY_SLOPES: ReadonlyArray<string> = ["2Y_5Y", "2Y_10Y", "5Y_30Y", "10Y_30Y"];
const HISTORY_SPREAD_STATUS: ReadonlyArray<string> = ["ok", "partial", "missing"];
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

function assertHistoryMonth(value: unknown, path: string): asserts value is string {
  if (typeof value !== "string" || !MONTH_RE.test(value)) {
    fail(path, "must be a YYYY-MM month: " + JSON.stringify(value));
  }
  if (value.slice(5) === "00" || value.slice(5) === "13") {
    fail(path, "must be a YYYY-MM month: " + JSON.stringify(value));
  }
}

function nextCalendarMonth(month: string): string {
  const year = Number(month.slice(0, 4));
  const mon = Number(month.slice(5, 7));
  const nextYear = mon === 12 ? year + 1 : year;
  const nextMon = mon === 12 ? 1 : mon + 1;
  return nextYear + "-" + String(nextMon).padStart(2, "0");
}

/**
 * Python compatible canonical JSON for row digests.
 * Mirrors json.dumps with sort_keys True and indent 2, with float
 * integers rendered as X.0 so JS output matches the Python sealer.
 */
function canonicalHistoryText(payload: unknown): string {
  return canonicalHistoryValue(payload, 0) + "\n";
}

function canonicalHistoryNumber(value: number): string {
  if (!Number.isFinite(value)) {
    fail("history", "non finite number in canonical payload");
  }
  if (Number.isInteger(value)) {
    return value.toFixed(1);
  }
  return JSON.stringify(value);
}

function canonicalHistoryValue(value: unknown, indent: number): string {
  if (value === null) return "null";
  if (typeof value === "number") return canonicalHistoryNumber(value as number);
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    const parts = (value as unknown[]).map(
      (item) => " ".repeat(indent + 2) + canonicalHistoryValue(item, indent + 2)
    );
    return "[\n" + parts.join(",\n") + "\n" + " ".repeat(indent) + "]";
  }
  if (isRecord(value)) {
    const keys = Object.keys(value).sort();
    if (keys.length === 0) return "{}";
    const parts = keys.map(
      (key) =>
        " ".repeat(indent + 2) +
        JSON.stringify(key) +
        ": " +
        canonicalHistoryValue((value as Record<string, unknown>)[key], indent + 2)
    );
    return "{\n" + parts.join(",\n") + "\n" + " ".repeat(indent) + "}";
  }
  fail("history", "unsupported canonical value: " + typeof value);
}

type HashFn = (text: string) => string;

/** Synchronous SHA-256 over UTF-8 text (compact implementation, no dependency). */
function sha256HexText(text: string): string {
  const bytes = new TextEncoder().encode(text);
  const K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];
  let h0 = 0x6a09e667;
  let h1 = 0xbb67ae85;
  let h2 = 0x3c6ef372;
  let h3 = 0xa54ff53a;
  let h4 = 0x510e527f;
  let h5 = 0x9b05688c;
  let h6 = 0x1f83d9ab;
  let h7 = 0x5be0cd19;
  const bitLen = bytes.length * 8;
  const withPad = bytes.length + 1 + 8;
  const blocks = Math.ceil(withPad / 64);
  const padded = new Uint8Array(blocks * 64);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  const hi = Math.floor(bitLen / 0x100000000);
  const lo = bitLen >>> 0;
  view.setUint32(padded.length - 8, hi);
  view.setUint32(padded.length - 4, lo);
  const w = new Uint32Array(64);
  const rotr = (x: number, n: number): number => (x >>> n) | (x << (32 - n));
  for (let off = 0; off < padded.length; off += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(off + i * 4);
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
    }
    let a = h0;
    let b = h1;
    let c = h2;
    let d = h3;
    let e = h4;
    let f = h5;
    let g = h6;
    let h = h7;
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + S1 + ch + K[i] + w[i]) | 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) | 0;
      h = g;
      g = f;
      f = e;
      e = (d + t1) | 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) | 0;
    }
    h0 = (h0 + a) | 0;
    h1 = (h1 + b) | 0;
    h2 = (h2 + c) | 0;
    h3 = (h3 + d) | 0;
    h4 = (h4 + e) | 0;
    h5 = (h5 + f) | 0;
    h6 = (h6 + g) | 0;
    h7 = (h7 + h) | 0;
  }
  const hex = (x: number): string => (x >>> 0).toString(16).padStart(8, "0");
  return hex(h0) + hex(h1) + hex(h2) + hex(h3) + hex(h4) + hex(h5) + hex(h6) + hex(h7);
}

let hashImpl: HashFn = sha256HexText;

/** Install the sha256 helper for row digest recompute (Node or browser). */
export function setHistoryHashImpl(fn: HashFn): void {
  hashImpl = fn;
}

export { canonicalHistoryText, sha256HexText };

function requireHistoryHash(): HashFn {
  if (!hashImpl) {
    fail("history", "history digest helper is not installed, call setHistoryHashImpl first");
  }
  return hashImpl as HashFn;
}

function checkRowDigestSync(row: Record<string, unknown>, path: string): void {
  const stored = row.row_digest;
  if (typeof stored !== "string" || !SHA256_HEX.test(stored)) {
    fail(path + ".row_digest", "must be a 64 character lowercase hex digest");
  }
  const body: Record<string, unknown> = {};
  for (const [key, val] of Object.entries(row)) {
    if (key === "row_digest") continue;
    body[key] = val;
  }
  const expected = requireHistoryHash()(canonicalHistoryText(body));
  if (expected !== stored) {
    fail(path + ".row_digest", "row digest does not recompute from the canonical subdocument");
  }
}

/** Validate the merged history document published as history.json. */
export function validateHistory(doc: unknown): import("./types").HistoryDoc {
  if (!isRecord(doc)) {
    fail("history", "document must be an object");
  }
  const metadata = doc.metadata;
  if (!isRecord(metadata)) {
    fail("history.metadata", "metadata must be an object");
  }
  if (metadata.schema_version !== 1) {
    fail("history.metadata.schema_version", "must pin schema version 1");
  }
  if (metadata.method !== HISTORY_METHOD) {
    fail("history.metadata.method", "method must pin " + HISTORY_METHOD);
  }
  assertIsoDate(metadata.asof, "history.metadata.asof");
  for (const key of ["daily_count", "cpi_count"] as const) {
    const value = (metadata as Record<string, unknown>)[key];
    if (typeof value !== "number" || !Number.isInteger(value) || (value as number) < 0) {
      fail("history.metadata." + key, "must be a non negative integer");
    }
  }
  if ((metadata.daily_count as number) > MAX_HISTORY_DAILY) {
    fail("history.metadata.daily_count", "exceeds the " + MAX_HISTORY_DAILY + " daily cap");
  }
  if ((metadata.cpi_count as number) > MAX_HISTORY_CPI) {
    fail("history.metadata.cpi_count", "exceeds the " + MAX_HISTORY_CPI + " CPI cap");
  }
  if (!Array.isArray(doc.daily)) {
    fail("history.daily", "daily must be an array");
  }
  if (!Array.isArray(doc.cpi)) {
    fail("history.cpi", "cpi must be an array");
  }
  if ((doc.daily as unknown[]).length !== (metadata.daily_count as number)) {
    fail("history.daily", "daily length must match metadata daily_count");
  }
  if ((doc.cpi as unknown[]).length !== (metadata.cpi_count as number)) {
    fail("history.cpi", "cpi length must match metadata cpi_count");
  }
  const dates: string[] = [];
  (doc.daily as unknown[]).forEach((row: unknown, i: number) => {
    const path = "history.daily[" + i + "]";
    if (!isRecord(row)) {
      fail(path, "daily row must be an object");
    }
    assertIsoDate(row.date, path + ".date");
    dates.push(row.date as string);
    const yields = row.yields_percent;
    if (!isRecord(yields)) {
      fail(path + ".yields_percent", "must be an object");
    }
    if (JSON.stringify(Object.keys(yields).sort()) !== JSON.stringify([...HISTORY_TENORS].sort())) {
      fail(path + ".yields_percent", "must hold exactly " + JSON.stringify(HISTORY_TENORS));
    }
    for (const tenor of HISTORY_TENORS) {
      assertFiniteNumber((yields as Record<string, unknown>)[tenor], path + ".yields_percent." + tenor);
      const v = (yields as Record<string, number>)[tenor];
      if (v < -20 || v > 30) {
        fail(path + ".yields_percent." + tenor, "yield must be within [-20, 30] percent");
      }
    }
    if (row.yields_unit !== "percent") {
      fail(path + ".yields_unit", "yields unit must be percent");
    }
    const slopes = row.slopes_bp;
    if (!isRecord(slopes)) {
      fail(path + ".slopes_bp", "must be an object");
    }
    if (JSON.stringify(Object.keys(slopes).sort()) !== JSON.stringify([...HISTORY_SLOPES].sort())) {
      fail(path + ".slopes_bp", "must hold exactly " + JSON.stringify(HISTORY_SLOPES));
    }
    const y = yields as Record<string, number>;
    const slopePairs: Array<[string, string, string]> = [
      ["2Y_5Y", "2Y", "5Y"],
      ["2Y_10Y", "2Y", "10Y"],
      ["5Y_30Y", "5Y", "30Y"],
      ["10Y_30Y", "10Y", "30Y"],
    ];
    for (const [key, shortT, longT] of slopePairs) {
      assertFiniteNumber((slopes as Record<string, unknown>)[key], path + ".slopes_bp." + key);
      const stored = (slopes as Record<string, number>)[key];
      const expected = (y[longT] - y[shortT]) * 100;
      if (Math.abs(stored - expected) > 1.0 + 1e-9) {
        fail(
          path + ".slopes_bp." + key,
          "slope must recompute as (long minus short) times 100 within 1.0 bp, expected " +
            expected +
            " got " +
            stored
        );
      }
    }
    if (row.slopes_unit !== "basis_points") {
      fail(path + ".slopes_unit", "slopes unit must be basis_points");
    }
    const spreads = row.spreads_bp;
    if (!isRecord(spreads)) {
      fail(path + ".spreads_bp", "must be an object");
    }
    if (JSON.stringify(Object.keys(spreads).sort()) !== JSON.stringify([...HISTORY_TENORS].sort())) {
      fail(path + ".spreads_bp", "must hold exactly " + JSON.stringify(HISTORY_TENORS));
    }
    let present = 0;
    for (const tenor of HISTORY_TENORS) {
      const value = (spreads as Record<string, unknown>)[tenor];
      if (value === null) continue;
      assertFiniteNumber(value, path + ".spreads_bp." + tenor);
      if (Math.abs(value as number) > 5000 + 1e-9) {
        fail(path + ".spreads_bp." + tenor, "spread must be within 5000 bp");
      }
      present += 1;
    }
    if (row.spreads_unit !== "basis_points") {
      fail(path + ".spreads_unit", "spreads unit must be basis_points");
    }
    if (typeof row.spreads_status !== "string" || !HISTORY_SPREAD_STATUS.includes(row.spreads_status)) {
      fail(path + ".spreads_status", "must be one of " + JSON.stringify(HISTORY_SPREAD_STATUS));
    }
    const status = row.spreads_status as string;
    if (status === "ok" && present !== 4) {
      fail(path + ".spreads_status", "ok status needs four present spreads, got " + present);
    }
    if (status === "missing" && present !== 0) {
      fail(path + ".spreads_status", "missing status needs zero present spreads, got " + present);
    }
    if (status === "partial" && (present === 0 || present === 4)) {
      fail(path + ".spreads_status", "partial status needs one to three present spreads");
    }
    if (typeof row.switch_in_window !== "boolean" || typeof row.calendar_gap !== "boolean") {
      fail(path, "switch_in_window and calendar_gap must be booleans");
    }
    const byTenor = row.switch_by_tenor;
    if (!isRecord(byTenor)) {
      fail(path + ".switch_by_tenor", "must be an object");
    }
    if (JSON.stringify(Object.keys(byTenor).sort()) !== JSON.stringify([...HISTORY_TENORS].sort())) {
      fail(path + ".switch_by_tenor", "must hold exactly " + JSON.stringify(HISTORY_TENORS));
    }
    for (const tenor of HISTORY_TENORS) {
      if (typeof (byTenor as Record<string, unknown>)[tenor] !== "boolean") {
        fail(path + ".switch_by_tenor." + tenor, "must be a boolean");
      }
    }
    const anySwitch = HISTORY_TENORS.some((t) => (byTenor as Record<string, boolean>)[t]);
    if ((row.switch_in_window as boolean) !== anySwitch) {
      fail(path + ".switch_in_window", "must equal the OR of switch_by_tenor");
    }
    if (typeof row.verified !== "boolean") {
      fail(path + ".verified", "verified must be a boolean");
    }
    if (typeof row.source !== "string" || !HISTORY_SOURCES.includes(row.source)) {
      fail(path + ".source", "source must be one of " + JSON.stringify(HISTORY_SOURCES));
    }
    if ((row.verified as boolean) && row.source !== "derived:history_verified_v1") {
      fail(path + ".source", "verified rows must use derived:history_verified_v1");
    }
    if (!(row.verified as boolean) && row.source !== "derived:backfill_v1") {
      fail(path + ".source", "unverified rows must use derived:backfill_v1");
    }
    const snap = row.snapshot_sha256;
    if (row.verified) {
      if (typeof snap !== "string" || !SHA256_HEX.test(snap)) {
        fail(path + ".snapshot_sha256", "verified rows need a 64 character hex snapshot digest");
      }
    } else if (snap !== null) {
      fail(path + ".snapshot_sha256", "unverified rows must carry a null snapshot_sha256");
    }
    if (row.input_digest_sha256 !== null && row.input_digest_sha256 !== undefined) {
      fail(path + ".input_digest_sha256", "history rows must carry a null input digest");
    }
    checkRowDigestSync(row as Record<string, unknown>, path);
  });
  for (let i = 1; i < dates.length; i++) {
    if (!(dates[i] > dates[i - 1])) {
      fail("history.daily", "daily dates must be strictly increasing");
    }
  }
  if (new Set(dates).size !== dates.length) {
    fail("history.daily", "daily dates must be unique");
  }
  const months: string[] = [];
  const trimMoms: number[] = [];
  (doc.cpi as unknown[]).forEach((row: unknown, i: number) => {
    const path = "history.cpi[" + i + "]";
    if (!isRecord(row)) {
      fail(path, "cpi row must be an object");
    }
    assertHistoryMonth(row.month, path + ".month");
    months.push(row.month as string);
    assertFiniteNumber(row.trim_mom_percent, path + ".trim_mom_percent");
    assertFiniteNumber(row.median_mom_percent, path + ".median_mom_percent");
    trimMoms.push(row.trim_mom_percent as number);
    if (typeof row.median_component !== "string" || (row.median_component as string).length === 0) {
      fail(path + ".median_component", "must be a non empty string");
    }
    const trimYoy = row.trim_yoy_percent;
    const medianYoy = row.median_yoy_percent;
    if (trimYoy !== null) assertFiniteNumber(trimYoy, path + ".trim_yoy_percent");
    if (medianYoy !== null) assertFiniteNumber(medianYoy, path + ".median_yoy_percent");
    if (row.mom_unit !== "percent_per_month") {
      fail(path + ".mom_unit", "mom unit must be percent_per_month");
    }
    if (row.yoy_unit !== "percent") {
      fail(path + ".yoy_unit", "yoy unit must be percent");
    }
    if (typeof row.verified !== "boolean") {
      fail(path + ".verified", "verified must be a boolean");
    }
    if (typeof row.source !== "string" || !HISTORY_SOURCES.includes(row.source)) {
      fail(path + ".source", "source must be one of " + JSON.stringify(HISTORY_SOURCES));
    }
    if ((row.verified as boolean) && row.source !== "derived:history_verified_v1") {
      fail(path + ".source", "verified rows must use derived:history_verified_v1");
    }
    if (!(row.verified as boolean) && row.source !== "derived:backfill_v1") {
      fail(path + ".source", "unverified rows must use derived:backfill_v1");
    }
    const cpiSnap = row.snapshot_sha256;
    if (row.verified) {
      if (typeof cpiSnap !== "string" || !SHA256_HEX.test(cpiSnap)) {
        fail(path + ".snapshot_sha256", "verified rows need a 64 character hex snapshot digest");
      }
    } else if (cpiSnap !== null && cpiSnap !== undefined) {
      fail(path + ".snapshot_sha256", "unverified rows must carry a null snapshot_sha256");
    }
    if (row.input_digest_sha256 !== null && row.input_digest_sha256 !== undefined) {
      fail(path + ".input_digest_sha256", "history rows must carry a null input digest");
    }
    checkRowDigestSync(row as Record<string, unknown>, path);
  });
  for (let i = 1; i < months.length; i++) {
    if (!(months[i] > months[i - 1])) {
      fail("history.cpi", "cpi months must be strictly increasing");
    }
  }
  if (new Set(months).size !== months.length) {
    fail("history.cpi", "cpi months must be unique");
  }
  for (let i = 1; i < months.length; i++) {
    if (months[i] !== nextCalendarMonth(months[i - 1])) {
      fail(
        "history.cpi",
        "cpi months must be consecutive calendar months, gap between " +
          months[i - 1] +
          " and " +
          months[i]
      );
    }
  }
  const compound = (series: number[]): number => {
    let factor = 1;
    for (const m of series) factor *= 1 + m / 100;
    return (factor - 1) * 100;
  };
  const cpiRows = doc.cpi as Array<{
    trim_mom_percent: number;
    median_mom_percent: number;
    trim_yoy_percent: number | null;
    median_yoy_percent: number | null;
  }>;
  const medMoms = cpiRows.map((r) => r.median_mom_percent);
  const trMoms = cpiRows.map((r) => r.trim_mom_percent);
  cpiRows.forEach((row, i) => {
    const path = "history.cpi[" + i + "]";
    if (i < 11) {
      if (row.trim_yoy_percent !== null || row.median_yoy_percent !== null) {
        fail(path, "first 11 CPI months must carry null year over year");
      }
      return;
    }
    if (row.trim_yoy_percent === null || row.median_yoy_percent === null) {
      fail(path, "CPI months at index 11 and later need numeric year over year");
    }
    for (let k = i - 11 + 1; k <= i; k++) {
      if (months[k] !== nextCalendarMonth(months[k - 1])) {
        fail(
          path,
          "CPI year over year needs 12 consecutive calendar months, gap between " +
            months[k - 1] +
            " and " +
            months[k]
        );
      }
    }
    const expectedTrim = compound(trMoms.slice(i - 11, i + 1));
    const expectedMedian = compound(medMoms.slice(i - 11, i + 1));
    if (Math.abs((row.trim_yoy_percent as number) - expectedTrim) > 0.01 + 1e-9) {
      fail(
        path + ".trim_yoy_percent",
        "must compound the trailing 12 moms within 0.01, expected " + expectedTrim
      );
    }
    if (Math.abs((row.median_yoy_percent as number) - expectedMedian) > 0.01 + 1e-9) {
      fail(
        path + ".median_yoy_percent",
        "must compound the trailing 12 moms within 0.01, expected " + expectedMedian
      );
    }
  });
  return doc as unknown as import("./types").HistoryDoc;
}
