import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = dirname(here);
const srcRoot = join(webRoot, "src");
const readSource = (rel) => readFileSync(join(webRoot, rel), "utf8");

/** Every file under web/src as a path relative to webRoot, sorted. */
function collectSourceFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...collectSourceFiles(full));
    } else if (entry.isFile()) {
      out.push(relative(webRoot, full));
    }
  }
  return out.sort();
}

const sourceFiles = collectSourceFiles(srcRoot);
const fileText = new Map(
  sourceFiles.map((rel) => [rel, readFileSync(join(webRoot, rel), "utf8")])
);

/**
 * The five metaphor register phrases the Phase 8.5 copy pass removed from
 * page copy. The list stays small and specific on purpose: it guards the
 * phrases this pass killed, not prose style in general. "Thesis" is matched
 * on word boundaries so a legitimate compound cannot trip the scan.
 */
const DEAD_PHRASE_PATTERNS = [
  { label: "thesis", pattern: /\bthesis\b/i },
  { label: "commentary on this line", pattern: /commentary on this line/i },
  { label: "stated plainly", pattern: /stated plainly/i },
  { label: "honest either way", pattern: /honest either way/i },
  { label: "no funding story", pattern: /no funding story/i },
];

describe("phase8.5 dead metaphor register scan", () => {
  it("walks a non empty web/src tree that includes a page and the methods table", () => {
    assert.ok(
      sourceFiles.length >= 10,
      "expected at least 10 source files, found " + sourceFiles.length
    );
    assert.ok(
      sourceFiles.some((rel) => rel.endsWith("pages/IndexPage.tsx")),
      "the scan missed the page sources"
    );
    assert.ok(
      sourceFiles.some((rel) => rel.endsWith("lib/methods-content.ts")),
      "the scan missed the lib sources"
    );
  });

  it("keeps every removed phrase out of web/src, code comments included", () => {
    for (const rel of sourceFiles) {
      const text = fileText.get(rel);
      for (const { label, pattern } of DEAD_PHRASE_PATTERNS) {
        const match = text.match(pattern);
        assert.equal(
          match,
          null,
          rel + ' still contains the removed phrase "' + label + '"'
        );
      }
    }
  });
});

describe("phase8.5 stale numbers", () => {
  it("keeps the retired 1250 cap out of every file under web/src", () => {
    for (const rel of sourceFiles) {
      const idx = fileText.get(rel).indexOf("1250");
      assert.equal(idx, -1, rel + ' still contains the stale cap "1250"');
    }
  });

  it("states the current 2750 window cap in the methods copy", () => {
    const methods = readSource("src/lib/methods-content.ts");
    assert.ok(
      methods.includes("up to 2750"),
      'methods copy must state "up to 2750" beside the window rule'
    );
  });

  it("keeps the 60 month CPI window copy beside the 2750 cap", () => {
    // No literal "60 month" string exists in web/src; the stable CPI copy
    // is the window sentence in the methods table.
    const methods = readSource("src/lib/methods-content.ts");
    assert.ok(
      methods.includes("monthly CPI rows (up to 60)"),
      'methods copy must keep "monthly CPI rows (up to 60)"'
    );
  });
});

/** The four sampled hero blocks from the Phase 8.5 copy pass. */
const HERO_DEK_PAGES = [
  "src/pages/IndexPage.tsx",
  "src/pages/CurvePage.tsx",
  "src/pages/FundingPage.tsx",
  "src/pages/InflationPage.tsx",
];

/** Unit tokens allowed inside a hero dek, per the Phase 8.5 assurance. */
const UNIT_PATTERNS = [
  { label: "percent", pattern: /percent/i },
  { label: "bp", pattern: /\bbp\b/i },
  { label: "basis point", pattern: /basis point/i },
  { label: "years", pattern: /years?\b/i },
  { label: "face", pattern: /\bface\b/i },
  { label: "months", pattern: /months?\b/i },
  { label: "business day", pattern: /business days?\b/i },
];

/** Literal method ids plus the V check ids the copy pass treats as anchors. */
const METHOD_ID_PATTERNS = [
  { label: "true_bootstrap_semiannual_log_discount_v1", pattern: /true_bootstrap_semiannual_log_discount_v1/ },
  { label: "cpi_trim_median_weighted_sa_v1", pattern: /cpi_trim_median_weighted_sa_v1/ },
  { label: "benchmark_switch_dod_gate_v1", pattern: /benchmark_switch_dod_gate_v1/ },
  { label: "carry_roll_v1", pattern: /carry_roll_v1/ },
  { label: "semiannual_risk_v1", pattern: /semiannual_risk_v1/ },
  { label: "history_merge_v1", pattern: /history_merge_v1/ },
  { label: "V check id", pattern: /\bV\d{2}\b/ },
];

/** The raw source text inside the first hero dek paragraph of a page. */
function heroDek(rel) {
  const text = readSource(rel);
  const match = text.match(/<p class="hero-dek">([\s\S]*?)<\/p>/);
  assert.ok(match, rel + " has no hero dek block");
  return match[1]
    .replace(/\{[^}]*\}/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

describe("phase8.5 hero dek quantitative anchors", () => {
  it("extracts a substantial hero dek from each sampled page", () => {
    for (const rel of HERO_DEK_PAGES) {
      const dek = heroDek(rel);
      assert.ok(
        dek.length > 40,
        rel + " hero dek is too short to carry content: " + dek
      );
    }
  });

  for (const rel of HERO_DEK_PAGES) {
    it(rel + " hero dek holds a unit token or a method id", () => {
      const dek = heroDek(rel);
      const unit = UNIT_PATTERNS.find(({ pattern }) => pattern.test(dek));
      const method = METHOD_ID_PATTERNS.find(({ pattern }) => pattern.test(dek));
      assert.ok(
        unit || method,
        rel +
          " hero dek carries no unit token (percent, bp, basis point, years, " +
          "face, months, business day) and no method id: " +
          dek
      );
    });
  }
});
