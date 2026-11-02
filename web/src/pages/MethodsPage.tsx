import { For, Show } from "solid-js";
import SectionState from "../components/SectionState";
import {
  ASSUMPTION_ROWS,
  CHECK_FAMILIES,
  LIMIT_ROWS,
  METHOD_SECTIONS,
} from "../lib/methods-content";
import type { HistoryDoc, SnapshotDoc, VerifyReport } from "../lib/types";

interface Props {
  snapshot: SnapshotDoc | null;
  verify: VerifyReport | null;
  loading: boolean;
  error: string | null;
  history?: HistoryDoc | null;
}

export default function MethodsPage(props: Props) {
  const curveMethod = () =>
    props.snapshot?.observations.curve?.method ?? "method unknown";
  const inflationMethod = () =>
    props.snapshot?.observations.inflation?.method ?? "method unknown";
  const breaksMethod = () =>
    props.snapshot?.observations.breaks?.method ?? "method unknown";
  return (
    <section aria-label="Methods">
      <p class="hero-kicker">Methods: what v1 claims and what it does not</p>
      <h2 class="hero-headline">True bootstrap, stated plainly.</h2>
      <p class="hero-dek">
        This page renders the shared methods module, then pins the live method
        ids, tolerance, and check count from the current snapshot and verify
        report. Copy below is static and always readable, even when derived
        displays are blocked.
      </p>
      <div class="ledger-card">
        <h2>
          Live pins (tolerance {props.verify?.tolerance_bp ?? "unknown"}{" "}
          {props.verify?.tolerance_unit ?? "tolerance unknown"}, checks{" "}
          {props.verify?.checks.length ?? "unknown"})
        </h2>
        <SectionState
          loading={props.loading}
          error={props.error}
          empty={false}
        >
          <table>
            <caption>Pinned method ids and check families for this date</caption>
            <thead>
              <tr>
                <th scope="col">Layer</th>
                <th scope="col">Method</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Curve</td>
                <td class="num">{curveMethod()}</td>
              </tr>
              <tr>
                <td>Inflation</td>
                <td class="num">{inflationMethod()}</td>
              </tr>
              <tr>
                <td>Breaks</td>
                <td class="num">{breaksMethod()}</td>
              </tr>
              <tr>
                <td>History</td>
                <td class="num">{props.history?.metadata.method ?? "history_merge_v1"}</td>
              </tr>
              <For each={CHECK_FAMILIES}>
                {(family) => (
                  <tr>
                    <td>{family.range}</td>
                    <td>
                      {family.title}: {family.blurb}
                    </td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
          <Show when={props.history}>
            <p class="figure-caption">
              History window: {props.history?.metadata.daily_count} daily rows
              and {props.history?.metadata.cpi_count} CPI months, asof{" "}
              {props.history?.metadata.asof}. CPI vintage is uniform (2024
              expenditure, link 2025-05, provisional). Backfilled spans are
              unverified and dashed, verified spans carry snapshot digests.
            </p>
          </Show>
        </SectionState>
        <p class="figure-caption">
          Twenty five checks at 1.0 basis point tolerance. Any failure blocks
          the build and turns derived values to NA.
        </p>
      </div>
      <For each={METHOD_SECTIONS}>
        {(section) => (
          <div class="ledger-card" style={{ margin: "16px 0" }}>
            <p class="hero-kicker">{section.kicker}</p>
            <h2>{section.title}</h2>
            <p class="num">{section.method}</p>
            <p>{section.summary}</p>
            <ul>
              <For each={section.points}>{(point) => <li>{point}</li>}</For>
            </ul>
            <Show when={section.limits.length > 0}>
              <p class="figure-caption">Limits: {section.limits.join(" ")}</p>
            </Show>
          </div>
        )}
      </For>
      <div class="grid-two" style={{ margin: "16px 0" }}>
        <div class="ledger-card">
          <h2>Assumptions and consequences</h2>
          <table>
            <caption>What v1 assumes and what follows</caption>
            <thead>
              <tr>
                <th scope="col">Topic</th>
                <th scope="col">Assumption</th>
                <th scope="col">Consequence</th>
              </tr>
            </thead>
            <tbody>
              <For each={ASSUMPTION_ROWS}>
                {(row) => (
                  <tr>
                    <td>{row.topic}</td>
                    <td>{row.assumption}</td>
                    <td>{row.consequence}</td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
        <div class="ledger-card">
          <h2>Limits and rationale</h2>
          <table>
            <caption>Where v1 stops and why</caption>
            <thead>
              <tr>
                <th scope="col">Topic</th>
                <th scope="col">Limit</th>
                <th scope="col">Rationale</th>
              </tr>
            </thead>
            <tbody>
              <For each={LIMIT_ROWS}>
                {(row) => (
                  <tr>
                    <td>{row.topic}</td>
                    <td>{row.limit}</td>
                    <td>{row.rationale}</td>
                  </tr>
                )}
              </For>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
