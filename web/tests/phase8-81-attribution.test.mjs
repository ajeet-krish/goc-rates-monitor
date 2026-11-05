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
import { validateHistory } from "../src/lib/validate.ts";

const scriptsDir = join(dirname(fileURLToPath(import.meta.url)), "..", "scripts");

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
  if (typeof value === "object") {
    const keys = Object.keys(value).sort();
    if (keys.length === 0) return "{}";
    const parts = keys.map(
      (key) => " ".repeat(indent + 2) + JSON.stringify(key) + ": " + canonicalValue(value[key], indent + 2)
    );
    return "{\n" + parts.join(",\n") + "\n" + " ".repeat(indent) + "}";
  }
  throw new Error("unsupported canonical value type " + typeof value);
}

function canonicalText(payload) {
  return canonicalValue(payload, 0) + "\n";
}

function digestOf(body) {
  return createHash("sha256").update(canonicalText(body), "utf8").digest("hex");
}

const BASE_YIELDS = { "2Y": 3.28, "5Y": 3.51, "10Y": 3.78, "30Y": 4.11 };

function dailyRow(date, yields, spreads) {
  const spreadsBp = { "2Y": null, "5Y": null, "10Y": null, "30Y": null };
  let spreadsStatus = "missing";
  if (spreads !== undefined) {
    spreadsStatus = spreads.status;
    for (const [tenor, value] of Object.entries(spreads.values)) {
      spreadsBp[tenor] = value;
    }
  }
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
    spreads_bp: spreadsBp,
    spreads_status: spreadsStatus,
    spreads_unit: "basis_points",
    switch_by_tenor: { "2Y": false, "5Y": false, "10Y": false, "30Y": false },
    switch_in_window: false,
    verified: false,
    yields_percent: yields,
    yields_unit: "percent",
  };
  return { ...body, row_digest: digestOf(body) };
}

function cpiRow(month) {
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

/**
 * Snapshot with benchmark yields. The settlement argument is the
 * curve.settlement_date value: a string sets it, null publishes a null
 * settlement, and undefined omits the curve section entirely. The optional
 * spreads argument is placed verbatim at observations.spreads.
 */
function benchmarkSnapshot(labelDate, yields, settlement, spreads) {
  const observations = {
    benchmarks: {
      "2Y": { valet_label: "2Y", valet: { value: yields["2Y"], unit: "percent", quality: "observed", source_id: "valet:BD.CDN.2YR.DQ.YLD" } },
      "5Y": { valet_label: "5Y", valet: { value: yields["5Y"], unit: "percent", quality: "observed", source_id: "valet:BD.CDN.5YR.DQ.YLD" } },
      "10Y": { valet_label: "10Y", valet: { value: yields["10Y"], unit: "percent", quality: "observed", source_id: "valet:BD.CDN.10YR.DQ.YLD" } },
      "30Y": { valet_label: "30Y", valet: { value: yields["30Y"], unit: "percent", quality: "observed", source_id: "valet:BD.CDN.LONG.DQ.YLD" } },
    },
  };
  if (settlement !== undefined) {
    observations.curve = { settlement_date: settlement };
  }
  if (spreads !== undefined) {
    observations.spreads = spreads;
  }
  return JSON.stringify({
    metadata: { snapshot_date: labelDate, schema_version: 1 },
    observations,
    provenance: {
      valet: {
        source_url: "https://example.com/valet",
        retrieved_utc: "2026-11-04T00:00:00Z",
        vintage: labelDate,
      },
    },
    warnings: [],
  });
}

/** Sparse snapshot shape: no benchmark yields at all, so history skips it. */
function sparseSnapshot(labelDate) {
  return JSON.stringify({
    metadata: { snapshot_date: labelDate, schema_version: 1 },
    observations: {},
    provenance: {
      valet: {
        source_url: "https://example.com/valet",
        retrieved_utc: "2026-11-04T00:00:00Z",
        vintage: labelDate,
      },
    },
    warnings: [],
  });
}

async function makeSandbox() {
  const root = await mkdtemp(join(tmpdir(), "goc-attribution-"));
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
  const snapshot = snapshotText ?? sparseSnapshot(date);
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

async function publishedDates(sb) {
  try {
    const entries = await readdir(sb.outDir);
    return entries.filter((name) => /^\d{4}-\d{2}-\d{2}$/.test(name)).sort();
  } catch {
    return [];
  }
}

let sandbox = null;

beforeEach(async () => {
  sandbox = await makeSandbox();
});

afterEach(async () => {
  if (sandbox) await rm(sandbox.root, { recursive: true, force: true });
  sandbox = null;
});

describe("build-data dates verified rows by the Valet print date", () => {
  it("merges a stale snapshot under its settlement date and warns", async () => {
    await writeBackfill(
      sandbox,
      backfillDoc(
        [
          dailyRow("2026-10-30", BASE_YIELDS),
          dailyRow("2026-11-01", BASE_YIELDS),
        ],
        [cpiRow("2026-09")]
      )
    );
    const stale = await writeTriple(
      sandbox,
      "2026-11-02",
      benchmarkSnapshot("2026-11-02", BASE_YIELDS, "2026-11-01")
    );
    const result = await runBuild(sandbox);
    assert.equal(result.code, 0, result.err);
    assert.match(result.err, /2026-11-02/);
    assert.match(result.err, /2026-11-01/);
    assert.match(result.err, /settles on 2026-11-01/);
    const history = await readJson(sandbox, "history.json");
    assert.deepEqual(
      history.daily.map((row) => row.date),
      ["2026-10-30", "2026-11-01"]
    );
    const merged = history.daily[1];
    assert.equal(merged.verified, true);
    assert.equal(merged.source, "derived:history_verified_v1");
    assert.equal(merged.snapshot_sha256, stale.sha);
    assert.equal(merged.yields_percent["2Y"], BASE_YIELDS["2Y"]);
    assert.doesNotThrow(() => validateHistory(history));
    const index = await readJson(sandbox, "index.json");
    assert.deepEqual(index.dates, ["2026-11-02"]);
    assert.ok(index.entries["2026-11-02"], "index stays keyed by the snapshot label");
    assert.equal(index.entries["2026-11-02"].snapshot_sha256, stale.sha);
  });

  it("fails closed when a stale snapshot disagrees with the settlement date row beyond 1.0 bp", async () => {
    await writeBackfill(
      sandbox,
      backfillDoc([dailyRow("2026-11-01", BASE_YIELDS)], [cpiRow("2026-09")])
    );
    const drifted = { ...BASE_YIELDS, "2Y": 9.99 };
    await writeTriple(
      sandbox,
      "2026-11-02",
      benchmarkSnapshot("2026-11-02", drifted, "2026-11-01")
    );
    const result = await runBuild(sandbox);
    assert.equal(result.code, 1);
    assert.match(result.err, /history overlap conflict on 2026-11-01 tenor 2Y/);
    assert.match(result.err, /refusing to publish/);
    assert.deepEqual(await publishedDates(sandbox), []);
  });

  it("fails closed when settlement_date is later than the snapshot label", async () => {
    await writeBackfill(
      sandbox,
      backfillDoc([dailyRow("2026-10-30", BASE_YIELDS)], [cpiRow("2026-09")])
    );
    await writeTriple(
      sandbox,
      "2026-11-01",
      benchmarkSnapshot("2026-11-01", BASE_YIELDS, "2026-11-02")
    );
    const result = await runBuild(sandbox);
    assert.equal(result.code, 1);
    assert.match(result.err, /curve\.settlement_date 2026-11-02 later than the snapshot date/);
    assert.match(result.err, /refusing to publish/);
    assert.deepEqual(await publishedDates(sandbox), []);
  });

  it("fails closed when a snapshot with yields has no usable settlement_date", async () => {
    await writeBackfill(
      sandbox,
      backfillDoc([dailyRow("2026-10-30", BASE_YIELDS)], [cpiRow("2026-09")])
    );
    await writeTriple(
      sandbox,
      "2026-11-02",
      benchmarkSnapshot("2026-11-02", BASE_YIELDS, null)
    );
    const result = await runBuild(sandbox);
    assert.equal(result.code, 1);
    assert.match(result.err, /curve\.settlement_date null: refusing to publish/);
    assert.deepEqual(await publishedDates(sandbox), []);
  });

  it("keeps skipping snapshots that publish no benchmark yields at all", async () => {
    await writeBackfill(
      sandbox,
      backfillDoc([dailyRow("2026-10-30", BASE_YIELDS)], [cpiRow("2026-09")])
    );
    await writeTriple(sandbox, "2026-11-02", sparseSnapshot("2026-11-02"));
    const result = await runBuild(sandbox);
    assert.equal(result.code, 0, result.err);
    const history = await readJson(sandbox, "history.json");
    assert.deepEqual(
      history.daily.map((row) => row.date),
      ["2026-10-30"]
    );
    assert.equal(history.daily[0].verified, false);
  });

  it("fails closed when two snapshots share a print date with conflicting yields", async () => {
    await writeBackfill(
      sandbox,
      backfillDoc([dailyRow("2026-10-30", BASE_YIELDS)], [cpiRow("2026-09")])
    );
    await writeTriple(
      sandbox,
      "2026-10-30",
      benchmarkSnapshot("2026-10-30", BASE_YIELDS, "2026-10-30")
    );
    const drifted = { ...BASE_YIELDS, "2Y": 9.99 };
    await writeTriple(
      sandbox,
      "2026-11-02",
      benchmarkSnapshot("2026-11-02", drifted, "2026-10-30")
    );
    const result = await runBuild(sandbox);
    assert.equal(result.code, 1);
    assert.match(result.err, /history overlap conflict on 2026-10-30 tenor 2Y/);
    assert.match(result.err, /refusing to publish/);
    assert.deepEqual(await publishedDates(sandbox), []);
  });

  it("keeps the first snapshot row when a later snapshot agrees on the shared print date", async () => {
    await writeBackfill(
      sandbox,
      backfillDoc([dailyRow("2026-10-30", BASE_YIELDS)], [cpiRow("2026-09")])
    );
    const first = await writeTriple(
      sandbox,
      "2026-10-30",
      benchmarkSnapshot("2026-10-30", BASE_YIELDS, "2026-10-30")
    );
    const agreed = { ...BASE_YIELDS, "2Y": 3.285 };
    const second = await writeTriple(
      sandbox,
      "2026-11-02",
      benchmarkSnapshot("2026-11-02", agreed, "2026-10-30")
    );
    const result = await runBuild(sandbox);
    assert.equal(result.code, 0, result.err);
    assert.match(result.err, /shares print date 2026-10-30/);
    const history = await readJson(sandbox, "history.json");
    assert.deepEqual(
      history.daily.map((row) => row.date),
      ["2026-10-30"]
    );
    const merged = history.daily[0];
    assert.equal(merged.verified, true);
    assert.equal(merged.snapshot_sha256, first.sha);
    assert.notEqual(merged.snapshot_sha256, second.sha);
    assert.equal(merged.yields_percent["2Y"], BASE_YIELDS["2Y"]);
    assert.doesNotThrow(() => validateHistory(history));
    const index = await readJson(sandbox, "index.json");
    assert.deepEqual(index.dates, ["2026-10-30", "2026-11-02"]);
    assert.equal(index.entries["2026-10-30"].snapshot_sha256, first.sha);
    assert.equal(index.entries["2026-11-02"].snapshot_sha256, second.sha);
  });

  it("behaves exactly as before when settlement equals the snapshot label", async () => {
    await writeBackfill(
      sandbox,
      backfillDoc(
        [
          dailyRow("2026-10-30", BASE_YIELDS),
          dailyRow("2026-11-01", BASE_YIELDS),
        ],
        [cpiRow("2026-09")]
      )
    );
    const current = await writeTriple(
      sandbox,
      "2026-11-02",
      benchmarkSnapshot("2026-11-02", BASE_YIELDS, "2026-11-02")
    );
    const result = await runBuild(sandbox);
    assert.equal(result.code, 0, result.err);
    assert.doesNotMatch(result.err, /settles on/);
    assert.doesNotMatch(result.err, /shares print date/);
    const history = await readJson(sandbox, "history.json");
    assert.deepEqual(
      history.daily.map((row) => row.date),
      ["2026-10-30", "2026-11-01", "2026-11-02"]
    );
    const merged = history.daily[2];
    assert.equal(merged.verified, true);
    assert.equal(merged.snapshot_sha256, current.sha);
    assert.doesNotThrow(() => validateHistory(history));
    const index = await readJson(sandbox, "index.json");
    assert.deepEqual(index.dates, ["2026-11-02"]);
  });
});

/** Benchmark snapshot that also carries one inflation history row. */
function cpiSnapshot(labelDate, month, trim, settlement) {
  const doc = JSON.parse(benchmarkSnapshot(labelDate, BASE_YIELDS, settlement));
  doc.observations.inflation = {
    history: [
      {
        month,
        trim_mom_percent: trim,
        median_mom_percent: 0.2,
        median_component: "C01",
        trim_yoy_percent: null,
        median_yoy_percent: null,
      },
    ],
  };
  return JSON.stringify(doc);
}

const FULL_SPREAD_RECORDS = [
  { tenor: "2Y", spread_bp: -128 },
  { tenor: "5Y", spread_bp: -120 },
  { tenor: "10Y", spread_bp: -116 },
  { tenor: "30Y", spread_bp: -120 },
];

const FULL_SPREAD_VALUES = { "2Y": -128, "5Y": -120, "10Y": -116, "30Y": -120 };

describe("build-data spreads mapping, overlap arbitration, and print window", () => {
  it("maps an ok spreads section with fewer than four tenor records to partial", async () => {
    await writeBackfill(
      sandbox,
      backfillDoc([dailyRow("2026-10-30", BASE_YIELDS)], [cpiRow("2026-09")])
    );
    const twoRecords = {
      status: "ok",
      records: [FULL_SPREAD_RECORDS[0], FULL_SPREAD_RECORDS[1]],
    };
    await writeTriple(
      sandbox,
      "2026-11-02",
      benchmarkSnapshot("2026-11-02", BASE_YIELDS, "2026-11-02", twoRecords)
    );
    const result = await runBuild(sandbox);
    assert.equal(result.code, 0, result.err);
    const history = await readJson(sandbox, "history.json");
    const merged = history.daily.find((row) => row.date === "2026-11-02");
    assert.equal(merged.spreads_status, "partial");
    assert.equal(typeof merged.spreads_bp["2Y"], "number");
    assert.equal(typeof merged.spreads_bp["5Y"], "number");
    assert.equal(merged.spreads_bp["10Y"], null);
    assert.equal(merged.spreads_bp["30Y"], null);
    assert.doesNotThrow(() => validateHistory(history));
  });

  it("keeps ok status for four tenor records and merges over a spreadless backfill row", async () => {
    await writeBackfill(
      sandbox,
      backfillDoc([dailyRow("2026-11-02", BASE_YIELDS)], [cpiRow("2026-09")])
    );
    const triple = await writeTriple(
      sandbox,
      "2026-11-04",
      benchmarkSnapshot("2026-11-04", BASE_YIELDS, "2026-11-02", {
        status: "ok",
        records: FULL_SPREAD_RECORDS,
      })
    );
    const result = await runBuild(sandbox);
    assert.equal(result.code, 0, result.err);
    const history = await readJson(sandbox, "history.json");
    const merged = history.daily.find((row) => row.date === "2026-11-02");
    assert.equal(merged.verified, true);
    assert.equal(merged.spreads_status, "ok");
    assert.equal(merged.snapshot_sha256, triple.sha);
    for (const tenor of ["2Y", "5Y", "10Y", "30Y"]) {
      assert.equal(typeof merged.spreads_bp[tenor], "number");
    }
    assert.doesNotThrow(() => validateHistory(history));
  });

  it("fails closed when settlement_date falls before the sealed backfill print window", async () => {
    await writeBackfill(
      sandbox,
      backfillDoc([dailyRow("2026-10-30", BASE_YIELDS)], [cpiRow("2026-09")])
    );
    await writeTriple(
      sandbox,
      "2026-11-02",
      benchmarkSnapshot("2026-11-02", BASE_YIELDS, "0001-01-01")
    );
    const result = await runBuild(sandbox);
    assert.equal(result.code, 1);
    assert.match(result.err, /curve\.settlement_date 0001-01-01/);
    assert.match(result.err, /sealed backfill print window start 2026-10-23/);
    assert.match(result.err, /refusing to publish/);
    assert.deepEqual(await publishedDates(sandbox), []);
  });

  it("fails closed when an overlapping snapshot disagrees on a spread beyond 1.0 bp", async () => {
    await writeBackfill(
      sandbox,
      backfillDoc(
        [dailyRow("2026-11-02", BASE_YIELDS, { status: "ok", values: FULL_SPREAD_VALUES })],
        [cpiRow("2026-09")]
      )
    );
    const drifted = [
      { tenor: "2Y", spread_bp: -123 },
      FULL_SPREAD_RECORDS[1],
      FULL_SPREAD_RECORDS[2],
      FULL_SPREAD_RECORDS[3],
    ];
    await writeTriple(
      sandbox,
      "2026-11-04",
      benchmarkSnapshot("2026-11-04", BASE_YIELDS, "2026-11-02", {
        status: "ok",
        records: drifted,
      })
    );
    const result = await runBuild(sandbox);
    assert.equal(result.code, 1);
    assert.match(result.err, /spread tenor 2Y beyond 1\.0 bp/);
    assert.match(result.err, /refusing to publish/);
    assert.deepEqual(await publishedDates(sandbox), []);
  });

  it("fails closed when overlapping rows carry different spreads_status", async () => {
    await writeBackfill(
      sandbox,
      backfillDoc(
        [dailyRow("2026-11-02", BASE_YIELDS, { status: "ok", values: FULL_SPREAD_VALUES })],
        [cpiRow("2026-09")]
      )
    );
    await writeTriple(
      sandbox,
      "2026-11-04",
      benchmarkSnapshot("2026-11-04", BASE_YIELDS, "2026-11-02", {
        status: "ok",
        records: [FULL_SPREAD_RECORDS[0]],
      })
    );
    const result = await runBuild(sandbox);
    assert.equal(result.code, 1);
    assert.match(result.err, /spreads_status ok versus snapshot partial/);
    assert.match(result.err, /refusing to publish/);
    assert.deepEqual(await publishedDates(sandbox), []);
  });

  it("keeps the first verified CPI writer for a shared month after the agreement check", async () => {
    await writeBackfill(
      sandbox,
      backfillDoc([dailyRow("2026-10-29", BASE_YIELDS)], [cpiRow("2026-08")])
    );
    const first = await writeTriple(
      sandbox,
      "2026-10-30",
      cpiSnapshot("2026-10-30", "2026-09", 0.2, "2026-10-30")
    );
    const second = await writeTriple(
      sandbox,
      "2026-11-02",
      cpiSnapshot("2026-11-02", "2026-09", 0.205, "2026-11-02")
    );
    const result = await runBuild(sandbox);
    assert.equal(result.code, 0, result.err);
    const history = await readJson(sandbox, "history.json");
    assert.deepEqual(
      history.cpi.map((row) => row.month),
      ["2026-08", "2026-09"]
    );
    const shared = history.cpi[1];
    assert.equal(shared.verified, true);
    assert.equal(shared.trim_mom_percent, 0.2);
    assert.equal(shared.snapshot_sha256, first.sha);
    assert.notEqual(shared.snapshot_sha256, second.sha);
    assert.doesNotThrow(() => validateHistory(history));
  });

  it("fails closed when backfill provenance nests past the depth cap", async () => {
    const doc = backfillDoc([dailyRow("2026-10-30", BASE_YIELDS)], [cpiRow("2026-09")]);
    doc.provenance = { level1: { level2: { level3: { level4: "too deep" } } } };
    await writeBackfill(sandbox, doc);
    const result = await runBuild(sandbox);
    assert.equal(result.code, 1);
    assert.match(result.err, /backfill\.json provenance/);
    assert.match(result.err, /depth cap/);
    assert.deepEqual(await publishedDates(sandbox), []);
  });
});
