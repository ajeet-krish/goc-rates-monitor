import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function readSource(relative) {
  return readFile(path.join(webDir, relative), "utf8");
}

describe("router and reload fallback wiring", () => {
  it("navigates with an encoded asof query on date change", async () => {
    const app = await readSource("src/App.tsx");
    assert.match(app, /\?asof=/);
    assert.match(app, /encodeURIComponent\(asof\)/);
    assert.match(app, /useNavigate/);
  });

  it("keys snapshot and verify resources on the resolved asof", async () => {
    const app = await readSource("src/App.tsx");
    assert.match(app, /createResource\(resolved/);
    assert.match(app, /fetchSnapshot\(r\.asof\)/);
    assert.match(app, /fetchVerify\(r\.asof, digest\)/);
  });

  it("falls back unknown paths to a ledger placeholder route", async () => {
    const app = await readSource("src/App.tsx");
    assert.match(app, /path="\*"/);
    assert.match(app, /No such ledger page/);
  });

  it("ships a 404 fallback that preserves the asof query on hard reload", async () => {
    const fallback = await readSource("public/404.html");
    assert.match(fallback, /asof/);
    const index = await readSource("index.html");
    assert.match(index, /id="root"/);
  });
});

describe("site shell: phone layout, stamp, mock isolation, loading gate", () => {
  it("keeps a 360px phone free of horizontal scroll", async () => {
    const css = await readSource("src/index.css");
    assert.match(css, /overflow-x: auto/);
    assert.match(css, /max-width: 100%/);
    assert.match(css, /@media \(max-width: 640px\)/);
    assert.match(css, /grid-template-columns: 1fr/);
    assert.match(css, /min-height: 44px/);
    assert.match(css, /max-width: 1060px/);
  });

  it("renders the footer stamp from real verify counts, tolerance, and method", async () => {
    const stamp = await readSource("src/components/FooterStamp.tsx");
    assert.match(stamp, /passed_count/);
    assert.match(stamp, /checks\.length/);
    assert.match(stamp, /tolerance_bp/);
    assert.match(stamp, /tolerance_unit/);
    assert.match(stamp, /curveMethod/);
    assert.match(stamp, /snapshot sha/);
    assert.match(stamp, /unknownDate/);
  });

  it("loads mock fixtures only through a dynamic import gated on VITE_USE_MOCK", async () => {
    const app = await readSource("src/App.tsx");
    assert.match(app, /await import\("\.\/lib\/fixtures\/mock-snapshot"\)/);
    assert.doesNotMatch(app, /^import .*mock-snapshot/m);
    assert.match(app, /VITE_USE_MOCK/);
    const snapshotLib = await readSource("src/lib/snapshot.ts");
    assert.match(snapshotLib, /VITE_USE_MOCK/);
  });

  it("keeps the production bundle free of mock fixtures without the flag", async () => {
    const distDir = path.join(webDir, "dist/assets");
    const entries = await readdir(distDir);
    const scripts = entries.filter((name) => name.endsWith(".js"));
    assert.ok(scripts.length > 0, "expected built JS chunks in dist/assets");
    const chunks = await Promise.all(
      scripts.map((name) => readFile(path.join(distDir, name), "utf8"))
    );
    const bundled = chunks.join("\n");
    assert.doesNotMatch(bundled, /mock fixture/);
    assert.doesNotMatch(bundled, /MOCK_DATE/);
  });

  it("blocks derived displays while loading, errored, or failed", async () => {
    const app = await readSource("src/App.tsx");
    assert.match(app, /snapshot\.loading \|\| verify\.loading/);
    assert.match(app, /snapshot\.error \|\| verify\.error/);
    assert.match(app, /if \(!v\) return true/);
    assert.match(app, /return !v\.passed/);
    assert.match(app, /BlockedNotice/);
    assert.match(app, /Derived values stay NA until verify arrives/);
  });
});
