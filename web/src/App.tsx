import { createEffect, createMemo, createResource, lazy, Show, Suspense } from "solid-js";
import { A, Route, Router, useLocation, useNavigate } from "@solidjs/router";
import FooterStamp from "./components/FooterStamp";
import StalenessBanner from "./components/StalenessBanner";
import { DeskProvider, useDesk } from "./lib/desk";
import { fetchHistory, fetchIndex, fetchSnapshot, fetchVerify, useMock } from "./lib/snapshot";
import { canonicalSearch, isStrictIsoDate, latestN, readAsofState, resolveAsof } from "./lib/asof";
import { stepDate } from "./lib/history";
import { validateIndex, validateSnapshot, validateVerify } from "./lib/validate";
import type { DataIndex, SnapshotDoc, VerifyReport } from "./lib/types";
import type { ParentProps } from "solid-js";

const IndexPage = lazy(() => import("./pages/IndexPage"));
const CurvePage = lazy(() => import("./pages/CurvePage"));
const FundingPage = lazy(() => import("./pages/FundingPage"));
const InflationPage = lazy(() => import("./pages/InflationPage"));
const MethodsPage = lazy(() => import("./pages/MethodsPage"));
const VerificationPage = lazy(() => import("./pages/VerificationPage"));
const BreaksPage = lazy(() => import("./pages/BreaksPage"));
const PlaceholderPage = lazy(() => import("./pages/PlaceholderPage"));

/**
 * Mock fixtures load only through this explicit dynamic import, so the
 * production entry chunk never bundles them. Enabled solely by VITE_USE_MOCK.
 */
async function loadMockIndex(): Promise<DataIndex> {
  const mock = await import("./lib/fixtures/mock-snapshot");
  return validateIndex(mock.mockIndex);
}

async function loadMockSnapshot(asof: string): Promise<SnapshotDoc> {
  const mock = await import("./lib/fixtures/mock-snapshot");
  return validateSnapshot(mock.mockSnapshot, asof);
}

async function loadMockVerify(asof: string): Promise<VerifyReport> {
  const mock = await import("./lib/fixtures/mock-snapshot");
  const digest =
    mock.mockIndex.entries[asof]?.snapshot_sha256 ??
    mock.mockIndex.entries[mock.MOCK_DATE]?.snapshot_sha256;
  return validateVerify(mock.mockVerify, digest);
}

function errText(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return String(error ?? "unknown error");
}

function DatePicker(props: {
  dates: string[];
  current: string | null;
  unknownDate: string | null;
  compare: string | null;
  unknownCompare: string | null;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  let textRef: HTMLInputElement | undefined;
  const recent = () => latestN(props.dates, 90);
  const search = (asof: string | null, compare: string | null): string =>
    canonicalSearch(location.pathname, asof, compare);
  const go = (asof: string) => {
    navigate(search(asof, props.compare));
  };
  const goCompare = (compare: string | null) => {
    navigate(search(props.current, compare));
  };
  const jump = () => {
    const raw = textRef?.value.trim() ?? "";
    if (!raw) return;
    go(raw);
  };
  const prev = () => {
    const target = stepDate(props.dates, props.current, -1);
    if (target) go(target);
  };
  const next = () => {
    const target = stepDate(props.dates, props.current, 1);
    if (target) go(target);
  };
  const hasPrev = () => stepDate(props.dates, props.current, -1) !== null;
  const hasNext = () => stepDate(props.dates, props.current, 1) !== null;
  const onToolbarKeys = (e: KeyboardEvent) => {
    const target = e.target as HTMLElement | null;
    if (
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement ||
      (target !== null && target.isContentEditable)
    ) {
      return;
    }
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      prev();
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      next();
    }
  };
  return (
    <div
      class="toolbar"
      role="group"
      aria-label="Snapshot date picker with compare overlay and step controls"
      onKeyDown={onToolbarKeys}
    >
      <div class="field">
        <label for="asof-select">Snapshot date</label>
        <select
          id="asof-select"
          value={props.current ?? ""}
          onChange={(e) => go(e.currentTarget.value)}
        >
          {recent().length === 0 && <option value="">No dates published</option>}
          {recent().map((d) => (
            <option value={d} selected={d === props.current}>
              {d}
            </option>
          ))}
        </select>
      </div>
      <div class="field">
        <label for="compare-select">Compare date</label>
        <select
          id="compare-select"
          value={props.compare ?? ""}
          onChange={(e) => goCompare(e.currentTarget.value || null)}
        >
          <option value="">No compare</option>
          {recent().map((d) => (
            <option value={d} selected={d === props.compare}>
              {d}
            </option>
          ))}
        </select>
      </div>
      <button
        class="btn btn-secondary"
        type="button"
        aria-label="Previous snapshot date"
        disabled={!hasPrev()}
        onClick={prev}
      >
        Prev
      </button>
      <button
        class="btn btn-secondary"
        type="button"
        aria-label="Next snapshot date"
        disabled={!hasNext()}
        onClick={next}
      >
        Next
      </button>
      <div class="field">
        <label for="asof-text">Jump to date (YYYY-MM-DD)</label>
        <input id="asof-text" ref={textRef} type="text" placeholder="2026-10-30" inputmode="numeric" />
      </div>
      <button class="btn" type="button" onClick={jump}>
        Load date
      </button>
      {props.unknownDate && (
        <span class="badge" data-state="warn">
          unknown date {props.unknownDate}
        </span>
      )}
      {props.unknownCompare && (
        <span class="badge" data-state="warn">
          unknown compare {props.unknownCompare}
        </span>
      )}
    </div>
  );
}

function BlockedNotice() {
  const d = useDesk();
  return (
    <div class="alert" role="alert">
      <h3>Derived displays blocked</h3>
      <p>{d.blockReason() ?? "Verification is pending for this date."}</p>
      <p>
        <A href="/verification">Open verification for the named checks</A>. Values stay
        NA until every check passes.
      </p>
    </div>
  );
}

function IndexRoute() {
  const d = useDesk();
  return (
    <Show when={!d.blocked()} fallback={<BlockedNotice />}>
      <IndexPage snapshot={d.snapshot() ?? null} loading={d.snapLoading()} error={d.snapError()} />
    </Show>
  );
}

function CurveRoute() {
  const d = useDesk();
  return (
    <Show when={!d.blocked()} fallback={<BlockedNotice />}>
      <CurvePage
        snapshot={d.snapshot() ?? null}
        loading={d.snapLoading()}
        error={d.snapError()}
        history={d.history() ?? null}
        historyLoading={d.historyLoading()}
        historyError={d.historyError()}
        compare={d.compare()}
        compareSnapshot={d.compareSnapshot() ?? null}
        compareLoading={d.compareLoading()}
        compareError={d.compareError()}
      />
    </Show>
  );
}

function FundingRoute() {
  const d = useDesk();
  return (
    <Show when={!d.blocked()} fallback={<BlockedNotice />}>
      <FundingPage
        snapshot={d.snapshot() ?? null}
        loading={d.snapLoading()}
        error={d.snapError()}
        history={d.history() ?? null}
        historyLoading={d.historyLoading()}
        historyError={d.historyError()}
      />
    </Show>
  );
}

function InflationRoute() {
  const d = useDesk();
  return (
    <Show when={!d.blocked()} fallback={<BlockedNotice />}>
      <InflationPage
        snapshot={d.snapshot() ?? null}
        loading={d.snapLoading()}
        error={d.snapError()}
        history={d.history() ?? null}
        historyLoading={d.historyLoading()}
        historyError={d.historyError()}
      />
    </Show>
  );
}

function VerificationRoute() {
  const d = useDesk();
  return (
    <VerificationPage
      verify={d.verify() ?? null}
      snapshot={d.snapshot() ?? null}
      asof={d.asof()}
      loading={d.verifyLoading()}
      error={d.verifyError()}
    />
  );
}

function MethodsRoute() {
  const d = useDesk();
  return (
    <MethodsPage
      snapshot={d.snapshot() ?? null}
      verify={d.verify() ?? null}
      loading={d.snapLoading()}
      error={d.snapError()}
      history={d.history() ?? null}
    />
  );
}

function BreaksRoute() {
  const d = useDesk();
  return (
    <Show when={!d.blocked()} fallback={<BlockedNotice />}>
      <BreaksPage
        snapshot={d.snapshot() ?? null}
        loading={d.snapLoading()}
        error={d.snapError()}
        history={d.history() ?? null}
        historyLoading={d.historyLoading()}
        historyError={d.historyError()}
      />
    </Show>
  );
}

function Layout(props: ParentProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const [index] = createResource(async () => {
    if (useMock()) return loadMockIndex();
    return fetchIndex();
  });
  const request = createMemo(() => readAsofState(location.search));
  const resolved = createMemo(() => {
    const idx = index();
    if (!idx) return { asof: null as string | null, unknownDate: null as string | null };
    return resolveAsof(request().requested, request().invalid, idx.dates, idx.latest);
  });
  const [snapshot] = createResource(resolved, async (r) => {
    if (!r.asof) return null;
    if (useMock()) return loadMockSnapshot(r.asof);
    return fetchSnapshot(r.asof);
  });
  const [verify] = createResource(resolved, async (r) => {
    if (!r.asof) return null;
    const digest = index()?.entries[r.asof]?.snapshot_sha256;
    if (useMock()) return loadMockVerify(r.asof);
    return fetchVerify(r.asof, digest);
  });
  const [history] = createResource(async () => {
    if (useMock()) return null;
    return fetchHistory();
  });
  const compareResolved = createMemo(() => {
    const params = new URLSearchParams(location.search);
    const raw = params.get("compare")?.trim() ?? "";
    if (!raw) return { compare: null as string | null, unknownCompare: null as string | null };
    if (!isStrictIsoDate(raw)) return { compare: null, unknownCompare: raw };
    const idx = index();
    if (!idx || !idx.dates.includes(raw)) {
      return { compare: null, unknownCompare: raw };
    }
    return { compare: raw, unknownCompare: null as string | null };
  });
  const [compareSnapshot] = createResource(compareResolved, async (r) => {
    if (!r.compare) return null;
    if (useMock()) return loadMockSnapshot(r.compare);
    return fetchSnapshot(r.compare);
  });
  createEffect(() => {
    const r = resolved();
    const req = request();
    if (r.asof && req.requested === null && req.invalid === null && readAsofState(location.search).requested !== r.asof) {
      const params = new URLSearchParams(location.search);
      const rawCompare = params.get("compare")?.trim() ?? "";
      navigate(canonicalSearch(location.pathname, r.asof, rawCompare || null), { replace: true });
    }
  });
  const indexError = createMemo(() => (index.error ? errText(index.error) : null));
  const snapError = createMemo(() => (snapshot.error ? errText(snapshot.error) : null));
  const verifyError = createMemo(() => (verify.error ? errText(verify.error) : null));
  const historyError = createMemo(() => (history.error ? errText(history.error) : null));
  const compareError = createMemo(() =>
    compareSnapshot.error ? errText(compareSnapshot.error) : null
  );
  const blocked = createMemo(() => {
    if (index.error) return true;
    if (!resolved().asof) return true;
    if (snapshot.loading || verify.loading) return true;
    if (snapshot.error || verify.error) return true;
    const v = verify();
    if (!v) return true;
    return !v.passed;
  });
  const blockReason = createMemo((): string | null => {
    if (index.error) {
      return "Snapshot index failed to load (" + errText(index.error) + "). No mock fallback: fixtures load only with VITE_USE_MOCK.";
    }
    if (!resolved().asof) return "No snapshot date is published yet.";
    if (snapshot.loading || verify.loading) {
      return "Snapshot and verification are loading for this date. Derived values stay NA until verify arrives.";
    }
    if (snapshot.error) return "Snapshot failed validation or fetch (" + errText(snapshot.error) + ").";
    if (verify.error) return "Verify report failed validation or fetch (" + errText(verify.error) + ").";
    const v = verify();
    if (!v) return "Verify report is missing for this date. Derived values stay NA until verify arrives.";
    if (!v.passed) return "Verification failed for this date. Derived values stay NA until every check passes.";
    return null;
  });
  const badge = createMemo(() => {
    if (blocked()) return { state: "warn", text: "ledger blocked" };
    const v = verify();
    if (!v) return { state: "warn", text: "ledger pending" };
    return v.passed ? { state: "ok", text: "ledger verified" } : { state: "fail", text: "ledger failed" };
  });
  const state = {
    index,
    indexError,
    asof: () => resolved().asof,
    unknownDate: () => resolved().unknownDate,
    compare: () => compareResolved().compare,
    unknownCompare: () => compareResolved().unknownCompare,
    compareSnapshot: () => compareSnapshot() ?? null,
    compareLoading: () => compareSnapshot.loading,
    compareError,
    snapshot: () => snapshot() ?? null,
    snapLoading: () => snapshot.loading,
    snapError,
    verify: () => verify() ?? null,
    verifyLoading: () => verify.loading,
    verifyError,
    history: () => history() ?? null,
    historyLoading: () => history.loading,
    historyError,
    blocked,
    blockReason,
  };
  return (
    <div class="shell">
      <a class="skip-link" href="#main">
        Skip to content
      </a>
      <header class="masthead">
        <div>
          <h1 class="masthead-title">GoC Rates Monitor</h1>
          <p class="masthead-sub">Desk ledger: benchmarks, funding, verification</p>
        </div>
        <span class="badge" data-state={badge().state}>
          {badge().text}
        </span>
      </header>
      <StalenessBanner
        latest={index()?.latest}
        hasDates={(index()?.dates.length ?? 0) > 0}
        verifyPassed={verify()?.passed ?? null}
      />
      <nav class="nav-row" aria-label="Sections">
        <A class="nav-link" href="/" end>
          Desk
        </A>
        <A class="nav-link" href="/curve">
          Curve
        </A>
        <A class="nav-link" href="/funding">
          Funding
        </A>
        <A class="nav-link" href="/inflation">
          Inflation
        </A>
        <A class="nav-link" href="/methods">
          Methods
        </A>
        <A class="nav-link" href="/verification">
          Verification
        </A>
        <A class="nav-link" href="/breaks">
          Breaks
        </A>
      </nav>
      <DeskProvider value={state}>
        <Show when={indexError()}>
          <div class="alert" role="alert">
            <h3>Snapshot index unavailable</h3>
            <p>{indexError()}</p>
            <p>No mock fallback is served. Fixtures load only with VITE_USE_MOCK.</p>
          </div>
        </Show>
        <DatePicker
          dates={index()?.dates ?? []}
          current={resolved().asof}
          unknownDate={resolved().unknownDate}
          compare={compareResolved().compare}
          unknownCompare={compareResolved().unknownCompare}
        />
        <Show when={blocked() && blockReason()}>
          <div class="alert" role="alert">
            <h3>Derived displays blocked</h3>
            <p>{blockReason()}</p>
          </div>
        </Show>
        <main id="main">
          <Suspense fallback={<p role="status">Loading section.</p>}>{props.children}</Suspense>
        </main>
        <FooterStamp
          asof={resolved().asof}
          sha={
            verify()?.snapshot_sha256 ??
            (resolved().asof ? index()?.entries[resolved().asof as string]?.snapshot_sha256 : undefined)
          }
          verify={verify() ?? null}
          curveMethod={snapshot()?.observations.curve?.method ?? null}
          inflationMethod={snapshot()?.observations.inflation?.method ?? null}
          breaksMethod={snapshot()?.observations.breaks?.method ?? null}
          feedVintage={snapshot()?.observations.breaks?.feed_vintage ?? null}
          checkedUtc={verify()?.checked_utc}
          unknownDate={resolved().unknownDate}
        />
      </DeskProvider>
    </div>
  );
}

export default function App() {
  const appBase = import.meta.env.BASE_URL || "/";
  return (
    <Router base={appBase}>
      <Route path="/" component={Layout}>
        <Route path="/" component={IndexRoute} />
        <Route path="/curve" component={CurveRoute} />
        <Route path="/funding" component={FundingRoute} />
        <Route path="/inflation" component={InflationRoute} />
        <Route path="/methods" component={MethodsRoute} />
        <Route path="/verification" component={VerificationRoute} />
        <Route path="/breaks" component={BreaksRoute} />
        <Route
          path="*"
          component={() => (
            <PlaceholderPage title="No such ledger page." note="The desk holds seven sections. Pick one above." />
          )}
        />
      </Route>
    </Router>
  );
}
