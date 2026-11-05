import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { applyOverflowPolicy } from "./history-overflow.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..", "..");
const webDir = join(here, "..");
const snapshotsDir = join(repoRoot, "snapshots");
const outDir = join(webDir, "public", "data");
const backfillPath = join(repoRoot, "history", "backfill.json");
const backfillManifestPath = join(repoRoot, "history", "backfill-manifest.json");

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const SHA256_HEX_RE = /^[0-9a-f]{64}$/;
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

const MAX_HISTORY_DAILY = 2750;
const MAX_HISTORY_CPI = 60;
const MAX_HISTORY_BYTES = 5 * 1024 * 1024;
const MAX_BOUNDED_DEPTH = 3;
const MAX_BOUNDED_ENTRIES = 64;
const MAX_BOUNDED_STRING = 2048;
const PRINT_WINDOW_DAYS = 7; // unit: days, earliest sealed backfill print minus this bounds a settlement
const HISTORY_METHOD = "history_merge_v1";
const VERIFIED_SOURCE = "derived:history_verified_v1";
const BACKFILL_SOURCE = "derived:backfill_v1";
const TENORS = ["2Y", "5Y", "10Y", "30Y"];
const SLOPE_KEYS = ["2Y_5Y", "2Y_10Y", "5Y_30Y", "10Y_30Y"];
const SLOPE_PAIRS = { "2Y_5Y": ["2Y", "5Y"], "2Y_10Y": ["2Y", "10Y"], "5Y_30Y": ["5Y", "30Y"], "10Y_30Y": ["10Y", "30Y"] };

function sha256HexBytes(raw) {
  return createHash("sha256").update(raw).digest("hex");
}

function sha256HexText(text) {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

async function exists(path) {
  try {
    await fs.access(path);
    return true;
  } catch {
    return false;
  }
}

/** Real calendar date check with round trip, not just a regex. */
function isRealIsoDate(text) {
  if (!DATE_RE.test(text)) return false;
  const parsed = new Date(text + "T00:00:00Z");
  if (Number.isNaN(parsed.getTime())) return false;
  return parsed.toISOString().slice(0, 10) === text;
}

/** Calendar date a fixed number of days before a validated strict ISO date. */
function isoDaysBefore(dateText, days) {
  const ms = Date.parse(dateText + "T00:00:00Z") - days * 24 * 60 * 60 * 1000;
  return new Date(ms).toISOString().slice(0, 10);
}

function fail(message) {
  console.error("build-data: " + message);
  process.exit(1);
}

/** Python compatible canonical JSON: sorted keys, indent 2, float ints as X.0. */
function canonicalNumber(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    fail("history canonical number is non finite: " + String(value));
  }
  if (Number.isInteger(value)) return value.toFixed(1);
  return JSON.stringify(value);
}

function canonicalValue(value, indent) {
  if (value === null) return "null";
  if (typeof value === "number") return canonicalNumber(value);
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    const parts = value.map((item) => " ".repeat(indent + 2) + canonicalValue(item, indent + 2));
    return "[\n" + parts.join(",\n") + "\n" + " ".repeat(indent) + "]";
  }
  if (typeof value === "object") {
    const keys = Object.keys(value).sort();
    if (keys.length === 0) return "{}";
    const parts = keys.map(
      (key) => " ".repeat(indent + 2) + JSON.stringify(key) + ": " + canonicalValue(value[key], indent + 2)
    );
    return "{\n" + parts.join(",\n") + "\n" + " ".repeat(indent) + "}";
  }
  fail("history canonical value has unsupported type: " + typeof value);
}

function canonicalText(payload) {
  return canonicalValue(payload, 0) + "\n";
}

function rowDigestFor(body) {
  return sha256HexText(canonicalText(body));
}

/** Extract the snapshot digest from either manifest shape, mirroring verify.py. */
function manifestDigest(manifestText, date) {
  let manifest;
  try {
    manifest = JSON.parse(manifestText);
  } catch (err) {
    fail("manifest.json for " + date + " is not valid JSON: " + err.message);
  }
  const files = manifest?.files;
  const direct = manifest?.["snapshot.json"];
  const entry = files?.["snapshot.json"] ?? direct;
  const sha = entry?.sha256;
  if (typeof sha !== "string" || !SHA256_HEX_RE.test(sha.trim())) {
    fail("manifest.json for " + date + " has no valid snapshot.json sha256 digest");
  }
  return sha.trim();
}

function assertFinite(value, path) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    fail(path + " must be a finite number, got " + String(value));
  }
}

function validateBackfillDoc(doc) {
  if (typeof doc !== "object" || doc === null || Array.isArray(doc)) {
    fail("backfill.json document must be an object");
  }
  const metadata = doc.metadata;
  if (typeof metadata !== "object" || metadata === null) {
    fail("backfill.json metadata must be an object");
  }
  if (metadata.schema_version !== 1) {
    fail("backfill.json schema_version must be 1");
  }
  if (metadata.method !== "backfill_v1") {
    fail("backfill.json method must be backfill_v1");
  }
  if (!isRealIsoDate(metadata.asof)) {
    fail("backfill.json metadata.asof must be a strict ISO date");
  }
  if (!Array.isArray(doc.daily) || !Array.isArray(doc.cpi)) {
    fail("backfill.json daily and cpi must be arrays");
  }
  if (doc.daily.length > MAX_HISTORY_DAILY) {
    fail("backfill.json daily count " + doc.daily.length + " exceeds the " + MAX_HISTORY_DAILY + " cap");
  }
  if (doc.daily.length !== metadata.daily_count) {
    fail("backfill.json daily length must match metadata daily_count");
  }
  if (doc.cpi.length > MAX_HISTORY_CPI) {
    fail("backfill.json cpi count " + doc.cpi.length + " exceeds the " + MAX_HISTORY_CPI + " cap");
  }
  if (doc.cpi.length !== metadata.cpi_count) {
    fail("backfill.json cpi length must match metadata cpi_count");
  }
  const seenDates = [];
  doc.daily.forEach((row, i) => {
    const path = "backfill.json daily[" + i + "]";
    if (typeof row !== "object" || row === null) fail(path + " must be an object");
    if (!isRealIsoDate(row.date)) fail(path + ".date must be a strict ISO date");
    seenDates.push(row.date);
    if (row.verified !== false) {
      fail(path + ".verified must be false (promoted-row forgery): refusing to publish");
    }
    if (row.source !== BACKFILL_SOURCE) {
      fail(path + ".source must be " + BACKFILL_SOURCE);
    }
    if (row.snapshot_sha256 !== null) {
      fail(path + ".snapshot_sha256 must be null for backfilled rows");
    }
    if (row.input_digest_sha256 !== null) {
      fail(path + ".input_digest_sha256 must be null for backfilled rows");
    }
    if (typeof row.row_digest !== "string" || !SHA256_HEX_RE.test(row.row_digest)) {
      fail(path + ".row_digest must be a 64 character hex digest");
    }
    const yields = row.yields_percent;
    if (typeof yields !== "object" || yields === null) fail(path + ".yields_percent must be an object");
    for (const tenor of TENORS) {
      assertFinite(yields[tenor], path + ".yields_percent." + tenor);
    }
    if (row.yields_unit !== "percent") fail(path + ".yields_unit must be percent");
    const slopes = row.slopes_bp;
    if (typeof slopes !== "object" || slopes === null) fail(path + ".slopes_bp must be an object");
    for (const key of SLOPE_KEYS) {
      assertFinite(slopes[key], path + ".slopes_bp." + key);
      const pair = SLOPE_PAIRS[key];
      const expected = (yields[pair[1]] - yields[pair[0]]) * 100;
      if (Math.abs(slopes[key] - expected) > 1.0 + 1e-9) {
        fail(path + ".slopes_bp." + key + " does not recompute within 1.0 bp");
      }
    }
    if (!["ok", "partial", "missing"].includes(row.spreads_status)) {
      fail(path + ".spreads_status must be ok, partial, or missing");
    }
    const spreads = row.spreads_bp;
    if (typeof spreads !== "object" || spreads === null) fail(path + ".spreads_bp must be an object");
    let present = 0;
    for (const tenor of TENORS) {
      const v = spreads[tenor];
      if (v === null) continue;
      assertFinite(v, path + ".spreads_bp." + tenor);
      present += 1;
    }
    if (row.spreads_status === "ok" && present !== 4) fail(path + ".spreads_status ok needs four spreads");
    if (row.spreads_status === "missing" && present !== 0) fail(path + ".spreads_status missing needs zero spreads");
    if (row.spreads_status === "partial" && (present === 0 || present === 4)) {
      fail(path + ".spreads_status partial needs one to three spreads");
    }
    const body = {};
    for (const [k, v] of Object.entries(row)) {
      if (k === "row_digest") continue;
      body[k] = v;
    }
    if (rowDigestFor(body) !== row.row_digest) {
      fail(path + ".row_digest does not recompute (tampered row): refusing to publish");
    }
  });
  for (let i = 1; i < seenDates.length; i++) {
    if (!(seenDates[i] > seenDates[i - 1])) fail("backfill.json daily dates must be strictly increasing");
  }
  if (new Set(seenDates).size !== seenDates.length) fail("backfill.json daily dates must be unique");
  const seenMonths = [];
  doc.cpi.forEach((row, i) => {
    const path = "backfill.json cpi[" + i + "]";
    if (typeof row !== "object" || row === null) fail(path + " must be an object");
    if (typeof row.month !== "string" || !MONTH_RE.test(row.month)) fail(path + ".month must be YYYY-MM");
    seenMonths.push(row.month);
    if (row.verified !== false) {
      fail(path + ".verified must be false (promoted-row forgery): refusing to publish");
    }
    if (row.source !== BACKFILL_SOURCE) fail(path + ".source must be " + BACKFILL_SOURCE);
    assertFinite(row.trim_mom_percent, path + ".trim_mom_percent");
    assertFinite(row.median_mom_percent, path + ".median_mom_percent");
    if (row.trim_yoy_percent !== null) assertFinite(row.trim_yoy_percent, path + ".trim_yoy_percent");
    if (row.median_yoy_percent !== null) assertFinite(row.median_yoy_percent, path + ".median_yoy_percent");
    if (typeof row.row_digest !== "string" || !SHA256_HEX_RE.test(row.row_digest)) {
      fail(path + ".row_digest must be a 64 character hex digest");
    }
    const body = {};
    for (const [k, v] of Object.entries(row)) {
      if (k === "row_digest") continue;
      body[k] = v;
    }
    if (rowDigestFor(body) !== row.row_digest) {
      fail(path + ".row_digest does not recompute (tampered row): refusing to publish");
    }
  });
  for (let i = 1; i < seenMonths.length; i++) {
    if (!(seenMonths[i] > seenMonths[i - 1])) fail("backfill.json cpi months must be strictly increasing");
  }
  if (new Set(seenMonths).size !== seenMonths.length) fail("backfill.json cpi months must be unique");
}

/**
 * Bounded shape check for history fields copied verbatim from backfill.json.
 *
 * exclusions and provenance publish straight into history.json, so they take
 * the caps validateSnapshot applies to snapshot provenance: nesting depth
 * MAX_BOUNDED_DEPTH, MAX_BOUNDED_ENTRIES per array or object, and
 * MAX_BOUNDED_STRING characters per string. Any violation fails closed
 * before publish.
 *
 * @param {unknown} value field value to check.
 * @param {string} path error path label.
 * @param {number} depth current nesting depth, zero at the field root.
 */
function assertBoundedField(value, path, depth) {
  if (depth > MAX_BOUNDED_DEPTH) {
    fail(path + " exceeds the " + MAX_BOUNDED_DEPTH + " level depth cap: refusing to publish");
  }
  if (typeof value === "string") {
    if (value.length > MAX_BOUNDED_STRING) {
      fail(path + " exceeds the " + MAX_BOUNDED_STRING + " character cap: refusing to publish");
    }
    return;
  }
  if (value === null || typeof value === "number" || typeof value === "boolean") return;
  if (Array.isArray(value)) {
    if (value.length > MAX_BOUNDED_ENTRIES) {
      fail(path + " exceeds the " + MAX_BOUNDED_ENTRIES + " entry cap: refusing to publish");
    }
    value.forEach((item, i) => assertBoundedField(item, path + "[" + i + "]", depth + 1));
    return;
  }
  if (typeof value === "object") {
    const keys = Object.keys(value);
    if (keys.length > MAX_BOUNDED_ENTRIES) {
      fail(path + " exceeds the " + MAX_BOUNDED_ENTRIES + " entry cap: refusing to publish");
    }
    for (const key of keys) {
      assertBoundedField(value[key], path + "." + key, depth + 1);
    }
    return;
  }
  fail(path + " has unsupported type " + typeof value + ": refusing to publish");
}

function snapshotYields(snapshotDoc, date) {
  const benchmarks = snapshotDoc?.observations?.benchmarks;
  if (typeof benchmarks !== "object" || benchmarks === null) return null;
  const out = {};
  for (const tenor of TENORS) {
    const entry = benchmarks[tenor];
    const value = entry?.valet?.value;
    if (typeof value !== "number" || !Number.isFinite(value)) return null;
    out[tenor] = value;
  }
  return out;
}

function snapshotSpreads(snapshotDoc) {
  const section = snapshotDoc?.observations?.spreads;
  if (typeof section !== "object" || section === null) return { status: "missing", byTenor: {} };
  if (section.status === "ok" && Array.isArray(section.records)) {
    const byTenor = {};
    for (const record of section.records) {
      if (typeof record?.tenor !== "string") continue;
      if (typeof record?.spread_bp !== "number" || !Number.isFinite(record.spread_bp)) continue;
      byTenor[record.tenor] = record.spread_bp;
    }
    // status ok needs exactly the four tenor spreads that validateHistory
    // checks at load, so an ok section with fewer finite tenor records maps
    // to the partial or missing rule instead of publishing ok with nulls.
    let present = 0;
    for (const tenor of TENORS) {
      if (Number.isFinite(byTenor[tenor])) present += 1;
    }
    if (present === 4) return { status: "ok", byTenor };
    if (present > 0) return { status: "partial", byTenor };
    return { status: "missing", byTenor: {} };
  }
  return { status: "missing", byTenor: {} };
}

function snapshotBreaksFlags(snapshotDoc) {
  const section = snapshotDoc?.observations?.breaks;
  const byTenor = { "2Y": false, "5Y": false, "10Y": false, "30Y": false };
  let anySwitch = false;
  let anyGap = false;
  if (typeof section === "object" && section !== null && Array.isArray(section.records)) {
    for (const record of section.records) {
      const tenor = record?.tenor;
      if (!TENORS.includes(tenor)) continue;
      if (record?.switch_in_window === true) {
        byTenor[tenor] = true;
        anySwitch = true;
      }
      if (record?.calendar_gap === true) anyGap = true;
    }
  }
  return { byTenor, anySwitch, anyGap };
}

/**
 * Valet print date for a staged snapshot, taken from curve.settlement_date.
 *
 * The daily workflow can run before BoC publishes that day's yields, so a
 * snapshot labeled D may carry the previous business day's print. History
 * rows must be dated by the print date, never by the snapshot label. A
 * settlement that is missing, not a strict ISO date, later than the label,
 * or earlier than the sealed backfill print window would misdate or corrupt
 * the merged history, so the build fails closed.
 *
 * Callers only reach this helper for snapshots that still merge benchmark
 * yields. Snapshots without yields never enter history and keep the existing
 * sparse degradation path, which skips them before this check.
 *
 * @param {{ date: string, snapshotDoc: Record<string, any> }} item staged snapshot.
 * @param {string | null} minPrintDate earliest allowed print date, the first
 *   sealed backfill row date minus PRINT_WINDOW_DAYS, or null when the
 *   backfill carries no daily rows and no lower bound applies.
 * @returns {string} the strict ISO print date, inside the allowed window.
 */
function snapshotPrintDate(item, minPrintDate) {
  const settlement = item.snapshotDoc?.observations?.curve?.settlement_date;
  if (typeof settlement !== "string" || !isRealIsoDate(settlement)) {
    fail(
      "snapshot.json for " + item.date + " has curve.settlement_date " +
        JSON.stringify(settlement ?? null) + ": refusing to publish"
    );
  }
  if (settlement > item.date) {
    fail(
      "snapshot.json for " + item.date + " has curve.settlement_date " + settlement +
        " later than the snapshot date: refusing to publish"
    );
  }
  if (minPrintDate !== null && settlement < minPrintDate) {
    fail(
      "snapshot.json for " + item.date + " has curve.settlement_date " + settlement +
        " earlier than the sealed backfill print window start " + minPrintDate +
        ": refusing to publish"
    );
  }
  return settlement;
}

function buildVerifiedDaily(date, yields, spreadsInfo, breaksFlags, snapshotDigest, switchFallback, calendarFallback) {
  const slopes = {};
  for (const key of SLOPE_KEYS) {
    const pair = SLOPE_PAIRS[key];
    slopes[key] = (yields[pair[1]] - yields[pair[0]]) * 100;
  }
  const spreads = {};
  for (const tenor of TENORS) {
    const v = spreadsInfo.byTenor[tenor];
    spreads[tenor] = typeof v === "number" && Number.isFinite(v) ? v : null;
  }
  // snapshotSpreads only returns ok with four finite tenor spreads, partial
  // with one to three, and missing with none, so the status passes through.
  const status = spreadsInfo.status;
  const byTenor = breaksFlags.anySwitch || breaksFlags.anyGap ? breaksFlags.byTenor : (switchFallback ?? breaksFlags.byTenor);
  const switchFlag = TENORS.some((t) => byTenor[t]);
  const gapFlag = breaksFlags.anyGap || (calendarFallback ?? false);
  const body = {
    calendar_gap: gapFlag,
    date,
    input_digest_sha256: null,
    slopes_bp: slopes,
    slopes_unit: "basis_points",
    snapshot_sha256: snapshotDigest,
    source: VERIFIED_SOURCE,
    spreads_bp: spreads,
    spreads_status: status,
    spreads_unit: "basis_points",
    switch_by_tenor: byTenor,
    switch_in_window: switchFlag,
    verified: true,
    yields_percent: yields,
    yields_unit: "percent",
  };
  return { ...body, row_digest: rowDigestFor(body) };
}

function buildVerifiedCpi(month, snapRow, snapshotDigest) {
  const body = {
    median_component: snapRow.median_component,
    median_mom_percent: snapRow.median_mom_percent,
    median_yoy_percent: snapRow.median_yoy_percent ?? null,
    mom_unit: "percent_per_month",
    month,
    snapshot_sha256: snapshotDigest,
    source: VERIFIED_SOURCE,
    trim_mom_percent: snapRow.trim_mom_percent,
    trim_yoy_percent: snapRow.trim_yoy_percent ?? null,
    verified: true,
    yoy_unit: "percent",
  };
  return { ...body, row_digest: rowDigestFor(body) };
}

async function main() {
  // Phase 1: validate everything before publishing anything. Any mismatch
  // or parse failure aborts with a nonzero exit and publishes nothing.
  let dates = [];
  if (await exists(snapshotsDir)) {
    const entries = await fs.readdir(snapshotsDir);
    dates = entries.filter((name) => isRealIsoDate(name)).sort();
  }
  const staged = [];
  for (const date of dates) {
    const srcSnapshot = join(snapshotsDir, date, "snapshot.json");
    const srcManifest = join(snapshotsDir, date, "manifest.json");
    const srcVerify = join(snapshotsDir, date, "verify.json");
    if (!(await exists(srcSnapshot))) continue;
    if (!(await exists(srcManifest))) {
      fail("missing manifest.json for " + date + ": refusing to publish");
    }
    if (!(await exists(srcVerify))) {
      fail("missing verify.json for " + date + ": refusing to publish");
    }
    const rawSnapshot = await fs.readFile(srcSnapshot);
    let snapshotText;
    try {
      snapshotText = rawSnapshot.toString("utf8");
    } catch (err) {
      fail("snapshot.json for " + date + " is not valid UTF-8: " + err.message);
    }
    let snapshotDoc;
    try {
      snapshotDoc = JSON.parse(snapshotText);
    } catch (err) {
      fail("snapshot.json for " + date + " is not valid JSON: " + err.message);
    }
    if (snapshotDoc?.metadata?.snapshot_date !== date) {
      fail(
        "snapshot.json for " + date + " has snapshot_date " +
          JSON.stringify(snapshotDoc?.metadata?.snapshot_date) + ": refusing to publish"
      );
    }
    const digest = sha256HexBytes(rawSnapshot);
    const manifestText = await fs.readFile(srcManifest, "utf8");
    const recorded = manifestDigest(manifestText, date);
    if (recorded !== digest) {
      fail(
        "manifest digest mismatch for " + date + " (manifest " + recorded.slice(0, 8) +
          " versus recomputed " + digest.slice(0, 8) + "): refusing to publish"
      );
    }
    let verifyDoc;
    try {
      verifyDoc = JSON.parse(await fs.readFile(srcVerify, "utf8"));
    } catch (err) {
      fail("verify.json for " + date + " is not valid JSON: " + err.message);
    }
    if (typeof verifyDoc?.passed !== "boolean") {
      fail("verify.json for " + date + " has no boolean passed field: refusing to publish");
    }
    if (verifyDoc.snapshot_sha256 !== digest) {
      fail("verify.snapshot_sha256 mismatch for " + date + ": refusing to publish");
    }
    staged.push({ date, snapshotText, snapshotDoc, verifyText: JSON.stringify(verifyDoc), digest, verifyPassed: verifyDoc.passed });
  }

  // Stage 2: sealed backfill merge with verified precedence. Absent
  // artifacts fail the build, and any overlap beyond tolerance fails.
  if (!(await exists(backfillPath))) {
    fail("missing history/backfill.json: refusing to publish without the sealed backfill");
  }
  if (!(await exists(backfillManifestPath))) {
    fail("missing history/backfill-manifest.json: refusing to publish without the backfill manifest");
  }
  const rawBackfill = await fs.readFile(backfillPath);
  if (rawBackfill.length > MAX_HISTORY_BYTES) {
    fail("backfill.json of " + rawBackfill.length + " bytes exceeds the " + MAX_HISTORY_BYTES + " byte cap");
  }
  const backfillDigest = sha256HexBytes(rawBackfill);
  let backfillManifest;
  try {
    backfillManifest = JSON.parse(await fs.readFile(backfillManifestPath, "utf8"));
  } catch (err) {
    fail("backfill-manifest.json is not valid JSON: " + err.message);
  }
  const recordedBackfill = backfillManifest?.files?.["backfill.json"]?.sha256;
  if (typeof recordedBackfill !== "string" || !SHA256_HEX_RE.test(recordedBackfill.trim())) {
    fail("backfill-manifest.json has no valid backfill.json sha256 digest");
  }
  if (recordedBackfill.trim() !== backfillDigest) {
    fail(
      "backfill manifest digest mismatch (manifest " + recordedBackfill.trim().slice(0, 8) +
        " versus recomputed " + backfillDigest.slice(0, 8) + "): refusing to publish"
    );
  }
  let backfillDoc;
  try {
    backfillDoc = JSON.parse(rawBackfill.toString("utf8"));
  } catch (err) {
    fail("backfill.json is not valid JSON: " + err.message);
  }
  validateBackfillDoc(backfillDoc);

  // exclusions and provenance copy verbatim into published history.json, so
  // they take the bounded shape check before anything is written: top level
  // types first, then depth, entry, and string caps.
  const historyExclusions = backfillDoc.exclusions ?? [];
  const historyProvenance = backfillDoc.provenance ?? {};
  if (!Array.isArray(historyExclusions)) {
    fail("backfill.json exclusions must be an array: refusing to publish");
  }
  if (
    typeof historyProvenance !== "object" ||
    historyProvenance === null ||
    Array.isArray(historyProvenance)
  ) {
    fail("backfill.json provenance must be an object: refusing to publish");
  }
  assertBoundedField(historyExclusions, "backfill.json exclusions", 0);
  assertBoundedField(historyProvenance, "backfill.json provenance", 0);

  // Lower bound for a staged settlement: a crafted print date (for example
  // 0001-01-01) must not merge a row far outside the sealed history window.
  // The bound is the earliest sealed backfill row date minus the print
  // window, and it is skipped when the backfill carries no daily rows.
  const minPrintDate =
    backfillDoc.daily.length > 0
      ? isoDaysBefore(backfillDoc.daily[0].date, PRINT_WINDOW_DAYS)
      : null;

  const dailyByDate = new Map();
  for (const row of backfillDoc.daily) dailyByDate.set(row.date, row);
  const cpiByMonth = new Map();
  for (const row of backfillDoc.cpi) cpiByMonth.set(row.month, row);

  // Staged items arrive in ascending snapshot label order (sorted above).
  // Each verified row is dated by the Valet print date (curve.settlement_date)
  // because a stale snapshot can label a day whose yields were printed earlier.
  for (const item of staged) {
    const yields = snapshotYields(item.snapshotDoc, item.date);
    if (yields === null) {
      continue;
    }
    if (item.verifyPassed !== true) {
      continue;
    }
    const printDate = snapshotPrintDate(item, minPrintDate);
    if (printDate !== item.date) {
      console.warn(
        "build-data: snapshot " + item.date + " settles on " + printDate +
          "; merging verified history under the print date"
      );
    }
    const spreadsInfo = snapshotSpreads(item.snapshotDoc);
    const existing = dailyByDate.get(printDate);
    if (existing) {
      const counterpart = existing.source === VERIFIED_SOURCE ? "snapshot" : "backfill";
      for (const tenor of TENORS) {
        const diffBp = Math.abs(yields[tenor] - existing.yields_percent[tenor]) * 100;
        if (diffBp > 1.0 + 1e-9) {
          fail(
            "history overlap conflict on " + printDate + " tenor " + tenor +
              " beyond 1.0 bp (snapshot " + yields[tenor] + " versus " + counterpart + " " +
              existing.yields_percent[tenor] + "): refusing to publish"
          );
        }
        const existingSpread = existing.spreads_bp[tenor];
        const incomingSpread = spreadsInfo.byTenor[tenor];
        if (Number.isFinite(existingSpread) && Number.isFinite(incomingSpread)) {
          const spreadDiffBp = Math.abs(existingSpread - incomingSpread);
          if (spreadDiffBp > 1.0 + 1e-9) {
            fail(
              "history overlap conflict on " + printDate + " spread tenor " + tenor +
                " beyond 1.0 bp (snapshot " + incomingSpread + " versus " + counterpart + " " +
                existingSpread + "): refusing to publish"
            );
          }
        }
      }
      // Spreads arbitration extends the yields rule: per tenor values compare
      // within 1.0 bp where both rows carry a finite spread, and spreads_status
      // must match when both rows carry spreads (ok or partial), otherwise the
      // build fails closed. A missing side never fails the comparison, so a
      // snapshot that adds spreads to a spreadless backfill row still merges.
      const existingStatus = existing.spreads_status;
      const existingCarriesSpreads = existingStatus === "ok" || existingStatus === "partial";
      const incomingCarriesSpreads =
        spreadsInfo.status === "ok" || spreadsInfo.status === "partial";
      if (
        existingCarriesSpreads &&
        incomingCarriesSpreads &&
        existingStatus !== spreadsInfo.status
      ) {
        fail(
          "history overlap conflict on " + printDate + " spreads_status " + existingStatus +
            " versus snapshot " + spreadsInfo.status + ": refusing to publish"
        );
      }
    }
    const existingVerified =
      existing !== undefined &&
      existing.source === VERIFIED_SOURCE &&
      typeof existing.snapshot_sha256 === "string";
    if (existingVerified) {
      // Two snapshots can resolve to the same print date, for example a stale
      // snapshot labeled 2026-11-02 with settlement 2026-10-30 sitting next to
      // the real 2026-10-30 snapshot. Staged items run in ascending label
      // order, so the first writer wins: keeping its row keeps the row digest
      // stable and ties the row to the snapshot whose label matches the print
      // date. The overlap check above already failed closed when the second
      // snapshot disagrees beyond 1.0 bp on yields or spreads, or carries a
      // different spreads_status while both rows carry spreads, so agreement
      // here means the row stays untouched.
      console.warn(
        "build-data: snapshot " + item.date + " shares print date " + printDate +
          " with an already merged snapshot; keeping the existing verified row"
      );
    } else {
      const breaksFlags = snapshotBreaksFlags(item.snapshotDoc);
      const verified = buildVerifiedDaily(
        printDate,
        yields,
        spreadsInfo,
        breaksFlags,
        item.digest,
        existing?.switch_by_tenor,
        existing?.calendar_gap
      );
      dailyByDate.set(printDate, verified);
    }
    const inflationHistory = item.snapshotDoc?.observations?.inflation?.history;
    if (Array.isArray(inflationHistory)) {
      for (const snapRow of inflationHistory) {
        if (typeof snapRow !== "object" || snapRow === null) continue;
        const month = snapRow.month;
        if (typeof month !== "string" || !MONTH_RE.test(month)) continue;
        const existingCpi = cpiByMonth.get(month);
        if (existingCpi) {
          const trimDiff = Math.abs(snapRow.trim_mom_percent - existingCpi.trim_mom_percent);
          const medianDiff = Math.abs(snapRow.median_mom_percent - existingCpi.median_mom_percent);
          if (trimDiff > 0.01 + 1e-9 || medianDiff > 0.01 + 1e-9) {
            fail(
              "history CPI overlap conflict on " + month + " beyond 0.01 pp: refusing to publish"
            );
          }
          // CPI mirrors the daily first writer rule: after the 0.01 pp
          // agreement check, a verified CPI row that already owns the month
          // keeps its values, digest, and snapshot link, and the later
          // snapshot is skipped. A backfill month (verified false) still
          // takes the verified overwrite.
          if (existingCpi.verified === true) {
            console.warn(
              "build-data: snapshot " + item.date + " shares CPI month " + month +
                " with an already merged snapshot; keeping the existing verified row"
            );
            continue;
          }
        }
        if (typeof snapRow.trim_mom_percent !== "number" || typeof snapRow.median_mom_percent !== "number") continue;
        if (typeof snapRow.median_component !== "string") continue;
        cpiByMonth.set(month, buildVerifiedCpi(month, snapRow, item.digest));
      }
    }
  }

  function nextCalendarMonth(month) {
    const year = Number(month.slice(0, 4));
    const mon = Number(month.slice(5, 7));
    const nextYear = mon === 12 ? year + 1 : year;
    const nextMon = mon === 12 ? 1 : mon + 1;
    return nextYear + "-" + String(nextMon).padStart(2, "0");
  }

  const mergedDaily = [...dailyByDate.values()].sort((a, b) => (a.date < b.date ? -1 : 1));
  const mergedCpi = [...cpiByMonth.values()].sort((a, b) => (a.month < b.month ? -1 : 1));
  for (let i = 1; i < mergedCpi.length; i++) {
    if (mergedCpi[i].month !== nextCalendarMonth(mergedCpi[i - 1].month)) {
      fail(
        "history CPI month gap between " + mergedCpi[i - 1].month + " and " + mergedCpi[i].month +
          ": months must be consecutive calendar months before compounding: refusing to publish"
      );
    }
  }
  const compoundYear = (moms) => {
    let factor = 1;
    for (const m of moms) factor *= 1 + m / 100;
    return (factor - 1) * 100;
  };
  const trimSeries = mergedCpi.map((row) => row.trim_mom_percent);
  const medianSeries = mergedCpi.map((row) => row.median_mom_percent);
  for (let i = 0; i < mergedCpi.length; i++) {
    const row = mergedCpi[i];
    let nextTrim = null;
    let nextMedian = null;
    if (i >= 11) {
      for (let k = i - 11 + 1; k <= i; k++) {
        if (mergedCpi[k].month !== nextCalendarMonth(mergedCpi[k - 1].month)) {
          fail(
            "history CPI year over year at " + mergedCpi[i].month + " needs 12 consecutive calendar months, gap between " +
              mergedCpi[k - 1].month + " and " + mergedCpi[k].month + ": refusing to publish"
          );
        }
      }
      nextTrim = compoundYear(trimSeries.slice(i - 11, i + 1));
      nextMedian = compoundYear(medianSeries.slice(i - 11, i + 1));
    }
    const trimSame =
      (row.trim_yoy_percent === null && nextTrim === null) ||
      (typeof row.trim_yoy_percent === "number" &&
        typeof nextTrim === "number" &&
        Math.abs(row.trim_yoy_percent - nextTrim) <= 1e-9);
    const medianSame =
      (row.median_yoy_percent === null && nextMedian === null) ||
      (typeof row.median_yoy_percent === "number" &&
        typeof nextMedian === "number" &&
        Math.abs(row.median_yoy_percent - nextMedian) <= 1e-9);
    if (trimSame && medianSame) continue;
    row.trim_yoy_percent = nextTrim;
    row.median_yoy_percent = nextMedian;
    const body = {};
    for (const [key, value] of Object.entries(row)) {
      if (key === "row_digest") continue;
      body[key] = value;
    }
    row.row_digest = rowDigestFor(body);
  }
  let dailyPolicy;
  try {
    dailyPolicy = applyOverflowPolicy(mergedDaily, MAX_HISTORY_DAILY);
  } catch (err) {
    fail(err.message);
  }
  const cappedDaily = dailyPolicy.rows;
  const trimmedBackfilledCount = dailyPolicy.trimmedCount;
  if (trimmedBackfilledCount > 0) {
    console.warn(
      "build-data: trimmed " + trimmedBackfilledCount +
        " oldest backfilled daily row(s) to stay within the " +
        MAX_HISTORY_DAILY + " cap"
    );
  }
  if (mergedCpi.length > MAX_HISTORY_CPI) {
    fail("merged CPI count " + mergedCpi.length + " exceeds the " + MAX_HISTORY_CPI + " cap");
  }
  const historyDoc = {
    cpi: mergedCpi,
    daily: cappedDaily,
    exclusions: historyExclusions,
    metadata: {
      asof: staged.length > 0 ? staged[staged.length - 1].date : backfillDoc.metadata.asof,
      cpi_count: mergedCpi.length,
      cpi_count_unit: "count",
      daily_count: cappedDaily.length,
      daily_count_unit: "count",
      method: HISTORY_METHOD,
      schema_version: 1,
    },
    provenance: historyProvenance,
  };
  const historyText = canonicalText(historyDoc);
  if (Buffer.byteLength(historyText, "utf8") > MAX_HISTORY_BYTES) {
    fail("merged history.json exceeds the " + MAX_HISTORY_BYTES + " byte cap");
  }
  const historyDigest = sha256HexText(historyText);

  // Phase 3: publish only after every date and the history merge validated.
  await fs.mkdir(outDir, { recursive: true });
  const published = staged.map((s) => s.date);
  const indexEntries = {};
  for (const item of staged) {
    const destDir = join(outDir, item.date);
    await fs.mkdir(destDir, { recursive: true });
    await fs.writeFile(join(destDir, "snapshot.json"), item.snapshotText, "utf8");
    await fs.writeFile(join(destDir, "verify.json"), item.verifyText + "\n", "utf8");
    indexEntries[item.date] = {
      snapshot_sha256: item.digest,
      verify_passed: item.verifyPassed,
      bytes_utf8: Buffer.byteLength(item.snapshotText, "utf8"),
    };
  }
  await fs.writeFile(join(outDir, "history.json"), historyText, "utf8");
  // Prune stale dates removed from snapshots so old output is not republished.
  // history.json and index.json are live outputs and never pruned.
  if (await exists(outDir)) {
    const outEntries = await fs.readdir(outDir);
    const live = new Set([...published, "index.json", "history.json", ".gitkeep"]);
    for (const name of outEntries) {
      if (live.has(name)) continue;
      if (!DATE_RE.test(name)) continue;
      await fs.rm(join(outDir, name), { recursive: true, force: true });
      console.log("build-data: pruned stale date " + name);
    }
  }
  const indexDoc = {
    generated_utc: new Date().toISOString(),
    dates: published,
    latest: published.length > 0 ? published[published.length - 1] : null,
    entries: indexEntries,
    history: {
      sha256: historyDigest,
      bytes_utf8: Buffer.byteLength(historyText, "utf8"),
      daily_count: cappedDaily.length,
      cpi_count: mergedCpi.length,
      trimmed_backfilled_count: trimmedBackfilledCount,
    },
  };
  await fs.writeFile(join(outDir, "index.json"), JSON.stringify(indexDoc, null, 2) + "\n", "utf8");
  console.log("build-data: published " + published.length + " date(s) plus history to public/data");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
