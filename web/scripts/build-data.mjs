import { createHash } from "node:crypto";
import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..", "..");
const webDir = join(here, "..");
const snapshotsDir = join(repoRoot, "snapshots");
const outDir = join(webDir, "public", "data");

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const SHA256_HEX_RE = /^[0-9a-f]{64}$/;

function sha256HexBytes(raw) {
  return createHash("sha256").update(raw).digest("hex");
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

function fail(message) {
  console.error("build-data: " + message);
  process.exit(1);
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
    staged.push({ date, snapshotText, verifyText: JSON.stringify(verifyDoc), digest, verifyPassed: verifyDoc.passed });
  }

  // Phase 2: publish only after every date validated.
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
  // Prune stale dates removed from snapshots so old output is not republished.
  if (await exists(outDir)) {
    const outEntries = await fs.readdir(outDir);
    const live = new Set([...published, "index.json", ".gitkeep"]);
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
  };
  await fs.writeFile(join(outDir, "index.json"), JSON.stringify(indexDoc, null, 2) + "\n", "utf8");
  console.log("build-data: published " + published.length + " date(s) to public/data");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
