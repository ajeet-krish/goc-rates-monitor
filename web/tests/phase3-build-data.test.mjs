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

const BUILD_SCRIPT = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "scripts",
  "build-data.mjs"
);

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

function historyDailyRow(date) {
  const yields = { "2Y": 3.28, "5Y": 3.51, "10Y": 3.78, "30Y": 4.11 };
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

function historyCpiRow(month) {
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

async function stageMinimalHistory(sb) {
  const doc = {
    cpi: [historyCpiRow("2026-09")],
    daily: [historyDailyRow("2026-10-30")],
    exclusions: [],
    metadata: {
      asof: "2026-10-30",
      cpi_count: 1,
      cpi_count_unit: "count",
      daily_count: 1,
      daily_count_unit: "count",
      method: "backfill_v1",
      retrieved_utc: "2026-10-31T00:00:00Z",
      schema_version: 1,
    },
    provenance: {},
    retrieved_utc: "2026-10-31T00:00:00Z",
  };
  const text = canonicalText(doc);
  const sha = createHash("sha256").update(text, "utf8").digest("hex");
  await mkdir(join(sb.root, "history"), { recursive: true });
  await writeFile(join(sb.root, "history", "backfill.json"), text, "utf8");
  await writeFile(
    join(sb.root, "history", "backfill-manifest.json"),
    JSON.stringify({ files: { "backfill.json": { sha256: sha, bytes_utf8: text.length } } }),
    "utf8"
  );
}

let sandbox = null;

async function makeSandbox() {
  const root = await mkdtemp(join(tmpdir(), "goc-build-data-"));
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

async function writeTriple(sb, date, mutate) {
  const snapshot = minimalSnapshot(date);
  const sha = createHash("sha256").update(snapshot, "utf8").digest("hex");
  let outSnapshot = snapshot;
  let outManifest = JSON.stringify({
    files: { "snapshot.json": { sha256: sha } },
  });
  let outVerify = JSON.stringify({ passed: true, snapshot_sha256: sha });
  if (mutate) {
    const next = mutate({ snapshot, sha });
    if (next.snapshot !== undefined) outSnapshot = next.snapshot;
    if (next.manifest !== undefined) outManifest = next.manifest;
    if (next.verify !== undefined) outVerify = next.verify;
  }
  const dir = join(sb.snapshots, date);
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "snapshot.json"), outSnapshot, "utf8");
  await writeFile(join(dir, "manifest.json"), outManifest, "utf8");
  await writeFile(join(dir, "verify.json"), outVerify, "utf8");
  return { sha };
}

function runBuild(sb) {
  return new Promise((resolve) => {
    execFile("node", [sb.script], (error, stdout, stderr) => {
      const code =
        error && typeof error.code === "number" ? error.code : error ? 1 : 0;
      resolve({ code, out: String(stdout), err: String(stderr) });
    });
  });
}

async function publishedDates(sb) {
  try {
    const entries = await readdir(sb.outDir);
    return entries.filter((name) => /^\d{4}-\d{2}-\d{2}$/.test(name)).sort();
  } catch {
    return [];
  }
}

beforeEach(async () => {
  sandbox = await makeSandbox();
});

afterEach(async () => {
  if (sandbox) await rm(sandbox.root, { recursive: true, force: true });
  sandbox = null;
});

describe("build-data tamper and refusal behavior", () => {
  it("publishes a valid triple to public data with an index", async () => {
    await writeTriple(sandbox, "2026-10-30");
    await stageMinimalHistory(sandbox);
    const result = await runBuild(sandbox);
    assert.equal(result.code, 0);
    assert.deepEqual(await publishedDates(sandbox), ["2026-10-30"]);
    const index = JSON.parse(
      await readFile(join(sandbox.outDir, "index.json"), "utf8")
    );
    assert.deepEqual(index.dates, ["2026-10-30"]);
    assert.equal(index.latest, "2026-10-30");
  });

  it("fails on a tampered snapshot and publishes nothing", async () => {
    await writeTriple(sandbox, "2026-10-30", ({ snapshot, sha }) => ({
      snapshot: snapshot + " ",
      manifest: JSON.stringify({
        files: { "snapshot.json": { sha256: sha } },
      }),
    }));
    const result = await runBuild(sandbox);
    assert.notEqual(result.code, 0);
    assert.match(result.err + result.out, /digest mismatch/);
    assert.deepEqual(await publishedDates(sandbox), []);
  });

  it("fails on a verify digest mismatch and publishes nothing", async () => {
    await writeTriple(sandbox, "2026-10-30", () => ({
      verify: JSON.stringify({
        passed: true,
        snapshot_sha256: "0".repeat(64),
      }),
    }));
    const result = await runBuild(sandbox);
    assert.notEqual(result.code, 0);
    assert.match(result.err + result.out, /snapshot_sha256 mismatch/);
    assert.deepEqual(await publishedDates(sandbox), []);
  });

  it("fails when the manifest is missing and publishes nothing", async () => {
    const date = "2026-10-30";
    const snapshot = minimalSnapshot(date);
    const dir = join(sandbox.snapshots, date);
    await mkdir(dir, { recursive: true });
    await writeFile(join(dir, "snapshot.json"), snapshot, "utf8");
    const sha = createHash("sha256").update(snapshot, "utf8").digest("hex");
    await writeFile(
      join(dir, "verify.json"),
      JSON.stringify({ passed: true, snapshot_sha256: sha }),
      "utf8"
    );
    const result = await runBuild(sandbox);
    assert.notEqual(result.code, 0);
    assert.match(result.err + result.out, /missing manifest/);
    assert.deepEqual(await publishedDates(sandbox), []);
  });

  it("ignores malformed directory names instead of publishing them", async () => {
    await writeTriple(sandbox, "2026-10-30");
    await stageMinimalHistory(sandbox);
    for (const bad of ["latest", "2026-13-99", "notes.txt", "2026-02-30"]) {
      await mkdir(join(sandbox.snapshots, bad), { recursive: true });
      await writeFile(
        join(sandbox.snapshots, bad, "snapshot.json"),
        "{}",
        "utf8"
      );
    }
    const result = await runBuild(sandbox);
    assert.equal(result.code, 0);
    assert.deepEqual(await publishedDates(sandbox), ["2026-10-30"]);
  });

  it("prunes stale published dates removed from snapshots", async () => {
    await writeTriple(sandbox, "2026-10-29");
    await writeTriple(sandbox, "2026-10-30");
    await stageMinimalHistory(sandbox);
    let result = await runBuild(sandbox);
    assert.equal(result.code, 0);
    assert.deepEqual(await publishedDates(sandbox), [
      "2026-10-29",
      "2026-10-30",
    ]);
    await rm(join(sandbox.snapshots, "2026-10-29"), {
      recursive: true,
      force: true,
    });
    result = await runBuild(sandbox);
    assert.equal(result.code, 0);
    assert.deepEqual(await publishedDates(sandbox), ["2026-10-30"]);
    assert.match(result.out, /pruned stale date 2026-10-29/);
  });
});
