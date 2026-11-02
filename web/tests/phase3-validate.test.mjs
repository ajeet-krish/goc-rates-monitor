import { describe, it, afterEach } from "node:test";
import assert from "node:assert/strict";
import {
  validateIndex,
  validateSnapshot,
  validateVerify,
  ValidationError,
  MAX_KNOTS,
  MAX_SPREAD_RECORDS,
  MAX_BACKTEST_OBS,
  MAX_VERIFY_CHECKS,
  MAX_QUANTITIES,
  MAX_INDEX_DATES,
  MAX_PROVENANCE_ENTRIES,
  MAX_COLLECT_DEPTH,
  EXPECTED_VERIFY_IDS,
} from "../src/lib/validate.ts";
import {
  isStrictIsoDate,
  readAsofState,
  resolveAsof,
  latestN,
} from "../src/lib/asof.ts";
import {
  MAX_JSON_BYTES,
  FETCH_TIMEOUT_MS,
  dataUrl,
  fetchSnapshot,
} from "../src/lib/snapshot.ts";
import {
  mockSnapshot,
  mockVerify,
  mockIndex,
  MOCK_DATE,
  MOCK_SHA256,
} from "../src/lib/fixtures/mock-snapshot.ts";

function clone(value) {
  return structuredClone(value);
}

function goodSnapshot(asof = MOCK_DATE) {
  const doc = clone(mockSnapshot);
  doc.metadata.snapshot_date = asof;
  return doc;
}

function goodVerify() {
  return clone(mockVerify);
}

function goodIndex() {
  return clone(mockIndex);
}

const realFetch = globalThis.fetch;
const realSetTimeout = globalThis.setTimeout;
afterEach(() => {
  globalThis.fetch = realFetch;
  globalThis.setTimeout = realSetTimeout;
});

describe("validators reject malformed quantities", () => {
  it("rejects a bad unit on a benchmark quantity", () => {
    const doc = goodSnapshot();
    doc.observations.benchmarks["10Y"].valet.unit = "furlongs";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), ValidationError);
  });

  it("rejects a bad quality on a benchmark quantity", () => {
    const doc = goodSnapshot();
    doc.observations.benchmarks["10Y"].valet.quality = "guessy";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), ValidationError);
  });

  it("rejects a bad source_id grammar on a benchmark quantity", () => {
    const doc = goodSnapshot();
    doc.observations.benchmarks["10Y"].valet.source_id = "evil:drop-table";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), ValidationError);
  });

  it("rejects an overlong source_id", () => {
    const doc = goodSnapshot();
    doc.observations.benchmarks["10Y"].valet.source_id = "valet:" + "A".repeat(80);
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), ValidationError);
  });

  it("rejects NaN and Infinity values as non finite", () => {
    for (const bad of [NaN, Infinity, -Infinity]) {
      const doc = goodSnapshot();
      doc.observations.benchmarks["10Y"].valet.value = bad;
      assert.throws(
        () => validateSnapshot(doc, MOCK_DATE),
        ValidationError,
        "expected rejection for " + String(bad)
      );
    }
  });

  it("rejects missing quality with a non null value", () => {
    const doc = goodSnapshot();
    const q = doc.observations.benchmarks["10Y"].valet;
    q.quality = "missing";
    q.value = 3.85;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), ValidationError);
  });

  it("accepts missing quality with a null value", () => {
    const doc = goodSnapshot();
    const q = doc.observations.benchmarks["10Y"].valet;
    q.quality = "missing";
    q.value = null;
    assert.doesNotThrow(() => validateSnapshot(doc, MOCK_DATE));
  });
});

describe("validators reject snapshot identity problems", () => {
  it("rejects an asof mismatch between URL date and snapshot_date", () => {
    const doc = goodSnapshot("2026-10-30");
    assert.throws(
      () => validateSnapshot(doc, "2026-10-29"),
      /does not match requested asof/
    );
  });

  it("rejects a non strict snapshot_date", () => {
    const doc = goodSnapshot();
    doc.metadata.snapshot_date = "10/30/2026";
    assert.throws(
      () => validateSnapshot(doc, "10/30/2026"),
      ValidationError
    );
  });
});

describe("validators reject verify problems", () => {
  it("rejects a verify digest mismatch against the published digest", () => {
    const report = goodVerify();
    assert.throws(
      () => validateVerify(report, "0".repeat(64)),
      /does not match the published snapshot digest/
    );
  });

  it("accepts a verify digest match", () => {
    assert.doesNotThrow(() => validateVerify(goodVerify(), MOCK_SHA256));
  });

  it("rejects an empty verify report with zero checks", () => {
    const report = goodVerify();
    report.checks = [];
    report.passed_count = 0;
    report.failed_count = 0;
    assert.throws(() => validateVerify(report), /exactly 25 checks/);
  });

  it("rejects a report with non V01 to V25 ids", () => {
    const report = goodVerify();
    report.checks[24].id = "V26";
    assert.throws(() => validateVerify(report), /exactly V01 to V25/);
  });

  it("rejects duplicate check ids", () => {
    const report = goodVerify();
    report.checks[1].id = "V01";
    assert.throws(() => validateVerify(report), /unique/);
  });

  it("rejects inconsistent passed_count and failed_count", () => {
    const report = goodVerify();
    report.passed_count = 3;
    report.failed_count = 15;
    assert.throws(() => validateVerify(report), /inconsistent/);
  });

  it("rejects a passed flag inconsistent with failures", () => {
    const report = goodVerify();
    report.checks[0].passed = false;
    report.passed_count = 17;
    report.failed_count = 1;
    report.passed = true;
    assert.throws(() => validateVerify(report), /inconsistent/);
  });

  it("expects exactly V01 to V25", () => {
    assert.equal(EXPECTED_VERIFY_IDS.length, MAX_VERIFY_CHECKS);
    assert.equal(EXPECTED_VERIFY_IDS[0], "V01");
    assert.equal(EXPECTED_VERIFY_IDS[24], "V25");
  });

  it("accepts the mock inflation section through the snapshot validator", () => {
    assert.doesNotThrow(() => validateSnapshot(goodSnapshot(), MOCK_DATE));
  });

  it("rejects a non experimental inflation label", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.label = "official";
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /must be experimental/);
  });

  it("rejects an inflation bulk section without the three pinned products", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.bulk = { cpi_monthly: doc.observations.inflation.bulk.cpi_monthly };
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /three products/);
  });

  it("rejects inflation residuals that do not recompute the MAE", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.validation.residuals_trim_pp[0] = 5;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /does not recompute/);
  });

  it("rejects inflation weights that drift from 100", () => {
    const doc = goodSnapshot();
    doc.observations.inflation.contributions[0].weight_percent += 2;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /expected 100 within/);
  });
});

describe("fetch caps: oversize and timeout budgets", () => {
  it("pins the 5MiB JSON cap and the 15s timeout", () => {
    assert.equal(MAX_JSON_BYTES, 5 * 1024 * 1024);
    assert.equal(FETCH_TIMEOUT_MS, 15_000);
  });

  it("rejects a payload with an oversize declared Content-Length", async () => {
    const big = String(MAX_JSON_BYTES + 1);
    globalThis.fetch = async () =>
      new Response("{}", { headers: { "content-length": big } });
    await assert.rejects(() => fetchSnapshot(MOCK_DATE), /byte cap/);
  });

  it("rejects a payload whose streamed body exceeds the cap", async () => {
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array(MAX_JSON_BYTES + 8));
        controller.close();
      },
    });
    globalThis.fetch = async () => new Response(stream, { status: 200 });
    await assert.rejects(() => fetchSnapshot(MOCK_DATE), /byte cap/);
  });

  it("times out a hung fetch after the budget with a timeout error", async () => {
    globalThis.setTimeout = ((callback, ...args) =>
      realSetTimeout(callback, 0, ...args));
    globalThis.fetch = (_url, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("aborted", "AbortError"));
        });
      });
    await assert.rejects(() => fetchSnapshot(MOCK_DATE), /timed out after 15000 ms/);
  });

  it("builds data URLs under the data prefix", () => {
    assert.match(dataUrl("index.json"), /data\/index\.json/);
    assert.match(
      dataUrl(MOCK_DATE + "/snapshot.json"),
      new RegExp("data/" + MOCK_DATE + "/snapshot\\.json")
    );
  });
});

describe("validators enforce collection caps", () => {
  it("rejects more than 10 curve knots", () => {
    assert.equal(MAX_KNOTS, 10);
    const doc = goodSnapshot();
    const knot = doc.observations.curve.knots[0];
    doc.observations.curve.knots = Array.from({ length: 11 }, () => clone(knot));
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /cap/);
  });

  it("rejects more than 2000 spread records", () => {
    assert.equal(MAX_SPREAD_RECORDS, 2000);
    const doc = goodSnapshot();
    const row = doc.observations.spreads.records[0];
    doc.observations.spreads.records = Array.from({ length: 2001 }, () => clone(row));
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /record cap/);
  });

  it("rejects more than 2000 backtest observations", () => {
    assert.equal(MAX_BACKTEST_OBS, 2000);
    const doc = goodSnapshot();
    doc.observations.backtest.dates = Array.from(
      { length: 2001 },
      (_, i) => "2020-01-" + String((i % 28) + 1).padStart(2, "0")
    );
    doc.observations.backtest.slopes_bp = Array.from({ length: 2001 }, () => 1.5);
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /backtest cap/);
  });

  it("rejects more than 10000 quantities", () => {
    assert.equal(MAX_QUANTITIES, 10000);
    const doc = goodSnapshot();
    const q = doc.observations.benchmarks["10Y"].valet;
    doc.observations.extra = Array.from({ length: 10001 }, () => clone(q));
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /quantity cap/);
  });

  it("rejects more than 2000 index dates", () => {
    assert.equal(MAX_INDEX_DATES, 2000);
    const index = goodIndex();
    index.dates = Array.from({ length: 2001 }, (_, i) => {
      const day = String((i % 28) + 1).padStart(2, "0");
      const month = String((Math.floor(i / 28) % 12) + 1).padStart(2, "0");
      return "2020-" + month + "-" + day;
    });
    assert.throws(() => validateIndex(index), /date cap/);
  });

  it("rejects more than 64 provenance entries", () => {
    assert.equal(MAX_PROVENANCE_ENTRIES, 64);
    const doc = goodSnapshot();
    doc.provenance = Object.fromEntries(
      Array.from({ length: 65 }, (_, i) => [
        "src" + i,
        {
          source_url: "https://example.com/" + i,
          retrieved_utc: "2026-10-31T00:00:00Z",
          vintage: MOCK_DATE,
        },
      ])
    );
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /provenance/);
  });

  it("rejects pathological nesting past the depth cap", () => {
    assert.equal(MAX_COLLECT_DEPTH, 64);
    const doc = goodSnapshot();
    const deep = {};
    let cursor = deep;
    for (let i = 0; i < 80; i++) {
      cursor.next = {};
      cursor = cursor.next;
    }
    doc.observations.deep = deep;
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /nesting cap/);
  });
});

describe("spreads ok envelope tenor set", () => {
  it("rejects an ok envelope with a 3 tenor subset", () => {
    const doc = goodSnapshot();
    doc.observations.spreads.records = doc.observations.spreads.records.slice(0, 3);
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /exactly.*with no duplicates/);
  });

  it("rejects an ok envelope with a duplicate tenor and no 30Y", () => {
    const doc = goodSnapshot();
    const rows = doc.observations.spreads.records;
    doc.observations.spreads.records = [rows[0], clone(rows[0]), rows[1], rows[2]];
    assert.throws(() => validateSnapshot(doc, MOCK_DATE), /with no duplicates/);
  });
});

describe("asof routing: invalid versus absent versus unknown", () => {
  const available = ["2026-10-29", "2026-10-30"];
  const latest = "2026-10-30";

  it("treats a missing asof as absent, not invalid", () => {
    assert.deepEqual(readAsofState(""), { requested: null, invalid: null });
    assert.deepEqual(readAsofState("?asof="), {
      requested: null,
      invalid: null,
    });
  });

  it("keeps malformed asof values distinct from absence", () => {
    assert.deepEqual(readAsofState("?asof=not-a-date"), {
      requested: null,
      invalid: "not-a-date",
    });
    assert.deepEqual(readAsofState("?asof=2026-13-99"), {
      requested: null,
      invalid: "2026-13-99",
    });
    assert.deepEqual(readAsofState("?asof=10%2F30%2F2026"), {
      requested: null,
      invalid: "10/30/2026",
    });
  });

  it("accepts a strict ISO date as requested", () => {
    assert.deepEqual(readAsofState("?asof=2026-10-29"), {
      requested: "2026-10-29",
      invalid: null,
    });
  });

  it("resolves absent to latest with no unknown banner", () => {
    assert.deepEqual(resolveAsof(null, null, available, latest), {
      asof: latest,
      unknownDate: null,
    });
  });

  it("resolves a known date to itself with no unknown banner", () => {
    assert.deepEqual(resolveAsof("2026-10-29", null, available, latest), {
      asof: "2026-10-29",
      unknownDate: null,
    });
  });

  it("resolves an unknown well formed date to latest with an unknown banner", () => {
    assert.deepEqual(resolveAsof("2026-10-28", null, available, latest), {
      asof: latest,
      unknownDate: "2026-10-28",
    });
  });

  it("resolves a malformed value to latest with the raw value as unknown", () => {
    assert.deepEqual(resolveAsof(null, "not-a-date", available, latest), {
      asof: latest,
      unknownDate: "not-a-date",
    });
  });

  it("rejects impossible calendar dates as non strict", () => {
    assert.equal(isStrictIsoDate("2026-02-30"), false);
    assert.equal(isStrictIsoDate("2026-10-30"), true);
  });

  it("latestN returns the newest dates in order", () => {
    assert.deepEqual(latestN(["2026-10-28", "2026-10-30", "2026-10-29"], 2), [
      "2026-10-29",
      "2026-10-30",
    ]);
  });
});
