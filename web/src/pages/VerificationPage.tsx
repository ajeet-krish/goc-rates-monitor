import { For, Show } from "solid-js";
import DataTable from "../components/DataTable";
import FailClosedDemo from "../components/FailClosedDemo";
import SectionState from "../components/SectionState";
import { CHECK_FAMILIES } from "../lib/methods-content";
import type { SnapshotDoc, VerifyReport } from "../lib/types";
import { fmtShortSha } from "../lib/format";

interface Props {
  verify: VerifyReport | null;
  snapshot: SnapshotDoc | null;
  asof: string | null;
  loading: boolean;
  error: string | null;
}

function familyOf(id: string): string {
  const n = Number.parseInt(id.slice(1), 10);
  if (Number.isFinite(n) && n >= 1 && n <= 12) return "V01 to V12: core snapshot";
  if (Number.isFinite(n) && n >= 13 && n <= 18) return "V13 to V18: curve and funding";
  if (Number.isFinite(n) && n >= 19 && n <= 22) return "V19 to V22: inflation replica";
  return "V23: breaks gate";
}

export default function VerificationPage(props: Props) {
  const curveMethod = () => props.snapshot?.observations.curve?.method ?? "method unknown";
  const inflationMethod = () =>
    props.snapshot?.observations.inflation?.method ?? "method unknown";
  const breaksMethod = () =>
    props.snapshot?.observations.breaks?.method ?? "method unknown";
  const feedVintage = () =>
    props.snapshot?.observations.breaks?.feed_vintage ?? "vintage unknown";
  return (
    <section aria-label="Verification">
      <Show
        when={props.verify}
        fallback={<p class="hero-kicker">Verification: checks pending</p>}
      >
        <p class="hero-kicker">
          Verification: {props.verify?.passed_count ?? 0} passed,{" "}
          {props.verify?.failed_count ?? 0} failed, {props.verify?.checks.length ?? 0}{" "}
          checks at {props.verify?.tolerance_bp} {props.verify?.tolerance_unit}
        </p>
      </Show>
      <h2 class="hero-headline">Fail closed, with names.</h2>
      <p class="hero-dek">
        Every check names its unit. Tolerance is {props.verify?.tolerance_bp ?? "1.0"}{" "}
        {props.verify?.tolerance_unit ?? "basis_points"}. A single failure blocks
        derived displays and the build. Checked at{" "}
        <span class="num">{props.verify?.checked_utc ?? "checked time unknown"}</span>{" "}
        (UTC) for snapshot <span class="num">{fmtShortSha(props.verify?.snapshot_sha256)}</span>.
      </p>
      <SectionState
        loading={props.loading}
        error={props.error}
        empty={!props.loading && !props.error && !props.verify}
      >
        <p>
          <span
            class="badge"
            data-state={props.verify?.passed ? "pass" : "fail"}
          >
            {props.verify?.passed ? "verify pass" : "verify fail"}:{" "}
            {props.verify?.passed_count ?? 0} of {(props.verify?.checks.length ?? 0)}
          </span>
        </p>
        <div class="ledger-card">
          <h2>Layers under check</h2>
          <p class="num">
            curve: {curveMethod()} render inflation: {inflationMethod()} render
            breaks: {breaksMethod()} (feed vintage {feedVintage()})
          </p>
          <p class="figure-caption">
            Methods come from the snapshot beside the report, so drift between
            code and data reads out here first.
          </p>
        </div>
        <For each={CHECK_FAMILIES}>
          {(family) => (
            <p class="figure-caption">
              {family.range} ({family.title}): {family.blurb}
            </p>
          )}
        </For>
        <DataTable
          caption="Verification checks with family, state, and detail including units"
          columns={[
            { key: "id", header: "Check" },
            { key: "family", header: "Family" },
            { key: "state", header: "State" },
            { key: "detail", header: "Detail" },
          ]}
          rows={(props.verify?.checks ?? []).map((c) => ({
            id: c.id,
            family: familyOf(c.id),
            state: c.passed ? "pass" : "FAIL",
            detail: c.detail,
          }))}
        />
        <div style={{ margin: "16px 0" }}>
          <FailClosedDemo asof={props.asof} />
        </div>
      </SectionState>
    </section>
  );
}
