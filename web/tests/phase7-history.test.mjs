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
import {
  validateHistory,
  validateIndex,
  ValidationError,
  MAX_HISTORY_DAILY,
  MAX_HISTORY_CPI,
} from "../src/lib/validate.ts";

const BUILD_SCRIPT = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "scripts",
  "build-data.mjs"
);

let sandbox = null;

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

function dailyRow(date, yields, spreadsStatus = "missing") {
  const slopes = {
    "2Y_5Y": (yields["5Y"] - yields["2Y"]) * 100,
    "2Y_10Y": (yields["10Y"] - yields["2Y"]) * 100,
    "5Y_30Y": (yields["30Y"] - yields["5Y"]) * 100,
    "10Y_30Y": (yields["30Y"] - yields["10Y"]) * 100,
  };
  const body = {
    calendar_gap: false,
    date,
    input_digest_sha256: null,
    slopes_bp: slopes,
    slopes_unit: "basis_points",
    snapshot_sha256: null,
    source: "derived:backfill_v1",
    spreads_bp: { "2Y": null, "5Y": null, "10Y": null, "30Y": null },
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

function cpiRow(month, trim = 0.2, median = 0.2) {
  const body = {
    median_component: "C01",
    median_mom_percent: median,
    median_yoy_percent: null,
    mom_unit: "percent_per_month",
    month,
    source: "derived:backfill_v1",
    trim_mom_percent: trim,
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
      asof: "2026-10-30",
      cpi_count: cpi.length,
      cpi_count_unit: "count",
      daily_count: daily.length,
      daily_count_unit: "count",
      method: "backfill_v1",
      retrieved_utc: "2026-10-31T00:00:00Z",
      schema_version: 1,
    },
    provenance: {},
    retrieved_utc: "2026-10-31T00:00:00Z",
  };
}

async function makeSandbox() {
  const root = await mkdtemp(join(tmpdir(), "goc-history-"));
  const webDir = join(root, "web");
  const scriptDir = join(webDir, "scripts");
  await mkdir(scriptDir, { recursive: true });
  for (const name of ["build-data.mjs", "history-overflow.mjs"]) {
    const source = await readFile(join(dirname(BUILD_SCRIPT), name), "utf8");
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

function minimalSnapshot(date) {
  return JSON.stringify({
    metadata: { snapshot_date: date, schema_version: 1 },
    observations: {},
    provenance: {
      valet: {
        source_url: "https://example.com/valet",
        retrieved_utc: "2026-10-31T00:00:00Z",
        vintage: date,
      },
    },
    warnings: [],
  });
}

async function writeTriple(sb, date, snapshotText) {
  const snapshot = snapshotText ?? minimalSnapshot(date);
  const sha = createHash("sha256").update(snapshot, "utf8").digest("hex");
  const dir = join(sb.snapshots, date);
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "snapshot.json"), snapshot, "utf8");
  await writeFile(
    join(dir, "manifest.json"),
    JSON.stringify({ files: { "snapshot.json": { sha256: sha } } }),
    "utf8"
  );
  await writeFile(join(dir, "verify.json"), JSON.stringify({ passed: true, snapshot_sha256: sha }), "utf8");
  return { sha };
}

async function writeBackfill(sb, doc, mutateManifest) {
  const text = canonicalText(doc);
  await mkdir(sb.historyDir, { recursive: true });
  await writeFile(join(sb.historyDir, "backfill.json"), text, "utf8");
  const sha = createHash("sha256").update(text, "utf8").digest("hex");
  let manifestSha = sha;
  if (mutateManifest) manifestSha = mutateManifest(sha);
  await writeFile(
    join(sb.historyDir, "backfill-manifest.json"),
    JSON.stringify({ files: { "backfill.json": { sha256: manifestSha, bytes_utf8: text.length } } }),
    "utf8"
  );
  return { sha, text };
}

function runBuild(sb) {
  return new Promise((resolve) => {
    execFile("node", [sb.script], (error, stdout, stderr) => {
      const code = error && typeof error.code === "number" ? error.code : error ? 1 : 0;
      resolve({ code, out: String(stdout), err: String(stderr) });
    });
  });
}

async function publishedHistory(sb) {
  try {
    await readFile(join(sb.outDir, "history.json"), "utf8");
    return true;
  } catch {
    return false;
  }
}

beforeEach(async () => {
  sandbox = await makeSandbox();
});

afterEach(async () => {
  if (sandbox) await rm(sandbox.root, { recursive: true, force: true });
  sandbox = null;
});

describe("build-data history merge fails closed", () => {
  it("publishes history.json and an index history entry on the happy path", async () => {
    await writeTriple(sandbox, "2026-10-30");
    const doc = backfillDoc(
      [
        dailyRow("2026-10-29", { "2Y": 3.3, "5Y": 3.5, "10Y": 3.8, "30Y": 4.1 }),
        dailyRow("2026-10-30", { "2Y": 3.28, "5Y": 3.51, "10Y": 3.78, "30Y": 4.11 }),
      ],
      [cpiRow("2026-08"), cpiRow("2026-09")]
    );
    await writeBackfill(sandbox, doc);
    const result = await runBuild(sandbox);
    assert.equal(result.code, 0);
    assert.equal(await publishedHistory(sandbox), true);
    const index = JSON.parse(await readFile(join(sandbox.outDir, "index.json"), "utf8"));
    assert.ok(index.history);
    assert.match(index.history.sha256, /^[0-9a-f]{64}$/);
    assert.equal(index.history.daily_count, 2);
    assert.equal(index.history.cpi_count, 2);
    const history = JSON.parse(await readFile(join(sandbox.outDir, "history.json"), "utf8"));
    assert.equal(history.daily.length, 2);
    assert.equal(history.metadata.method, "history_merge_v1");
  });

  it("fails on a tampered backfill manifest and publishes nothing", async () => {
    await writeTriple(sandbox, "2026-10-30");
    const doc = backfillDoc(
      [dailyRow("2026-10-30", { "2Y": 3.28, "5Y": 3.51, "10Y": 3.78, "30Y": 4.11 })],
      [cpiRow("2026-09")]
    );
    await writeBackfill(sandbox, doc, () => "0".repeat(64));
    const result = await runBuild(sandbox);
    assert.notEqual(result.code, 0);
    assert.match(result.err + result.out, /backfill manifest digest mismatch/);
    assert.equal(await publishedHistory(sandbox), false);
  });

  it("fails on a promoted row forgery with verified true in the backfill", async () => {
    await writeTriple(sandbox, "2026-10-30");
    const row = dailyRow("2026-10-30", { "2Y": 3.28, "5Y": 3.51, "10Y": 3.78, "30Y": 4.11 });
    row.verified = true;
    const { row_digest, ...body } = row;
    row.row_digest = digestOf(body);
    const doc = backfillDoc([row], [cpiRow("2026-09")]);
    await writeBackfill(sandbox, doc);
    const result = await runBuild(sandbox);
    assert.notEqual(result.code, 0);
    assert.match(result.err + result.out, /promoted-row forgery/);
    assert.equal(await publishedHistory(sandbox), false);
  });

  it("fails on an overlap conflict beyond 1.0 bp yields", async () => {
    const snapshot = JSON.stringify({
      metadata: { snapshot_date: "2026-10-30", schema_version: 1 },
      observations: {
        benchmarks: {
          "2Y": { valet_label: "2Y", valet: { value: 9.99, unit: "percent", quality: "observed", source_id: "valet:BD.CDN.2YR.DQ.YLD" } },
          "5Y": { valet_label: "5Y", valet: { value: 3.51, unit: "percent", quality: "observed", source_id: "valet:BD.CDN.5YR.DQ.YLD" } },
          "10Y": { valet_label: "10Y", valet: { value: 3.78, unit: "percent", quality: "observed", source_id: "valet:BD.CDN.10YR.DQ.YLD" } },
          "30Y": { valet_label: "30Y", valet: { value: 4.11, unit: "percent", quality: "observed", source_id: "valet:BD.CDN.LONG.DQ.YLD" } },
        },
        curve: { settlement_date: "2026-10-30" },
      },
      provenance: {
        valet: { source_url: "https://example.com/valet", retrieved_utc: "2026-10-31T00:00:00Z", vintage: "2026-10-30" },
      },
      warnings: [],
    });
    await writeTriple(sandbox, "2026-10-30", snapshot);
    const doc = backfillDoc(
      [dailyRow("2026-10-30", { "2Y": 3.28, "5Y": 3.51, "10Y": 3.78, "30Y": 4.11 })],
      [cpiRow("2026-09")]
    );
    await writeBackfill(sandbox, doc);
    const result = await runBuild(sandbox);
    assert.notEqual(result.code, 0);
    assert.match(result.err + result.out, /overlap conflict/);
    assert.equal(await publishedHistory(sandbox), false);
  });

  it("fails when the backfill artifact is absent", async () => {
    await writeTriple(sandbox, "2026-10-30");
    const result = await runBuild(sandbox);
    assert.notEqual(result.code, 0);
    assert.match(result.err + result.out, /missing history\/backfill/);
    assert.equal(await publishedHistory(sandbox), false);
  });

  it("never promotes snapshots whose verify report failed", async () => {
    const snapshot = JSON.stringify({
      metadata: { snapshot_date: "2026-10-30", schema_version: 1 },
      observations: {
        benchmarks: {
          "2Y": { valet_label: "2Y", valet: { value: 3.28, unit: "percent", quality: "observed", source_id: "valet:BD.CDN.2YR.DQ.YLD" } },
          "5Y": { valet_label: "5Y", valet: { value: 3.51, unit: "percent", quality: "observed", source_id: "valet:BD.CDN.5YR.DQ.YLD" } },
          "10Y": { valet_label: "10Y", valet: { value: 3.78, unit: "percent", quality: "observed", source_id: "valet:BD.CDN.10YR.DQ.YLD" } },
          "30Y": { valet_label: "30Y", valet: { value: 4.11, unit: "percent", quality: "observed", source_id: "valet:BD.CDN.LONG.DQ.YLD" } },
        },
      },
      provenance: {
        valet: { source_url: "https://example.com/valet", retrieved_utc: "2026-10-31T00:00:00Z", vintage: "2026-10-30" },
      },
      warnings: [],
    });
    await writeTriple(sandbox, "2026-10-30", snapshot);
    const verifyPath = join(sandbox.snapshots, "2026-10-30", "verify.json");
    const verifyDoc = JSON.parse(await readFile(verifyPath, "utf8"));
    verifyDoc.passed = false;
    await writeFile(verifyPath, JSON.stringify(verifyDoc), "utf8");
    const doc = backfillDoc(
      [dailyRow("2026-10-29", { "2Y": 3.3, "5Y": 3.5, "10Y": 3.8, "30Y": 4.1 })],
      [cpiRow("2026-09")]
    );
    await writeBackfill(sandbox, doc);
    const result = await runBuild(sandbox);
    assert.equal(result.code, 0);
    const history = JSON.parse(await readFile(join(sandbox.outDir, "history.json"), "utf8"));
    assert.equal(history.daily.length, 1);
    assert.equal(history.daily[0].date, "2026-10-29");
    assert.equal(history.daily[0].verified, false);
    const index = JSON.parse(await readFile(join(sandbox.outDir, "index.json"), "utf8"));
    assert.equal(index.entries["2026-10-30"].verify_passed, false);
  });

  it("fails closed on a gapped CPI month instead of compounding trailing rows", async () => {
    await writeTriple(sandbox, "2026-10-30");
    const doc = backfillDoc(
      [dailyRow("2026-10-29", { "2Y": 3.3, "5Y": 3.5, "10Y": 3.8, "30Y": 4.1 })],
      [cpiRow("2026-08"), cpiRow("2026-10")]
    );
    await writeBackfill(sandbox, doc);
    const result = await runBuild(sandbox);
    assert.notEqual(result.code, 0);
    assert.match(result.err + result.out, /consecutive calendar months|month gap/);
    assert.equal(await publishedHistory(sandbox), false);
  });

  it("recomputes verified CPI year over year from the merged monthly sequence", async () => {    const months = [];
    for (let i = 0; i < 11; i++) {
      months.push(cpiRow("2025-" + String(i + 1).padStart(2, "0"), 0.2, 0.2));
    }
    const snapshot = JSON.stringify({
      metadata: { snapshot_date: "2026-10-30", schema_version: 1 },
      observations: {
        benchmarks: {
          "2Y": { valet_label: "2Y", valet: { value: 3.28, unit: "percent", quality: "observed", source_id: "valet:BD.CDN.2YR.DQ.YLD" } },
          "5Y": { valet_label: "5Y", valet: { value: 3.51, unit: "percent", quality: "observed", source_id: "valet:BD.CDN.5YR.DQ.YLD" } },
          "10Y": { valet_label: "10Y", valet: { value: 3.78, unit: "percent", quality: "observed", source_id: "valet:BD.CDN.10YR.DQ.YLD" } },
          "30Y": { valet_label: "30Y", valet: { value: 4.11, unit: "percent", quality: "observed", source_id: "valet:BD.CDN.LONG.DQ.YLD" } },
        },
        curve: { settlement_date: "2026-10-30" },
        inflation: {
          history: [
            {
              month: "2025-12",
              trim_mom_percent: 0.2,
              median_mom_percent: 0.2,
              median_component: "C01",
              trim_yoy_percent: null,
              median_yoy_percent: null,
            },
          ],
        },
      },
      provenance: {
        valet: { source_url: "https://example.com/valet", retrieved_utc: "2026-10-31T00:00:00Z", vintage: "2026-10-30" },
      },
      warnings: [],
    });
    await writeTriple(sandbox, "2026-10-30", snapshot);
    const doc = backfillDoc(
      [dailyRow("2026-10-29", { "2Y": 3.3, "5Y": 3.5, "10Y": 3.8, "30Y": 4.1 })],
      months
    );
    await writeBackfill(sandbox, doc);
    const result = await runBuild(sandbox);
    assert.equal(result.code, 0);
    const history = JSON.parse(await readFile(join(sandbox.outDir, "history.json"), "utf8"));
    assert.equal(history.cpi.length, 12);
    const last = history.cpi[11];
    assert.equal(last.month, "2025-12");
    assert.equal(last.verified, true);
    let factor = 1;
    for (let i = 0; i < 12; i++) factor *= 1 + 0.2 / 100;
    const expected = (factor - 1) * 100;
    assert.ok(Math.abs(last.trim_yoy_percent - expected) < 0.01 + 1e-9);
    assert.ok(Math.abs(last.median_yoy_percent - expected) < 0.01 + 1e-9);
    assert.doesNotThrow(() => validateHistory(history));
  });
});

function validHistoryDoc() {
  const vBody = {
    calendar_gap: false,
    date: "2026-10-30",
    input_digest_sha256: null,
    slopes_bp: { "2Y_5Y": 23.0, "2Y_10Y": 50.0, "5Y_30Y": 60.0, "10Y_30Y": 33.0 },
    slopes_unit: "basis_points",
    snapshot_sha256: "a".repeat(64),
    source: "derived:history_verified_v1",
    spreads_bp: { "2Y": null, "5Y": null, "10Y": null, "30Y": null },
    spreads_status: "missing",
    spreads_unit: "basis_points",
    switch_by_tenor: { "2Y": false, "5Y": false, "10Y": false, "30Y": false },
    switch_in_window: false,
    verified: true,
    yields_percent: { "2Y": 3.28, "5Y": 3.51, "10Y": 3.78, "30Y": 4.11 },
    yields_unit: "percent",
  };
  const verified = { ...vBody, row_digest: digestOf(vBody) };
  const backfilled = dailyRow("2026-10-29", { "2Y": 3.3, "5Y": 3.5, "10Y": 3.8, "30Y": 4.1 });
  const cpi = [cpiRow("2026-08"), cpiRow("2026-09")];
  const doc = {
    cpi,
    daily: [backfilled, verified],
    exclusions: [],
    metadata: {
      asof: "2026-10-30",
      cpi_count: 2,
      cpi_count_unit: "count",
      daily_count: 2,
      daily_count_unit: "count",
      method: "history_merge_v1",
      schema_version: 1,
    },
    provenance: {},
  };
  doc.daily.sort((a, b) => (a.date < b.date ? -1 : 1));
  return doc;
}

describe("validateHistory closed sets and recompute", () => {
  it("accepts a valid merged history", () => {
    assert.doesNotThrow(() => validateHistory(validHistoryDoc()));
  });

  it("rejects slopes that do not recompute within 1.0 bp", () => {
    const doc = validHistoryDoc();
    doc.daily[1].slopes_bp["2Y_10Y"] += 5.0;
    const { row_digest, ...body } = doc.daily[1];
    doc.daily[1].row_digest = digestOf(body);
    assert.throws(() => validateHistory(doc), /recompute.*within 1.0 bp/);
  });

  it("rejects non monotonic daily dates", () => {
    const doc = validHistoryDoc();
    doc.daily = [doc.daily[1], doc.daily[0]];
    assert.throws(() => validateHistory(doc), /strictly increasing/);
  });

  it("rejects an unknown history source", () => {
    const doc = validHistoryDoc();
    doc.daily[0].source = "evil:backfill";
    const { row_digest, ...body } = doc.daily[0];
    doc.daily[0].row_digest = digestOf(body);
    assert.throws(() => validateHistory(doc), /one of/);
  });

  it("rejects gapped CPI months instead of compounding trailing rows", () => {
    const months = [];
    for (let i = 0; i < 11; i++) {
      const month = "2025-" + String(i + 1).padStart(2, "0");
      months.push(cpiRow(month, 0.2, 0.2));
    }
    months.push(cpiRow("2026-01", 0.2, 0.2));
    const doc = validHistoryDoc();
    doc.cpi = months;
    doc.metadata.cpi_count = 12;
    assert.throws(() => validateHistory(doc), /consecutive calendar months/);
  });

  it("rejects CPI year over year that does not compound within 0.01", () => {    const months = [];
    for (let i = 0; i < 12; i++) {
      const month = "2025-" + String(i + 1).padStart(2, "0");
      months.push(cpiRow(month, 0.2, 0.2));
    }
    let factor = 1;
    for (let i = 0; i < 12; i++) factor *= 1 + 0.2 / 100;
    const yoy = (factor - 1) * 100;
    months[11].trim_yoy_percent = yoy + 5.0;
    months[11].median_yoy_percent = yoy;
    const { row_digest, ...body } = months[11];
    months[11].row_digest = digestOf(body);
    const doc = validHistoryDoc();
    doc.cpi = months;
    doc.metadata.cpi_count = 12;
    assert.throws(() => validateHistory(doc), /compound the trailing 12/);
  });

  it("pins history caps", () => {
    assert.equal(MAX_HISTORY_DAILY, 2750);
    assert.equal(MAX_HISTORY_CPI, 60);
  });

  it("accepts an index with a history entry and rejects a bad sha", () => {
    const index = {
      generated_utc: "2026-10-31T00:00:00Z",
      dates: [],
      latest: null,
      entries: {},
      history: {
        sha256: "b".repeat(64),
        bytes_utf8: 10,
        daily_count: 2,
        cpi_count: 2,
        trimmed_backfilled_count: 0,
      },
    };
    assert.doesNotThrow(() => validateIndex(index));
    index.history.sha256 = "short";
    assert.throws(() => validateIndex(index), ValidationError);
  });
});
