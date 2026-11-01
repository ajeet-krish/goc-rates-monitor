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

let sandbox = null;

async function makeSandbox() {
  const root = await mkdtemp(join(tmpdir(), "goc-build-data-"));
  const webDir = join(root, "web");
  const scriptDir = join(webDir, "scripts");
  await mkdir(scriptDir, { recursive: true });
  const source = await readFile(BUILD_SCRIPT, "utf8");
  await writeFile(join(scriptDir, "build-data.mjs"), source, "utf8");
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
