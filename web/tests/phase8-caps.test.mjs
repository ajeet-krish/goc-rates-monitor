import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..", "..");
const webRoot = join(here, "..");

function readRepo(rel) {
  return readFileSync(join(repoRoot, rel), "utf8");
}

function readWeb(rel) {
  return readFileSync(join(webRoot, rel), "utf8");
}

function intConst(source, pattern, label) {
  const match = source.match(pattern);
  assert.ok(match, "missing " + label + " declaration");
  return Number(match[1]);
}

const LIMITS_DAILY = /^MAX_BACKFILL_DAILY_ROWS: int = (\d+)$/m;
const LIMITS_CPI = /^MAX_BACKFILL_CPI_MONTHS: int = (\d+)$/m;
const LIMITS_OBS = /^MAX_HISTORY_OBS: int = (\d+)$/m;
const BUILD_DAILY = /^const MAX_HISTORY_DAILY = (\d+);$/m;
const BUILD_CPI = /^const MAX_HISTORY_CPI = (\d+);$/m;
const VALIDATE_DAILY = /^export const MAX_HISTORY_DAILY = (\d+);$/m;
const VALIDATE_OBS = /^export const MAX_HISTORY_OBS = (\d+);$/m;
const CHART_POINTS = /^export const MAX_CHART_POINTS = (\d+);$/m;

const limitsSource = readRepo("src/goc_rates/limits.py");
const buildSource = readWeb("scripts/build-data.mjs");
const validateSource = readWeb("src/lib/validate.ts");
const chartSource = readWeb("src/components/Chart.tsx");

describe("phase8 caps: Python limits mirror the web caps", () => {
  it("keeps MAX_BACKFILL_DAILY_ROWS equal to build-data MAX_HISTORY_DAILY", () => {
    const limitsDaily = intConst(limitsSource, LIMITS_DAILY, "limits MAX_BACKFILL_DAILY_ROWS");
    const buildDaily = intConst(buildSource, BUILD_DAILY, "build-data MAX_HISTORY_DAILY");
    assert.equal(limitsDaily, buildDaily);
  });

  it("keeps MAX_BACKFILL_CPI_MONTHS equal to build-data MAX_HISTORY_CPI", () => {
    const limitsCpi = intConst(limitsSource, LIMITS_CPI, "limits MAX_BACKFILL_CPI_MONTHS");
    const buildCpi = intConst(buildSource, BUILD_CPI, "build-data MAX_HISTORY_CPI");
    assert.equal(limitsCpi, buildCpi);
  });

  it("keeps MAX_HISTORY_OBS equal to validate.ts MAX_HISTORY_OBS", () => {
    const limitsObs = intConst(limitsSource, LIMITS_OBS, "limits MAX_HISTORY_OBS");
    const validateObs = intConst(validateSource, VALIDATE_OBS, "validate MAX_HISTORY_OBS");
    assert.equal(limitsObs, validateObs);
  });

  it("keeps the validate.ts daily mirror aligned with the build mirror", () => {
    const validateDaily = intConst(
      validateSource,
      VALIDATE_DAILY,
      "validate MAX_HISTORY_DAILY"
    );
    const buildDaily = intConst(buildSource, BUILD_DAILY, "build-data MAX_HISTORY_DAILY");
    assert.equal(validateDaily, buildDaily);
  });

  it("keeps MAX_CHART_POINTS at 2000 beside the Phase 8.4 contract comment", () => {
    const points = intConst(chartSource, CHART_POINTS, "Chart MAX_CHART_POINTS");
    assert.equal(points, 2000);
    const pointIndex = chartSource.indexOf("MAX_CHART_POINTS = 2000");
    assert.ok(pointIndex >= 0, "MAX_CHART_POINTS must stay at the 2000 point render cap");
    const window = chartSource.slice(Math.max(0, pointIndex - 600), pointIndex);
    assert.match(
      window,
      /Phase 8\.4 aggregation contract/,
      "Phase 8.4 comment must sit near the cap"
    );
    assert.match(window, /2000 points/, "comment must state the 2000 point contract");
    assert.match(window, /2750 daily rows/, "comment must state the 2750 daily row input");
  });
});
