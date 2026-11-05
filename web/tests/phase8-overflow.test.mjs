import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import {
  mkdtemp,
  mkdir,
  writeFile,
  readFile,
  readdir,
  rm,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { applyOverflowPolicy } from "../scripts/history-overflow.mjs";
import { validateHistory, MAX_HISTORY_DAILY } from "../src/lib/validate.ts";

const scriptsDir = join(dirname(fileURLToPath(import.meta.url)), "..", "scripts");
// The overflow cap follows the raised 10 year history cap in validate.ts.
const CAP = MAX_HISTORY_DAILY;

function dateAt(index) {
  const start = Date.UTC(2021, 9, 25);
  return new Date(start + index * 86400000).toISOString().slice(0, 10);
}

function digestFor(label) {
  return createHash("sha256").update(label, "utf8").digest("hex");
}

function backfillRow(date) {
  return {
    date,
    snapshot_sha256: null,
    source: "derived:backfill_v1",
    verified: false,
  };
}

function verifiedRow(date) {
  return {
    date,
    snapshot_sha256: digestFor(date),
    source: "derived:history_verified_v1",
    verified: true,
  };
}

function buildRows(backfillCount, verifiedCount) {
  const rows = [];
  for (let i = 0; i < backfillCount; i++) {
    rows.push(backfillRow(dateAt(i)));
  }
  for (let k = 0; k < verifiedCount; k++) {
    rows.push(verifiedRow(dateAt(backfillCount + k)));
  }
  return rows;
}

function isVerifiedRow(row) {
  return typeof row.snapshot_sha256 === "string";
}

describe("applyOverflowPolicy merged daily overflow", () => {
  it("drops exactly the oldest backfill row at " + (CAP + 1) + " rows", () => {
    const rows = buildRows(CAP, 1);
    assert.equal(rows.length, CAP + 1);
    const result = applyOverflowPolicy(rows, CAP);
    assert.equal(result.rows.length, CAP);
    assert.equal(result.trimmedCount, 1);
    assert.equal(result.rows[0], rows[1]);
    assert.equal(result.rows[0].date, dateAt(1));
    assert.ok(!result.rows.includes(rows[0]));
    const verifiedKept = result.rows.filter(isVerifiedRow);
    assert.equal(verifiedKept.length, 1);
    assert.equal(verifiedKept[0], rows[CAP]);
    assert.equal(verifiedKept[0].date, dateAt(CAP));
  });

  it("drops the two oldest backfill rows at " + (CAP + 2) + " rows", () => {
    const rows = buildRows(CAP, 2);
    assert.equal(rows.length, CAP + 2);
    const result = applyOverflowPolicy(rows, CAP);
    assert.equal(result.rows.length, CAP);
    assert.equal(result.trimmedCount, 2);
    assert.equal(result.rows[0].date, dateAt(2));
    assert.ok(!result.rows.includes(rows[0]));
    assert.ok(!result.rows.includes(rows[1]));
    assert.equal(result.rows.filter(isVerifiedRow).length, 2);
  });

  it("refuses to publish when verified rows alone exceed the cap", () => {
    const rows = buildRows(0, CAP + 1);
    assert.equal(rows.length, CAP + 1);
    assert.throws(
      () => applyOverflowPolicy(rows, CAP),
      new RegExp(
        "verified daily rows " + (CAP + 1) + " alone exceed the " + CAP + " cap: refusing to publish"
      )
    );
  });

  it("passes rows through untouched when the count is within the cap", () => {
    const small = buildRows(3, 1);
    const smallResult = applyOverflowPolicy(small, CAP);
    assert.equal(smallResult.rows.length, 4);
    assert.equal(smallResult.trimmedCount, 0);
    assert.deepEqual(smallResult.rows, small);
    const atCap = buildRows(CAP, 0);
    const atCapResult = applyOverflowPolicy(atCap, CAP);
    assert.equal(atCapResult.rows.length, CAP);
    assert.equal(atCapResult.trimmedCount, 0);
    assert.deepEqual(atCapResult.rows, atCap);
  });

  it("drops the oldest dates in order and keeps verified digests intact", () => {
    const rows = [];
    for (let i = 0; i < CAP + 2; i++) {
      rows.push(i === 10 || i === CAP + 1 ? verifiedRow(dateAt(i)) : backfillRow(dateAt(i)));
    }
    const verifiedBefore = rows
      .filter(isVerifiedRow)
      .map((row) => ({ date: row.date, digest: row.snapshot_sha256 }));
    assert.equal(verifiedBefore.length, 2);
    const result = applyOverflowPolicy(rows, CAP);
    assert.equal(result.rows.length, CAP);
    assert.equal(result.trimmedCount, 2);
    assert.equal(result.rows[0].date, dateAt(2));
    assert.ok(!result.rows.includes(rows[0]));
    assert.ok(!result.rows.includes(rows[1]));
    for (let i = 1; i < result.rows.length; i++) {
      assert.ok(result.rows[i].date > result.rows[i - 1].date);
    }
    for (const entry of verifiedBefore) {
      const kept = result.rows.find((row) => row.date === entry.date);
      assert.ok(kept, "verified row " + entry.date + " must survive");
      assert.equal(kept.snapshot_sha256, entry.digest);
      assert.equal(kept.verified, true);
      assert.equal(kept.source, "derived:history_verified_v1");
    }
  });

  it("rejects a cap that is not a positive integer", () => {
    const rows = buildRows(3, 0);
    assert.throws(() => applyOverflowPolicy(rows, 0), /cap must be a positive integer/);
    assert.throws(() => applyOverflowPolicy(rows, -1), /cap must be a positive integer/);
    assert.throws(() => applyOverflowPolicy(rows, 12.5), /cap must be a positive integer/);
  });

  it("rejects rows that are not sorted ascending by date", () => {
    const rows = [backfillRow(dateAt(2)), backfillRow(dateAt(1)), backfillRow(dateAt(3))];
    assert.throws(
      () => applyOverflowPolicy(rows, CAP),
      /rows must be sorted ascending by date/
    );
  });

  it("rejects duplicate row dates", () => {
    const rows = [backfillRow(dateAt(1)), backfillRow(dateAt(1)), backfillRow(dateAt(2))];
    assert.throws(
      () => applyOverflowPolicy(rows, CAP),
      /duplicate row date .*: dates must be unique/
    );
  });

  it("rejects rows whose date is not a string", () => {
    const rows = [backfillRow(dateAt(1)), { ...backfillRow(dateAt(2)), date: 20261101 }];
    assert.throws(() => applyOverflowPolicy(rows, CAP), /row 1 date must be a string/);
  });
});

function canonicalNumber(value) {
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
  const keys = Object.keys(value).sort();
  if (keys.length === 0) return "{}";
  const parts = keys.map(
    (key) => " ".repeat(indent + 2) + JSON.stringify(key) + ": " + canonicalValue(value[key], indent + 2)
  );
  return "{\n" + parts.join(",\n") + "\n" + " ".repeat(indent) + "}";
}

function canonicalText(payload) {
  return canonicalValue(payload, 0) + "\n";
}

function digestOf(body) {
  return createHash("sha256").update(canonicalText(body), "utf8").digest("hex");
}

function backfillDailyRow(date, yields) {
  const body = {
    calendar_gap: false,
    date,
    input_digest_sha256: null,
    slopes_bp: {
      "2Y_5Y": (yields["5Y"] - yields["2Y"]) * 100,
      "2Y_10Y": (yields["10Y"] - yields["2Y"]) * 100,
      "5Y_30Y": (yields["30Y"] - yields["5Y"]) * 100,
      "10Y_30Y": (yields["30Y"] - yields["10Y"]) * 100,
    },
    slopes_unit: "basis_points",
    snapshot_sha256: null,
    source: "derived:backfill_v1",
    spreads_bp: { "2Y": null, "5Y": null, "10Y": null, "30Y": null },
    spreads_status: "missing",
    spreads_unit: "basis_points",
    switch_by_tenor: { "2Y": false, "5Y": false, "10Y": false, "30Y": false },
    switch_in_window: false,
    verified: false,
    yields_percent: yields,
    yields_unit: "percent",
  };
  return { ...body, row_digest: digestOf(body) };
}

function backfillCpiRow(month) {
  const body = {
    median_component: "C01",
    median_mom_percent: 0.2,
    median_yoy_percent: null,
    mom_unit: "percent_per_month",
    month,
    source: "derived:backfill_v1",
    trim_mom_percent: 0.2,
    trim_yoy_percent: null,
    verified: false,
    yoy_unit: "percent",
  };
  return { ...body, row_digest: digestOf(body) };
}

function backfillDoc(daily, cpi) {
  return {
    cpi,
    daily,
    exclusions: [],
    metadata: {
      asof: daily[daily.length - 1].date,
      cpi_count: cpi.length,
      cpi_count_unit: "count",
      daily_count: daily.length,
      daily_count_unit: "count",
      method: "backfill_v1",
      retrieved_utc: "2026-11-04T00:00:00Z",
      schema_version: 1,
    },
    provenance: {},
    retrieved_utc: "2026-11-04T00:00:00Z",
  };
}

function datesEnding(endDate, count) {
  const end = Date.parse(endDate + "T00:00:00Z");
  const dates = [];
  for (let offset = count - 1; offset >= 0; offset -= 1) {
    dates.push(new Date(end - offset * 86400000).toISOString().slice(0, 10));
  }
  return dates;
}

function snapshotWithBenchmarks(date, yields) {
  return JSON.stringify({
    metadata: { snapshot_date: date, schema_version: 1 },
    observations: {
      benchmarks: {
        "2Y": { valet_label: "2Y", valet: { value: yields["2Y"], unit: "percent", quality: "observed", source_id: "valet:BD.CDN.2YR.DQ.YLD" } },
        "5Y": { valet_label: "5Y", valet: { value: yields["5Y"], unit: "percent", quality: "observed", source_id: "valet:BD.CDN.5YR.DQ.YLD" } },
        "10Y": { valet_label: "10Y", valet: { value: yields["10Y"], unit: "percent", quality: "observed", source_id: "valet:BD.CDN.10YR.DQ.YLD" } },
        "30Y": { valet_label: "30Y", valet: { value: yields["30Y"], unit: "percent", quality: "observed", source_id: "valet:BD.CDN.LONG.DQ.YLD" } },
      },
      curve: { settlement_date: date },
    },
    provenance: {
      valet: {
        source_url: "https://example.com/valet",
        retrieved_utc: "2026-11-04T00:00:00Z",
        vintage: date,
      },
    },
    warnings: [],
  });
}

let sandbox = null;

async function makeSandbox() {
  const root = await mkdtemp(join(tmpdir(), "goc-overflow-"));
  const webDir = join(root, "web");
  const scriptDir = join(webDir, "scripts");
  await mkdir(scriptDir, { recursive: true });
  for (const name of ["build-data.mjs", "history-overflow.mjs"]) {
    const source = await readFile(join(scriptsDir, name), "utf8");
    await writeFile(join(scriptDir, name), source, "utf8");
  }
  return {
    root,
    snapshots: join(root, "snapshots"),
    historyDir: join(root, "history"),
    outDir: join(webDir, "public", "data"),
    script: join(scriptDir, "build-data.mjs"),
  };
}

async function writeTriple(sb, date, snapshotText) {
  const snapshot = snapshotText ?? JSON.stringify({ metadata: { snapshot_date: date, schema_version: 1 }, observations: {} });
  const sha = createHash("sha256").update(snapshot, "utf8").digest("hex");
  const dir = join(sb.snapshots, date);
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "snapshot.json"), snapshot, "utf8");
  await writeFile(
    join(dir, "manifest.json"),
    JSON.stringify({ files: { "snapshot.json": { sha256: sha } } }),
    "utf8"
  );
  await writeFile(
    join(dir, "verify.json"),
    JSON.stringify({ passed: true, snapshot_sha256: sha }),
    "utf8"
  );
  return { sha };
}

async function writeBackfill(sb, doc) {
  const text = canonicalText(doc);
  await mkdir(sb.historyDir, { recursive: true });
  await writeFile(join(sb.historyDir, "backfill.json"), text, "utf8");
  const sha = createHash("sha256").update(text, "utf8").digest("hex");
  await writeFile(
    join(sb.historyDir, "backfill-manifest.json"),
    JSON.stringify({ files: { "backfill.json": { sha256: sha, bytes_utf8: text.length } } }),
    "utf8"
  );
}

function runBuild(sb) {
  return new Promise((resolve) => {
    execFile("node", [sb.script], (error, stdout, stderr) => {
      const code = error && typeof error.code === "number" ? error.code : error ? 1 : 0;
      resolve({ code, out: String(stdout), err: String(stderr) });
    });
  });
}

async function readJson(sb, name) {
  return JSON.parse(await readFile(join(sb.outDir, name), "utf8"));
}

beforeEach(async () => {
  sandbox = await makeSandbox();
});

afterEach(async () => {
  if (sandbox) await rm(sandbox.root, { recursive: true, force: true });
  sandbox = null;
});

describe("build-data publishes a capped merged daily history", () => {
  it("trims one oldest backfill row at " + (CAP + 1) + " merged rows and records the trim", async () => {
    const yields = { "2Y": 3.28, "5Y": 3.51, "10Y": 3.78, "30Y": 4.11 };
    const dates = datesEnding("2026-11-01", CAP);
    const daily = dates.map((date) => backfillDailyRow(date, yields));
    await writeBackfill(sandbox, backfillDoc(daily, [backfillCpiRow("2026-09")]));
    const { sha } = await writeTriple(
      sandbox,
      "2026-11-03",
      snapshotWithBenchmarks("2026-11-03", yields)
    );
    const result = await runBuild(sandbox);
    assert.equal(result.code, 0, result.err);
    assert.match(
      result.err,
      new RegExp("trimmed 1 oldest backfilled daily row\\(s\\) to stay within the " + CAP + " cap")
    );
    const history = await readJson(sandbox, "history.json");
    assert.equal(history.daily.length, CAP);
    assert.equal(history.metadata.daily_count, CAP);
    assert.equal(history.daily[0].date, dates[1]);
    assert.ok(!history.daily.some((row) => row.date === dates[0]));
    const last = history.daily[history.daily.length - 1];
    assert.equal(last.date, "2026-11-03");
    assert.equal(last.verified, true);
    assert.equal(last.snapshot_sha256, sha);
    assert.doesNotThrow(() => validateHistory(history));
    const index = await readJson(sandbox, "index.json");
    assert.equal(index.history.daily_count, CAP);
    assert.equal(index.history.trimmed_backfilled_count, 1);
  });

  it("records a zero trim count when the merge fits the cap", async () => {
    const yields = { "2Y": 3.28, "5Y": 3.51, "10Y": 3.78, "30Y": 4.11 };
    const daily = ["2026-10-31", "2026-11-01"].map((date) => backfillDailyRow(date, yields));
    await writeBackfill(sandbox, backfillDoc(daily, [backfillCpiRow("2026-09")]));
    await writeTriple(sandbox, "2026-11-03", snapshotWithBenchmarks("2026-11-03", yields));
    const result = await runBuild(sandbox);
    assert.equal(result.code, 0, result.err);
    assert.doesNotMatch(result.err, /oldest backfilled/);
    const history = await readJson(sandbox, "history.json");
    assert.equal(history.daily.length, 3);
    const index = await readJson(sandbox, "index.json");
    assert.equal(index.history.daily_count, 3);
    assert.equal(index.history.trimmed_backfilled_count, 0);
  });

  it("trims exactly two oldest backfill rows at the real " + (CAP + 2) + " row CI shape", async () => {
    const yields = { "2Y": 3.28, "5Y": 3.51, "10Y": 3.78, "30Y": 4.11 };
    const dates = datesEnding("2026-10-30", CAP);
    const daily = dates.map((date) => backfillDailyRow(date, yields));
    await writeBackfill(sandbox, backfillDoc(daily, [backfillCpiRow("2026-09")]));
    const overlap = await writeTriple(sandbox, "2026-10-30", snapshotWithBenchmarks("2026-10-30", yields));
    const second = await writeTriple(sandbox, "2026-11-02", snapshotWithBenchmarks("2026-11-02", yields));
    const third = await writeTriple(sandbox, "2026-11-03", snapshotWithBenchmarks("2026-11-03", yields));
    const result = await runBuild(sandbox);
    assert.equal(result.code, 0, result.err);
    assert.match(
      result.err,
      new RegExp("trimmed 2 oldest backfilled daily row\\(s\\) to stay within the " + CAP + " cap")
    );
    const history = await readJson(sandbox, "history.json");
    assert.equal(history.daily.length, CAP);
    assert.equal(history.metadata.daily_count, CAP);
    assert.equal(history.daily[0].date, dates[2]);
    assert.ok(!history.daily.some((row) => row.date === dates[0]), "oldest backfill date dropped");
    assert.ok(!history.daily.some((row) => row.date === dates[1]), "second oldest backfill date dropped");
    const tail = history.daily.slice(-3);
    assert.deepEqual(
      tail.map((row) => row.date),
      ["2026-10-30", "2026-11-02", "2026-11-03"]
    );
    const expectedShas = [overlap.sha, second.sha, third.sha];
    for (let i = 0; i < tail.length; i++) {
      assert.equal(tail[i].verified, true, tail[i].date + " must stay verified");
      assert.equal(tail[i].source, "derived:history_verified_v1");
      assert.equal(tail[i].snapshot_sha256, expectedShas[i]);
    }
    assert.equal(history.daily.filter(isVerifiedRow).length, 3);
    assert.doesNotThrow(() => validateHistory(history));
    const index = await readJson(sandbox, "index.json");
    assert.equal(index.history.daily_count, CAP);
    assert.equal(index.history.trimmed_backfilled_count, 2);
    assert.deepEqual(index.dates, ["2026-10-30", "2026-11-02", "2026-11-03"]);
  });

  it("fails closed with no published output when verified rows alone exceed the cap", async () => {
    const yields = { "2Y": 3.28, "5Y": 3.51, "10Y": 3.78, "30Y": 4.11 };
    // The backfill dates must stay older than the oldest verified date.
    const verifiedDates = datesEnding("2026-11-03", CAP + 1);
    const backfillDates = ["2019-04-22", "2019-04-23"];
    const daily = backfillDates.map((date) => backfillDailyRow(date, yields));
    await writeBackfill(sandbox, backfillDoc(daily, [backfillCpiRow("2026-09")]));
    assert.equal(verifiedDates.length, CAP + 1);
    assert.ok(verifiedDates[0] > backfillDates[1], "backfill stays disjoint from the verified range");
    for (const date of verifiedDates) {
      await writeTriple(sandbox, date, snapshotWithBenchmarks(date, yields));
    }
    const result = await runBuild(sandbox);
    assert.notEqual(result.code, 0, "expected a nonzero exit, got 0 with stdout: " + result.out);
    assert.equal(result.code, 1);
    assert.match(
      result.err,
      new RegExp(
        "build-data: verified daily rows " +
          (CAP + 1) +
          " alone exceed the " +
          CAP +
          " cap: refusing to publish"
      )
    );
    assert.doesNotMatch(result.out, /published/);
    const entries = await readdir(sandbox.outDir).catch(() => null);
    if (entries === null) {
      assert.ok(true, "outDir was never created");
    } else {
      assert.deepEqual(entries, [], "no published output files may exist in outDir");
    }
  });
});
