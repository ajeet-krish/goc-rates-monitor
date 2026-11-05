import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  validateHistory,
  validateSnapshot,
  validateVerify,
  MAX_HISTORY_DAILY,
  MAX_HISTORY_CPI,
  MAX_HISTORY_OBS,
} from "../src/lib/validate.ts";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = join(here, "..");
const repoRoot = join(webRoot, "..");

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

const backfill = readJson(join(repoRoot, "history", "backfill.json"));
const historyPath = join(webRoot, "public", "data", "history.json");
const historyRaw = readFileSync(historyPath);
const history = JSON.parse(historyRaw.toString("utf8"));
const index = readJson(join(webRoot, "public", "data", "index.json"));

// The four re-sealed snapshot triples published by Phase 8.2.
const RESEALED_DATES = ["2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04"];

describe("phase8.2 re-sealed artifacts pass the client validators", () => {
  it("published history.json passes validateHistory", () => {
    assert.doesNotThrow(() => validateHistory(history));
  });

  it("every re-sealed snapshot triple passes validateSnapshot and validateVerify", () => {
    for (const date of RESEALED_DATES) {
      const snapshotPath = join(repoRoot, "snapshots", date, "snapshot.json");
      const snapshot = readJson(snapshotPath);
      const verify = readJson(join(repoRoot, "snapshots", date, "verify.json"));
      const manifest = readJson(join(repoRoot, "snapshots", date, "manifest.json"));
      assert.doesNotThrow(() => validateSnapshot(snapshot, date), date);
      assert.doesNotThrow(() => validateVerify(verify), date);
      const sha = createHash("sha256").update(readFileSync(snapshotPath)).digest("hex");
      assert.equal(manifest.files["snapshot.json"].sha256, sha, date);
      assert.equal(verify.snapshot_sha256, sha, date);
      assert.equal(verify.passed, true, date);
    }
  });

  it("daily_count equals backfill rows plus snapshot-only dates minus overlaps", () => {
    const backfillDates = new Set(backfill.daily.map((row) => row.date));
    const snapshotOnly = index.dates.filter((date) => !backfillDates.has(date));
    const overlaps = index.dates.filter((date) => backfillDates.has(date));
    assert.equal(overlaps.length + snapshotOnly.length, index.dates.length);
    const expected = backfill.daily.length + snapshotOnly.length;
    assert.equal(history.daily.length, expected);
    assert.equal(history.metadata.daily_count, expected);
    assert.ok(history.daily.length >= 2400, "re-sealed history keeps the raised window");
    assert.ok(history.daily.length <= MAX_HISTORY_DAILY, "history stays under the daily cap");
    assert.ok(history.daily.length <= MAX_HISTORY_OBS, "history stays under the obs cap");
    const dates = history.daily.map((row) => row.date);
    assert.deepEqual(dates, [...dates].sort(), "history dates must be ascending unique");
    assert.equal(new Set(dates).size, dates.length);
  });

  it("pins exactly the four re-sealed verified dates", () => {
    const verified = history.daily.filter((row) => row.verified);
    assert.deepEqual(
      verified.map((row) => row.date),
      RESEALED_DATES
    );
    const indexShas = new Set(
      index.dates.map((date) => index.entries[date].snapshot_sha256)
    );
    for (const row of verified) {
      assert.equal(row.source, "derived:history_verified_v1");
      assert.equal(typeof row.snapshot_sha256, "string");
      assert.ok(indexShas.has(row.snapshot_sha256), "verified sha must exist in the index");
    }
  });

  it("carries every non re-sealed backfill row through the merge unverified", () => {
    const resealed = new Set(RESEALED_DATES);
    const byDate = new Map(history.daily.map((row) => [row.date, row]));
    let carried = 0;
    for (const row of backfill.daily) {
      if (resealed.has(row.date)) continue;
      const merged = byDate.get(row.date);
      assert.ok(merged, "backfill date must survive the merge: " + row.date);
      assert.equal(merged.verified, false, row.date);
      assert.equal(merged.source, "derived:backfill_v1", row.date);
      assert.equal(merged.snapshot_sha256, null, row.date);
      carried += 1;
    }
    const verifiedCount = history.daily.filter((row) => row.verified).length;
    assert.equal(carried + verifiedCount, history.daily.length);
    assert.equal(carried, backfill.daily.length - RESEALED_DATES.length);
  });

  it("keeps the sealed 60 CPI months with a zero trim count", () => {
    assert.equal(history.metadata.cpi_count, MAX_HISTORY_CPI);
    assert.equal(history.cpi.length, 60);
    assert.equal(backfill.cpi.length, 60);
    assert.deepEqual(
      history.cpi.map((row) => row.month),
      backfill.cpi.map((row) => row.month)
    );
    assert.ok(history.cpi.every((row) => row.verified === false));
    assert.equal(index.history.trimmed_backfilled_count, 0);
  });

  it("index history entry binds the published history.json bytes", () => {
    assert.equal(index.history.sha256, createHash("sha256").update(historyRaw).digest("hex"));
    assert.equal(index.history.bytes_utf8, historyRaw.length);
    assert.equal(index.history.daily_count, history.daily.length);
    assert.equal(index.history.cpi_count, history.cpi.length);
    assert.equal(index.latest, RESEALED_DATES[RESEALED_DATES.length - 1]);
    assert.deepEqual(index.dates, RESEALED_DATES);
  });

  it("pins the raised 2750 caps beside the re-sealed counts", () => {
    assert.equal(MAX_HISTORY_DAILY, 2750);
    assert.equal(MAX_HISTORY_OBS, 2750);
    assert.ok(backfill.daily.length <= MAX_HISTORY_DAILY);
    assert.ok(backfill.daily.length <= MAX_HISTORY_OBS);
    assert.ok(backfill.daily.length >= 2400, "backfill keeps the ten year window");
  });
});
