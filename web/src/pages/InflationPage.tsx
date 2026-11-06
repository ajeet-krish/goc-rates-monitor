import { For, Show } from "solid-js";
import Chart from "../components/Chart";
import DataTable from "../components/DataTable";
import RangeSelector from "../components/RangeSelector";
import SectionState from "../components/SectionState";
import type { HistoryDoc, SnapshotDoc } from "../lib/types";
import {
  cpiAggregationNote,
  joinNote,
  percentileCaption,
  windowCpiSeries,
} from "../lib/history-window";
import { rangeKey } from "../lib/history-range";
import { percentileSummary } from "../lib/percentiles";

interface Props {
  snapshot: SnapshotDoc | null;
  loading: boolean;
  error: string | null;
  history?: HistoryDoc | null;
  historyLoading?: boolean;
  historyError?: string | null;
}

export default function InflationPage(props: Props) {
  const inflation = () => props.snapshot?.observations.inflation ?? null;
  const vintage = () => inflation()?.weight_vintage ?? null;
  const validation = () => inflation()?.validation ?? null;
  const bulkEntries = () => Object.entries(inflation()?.bulk ?? {});
  const flagState = () => (validation()?.exceeds_gate ? "fail" : "pass");
  const contributions = () => inflation()?.contributions ?? [];
  // Read inside the reactive scope so a range change re-renders the chart.
  const range = () => rangeKey();
  // CPI stays monthly: windowCpiSeries forces daily granularity for every range.
  const trimHistory = () =>
    windowCpiSeries(props.history, range(), (row) => row.trim_mom_percent);
  const medianHistory = () =>
    windowCpiSeries(props.history, range(), (row) => row.median_mom_percent);
  const trimSummary = () => percentileSummary(trimHistory().windowPoints);
  return (
    <section aria-label="Inflation">
      <p class="hero-kicker">Inflation: experimental trim and median</p>
      <h2 class="hero-headline">Headline is final. Core is vintage.</h2>
      <p class="hero-dek">
        StatCan seasonally adjusted values are reused as published, with no extra
        transformation. Publisher series stay final while the replica trim and
        median are experimental vintages that revise with the bulk source.
      </p>
      <SectionState
        loading={props.loading}
        error={props.error}
        empty={inflation() === null && !props.loading && props.error === null}
      >
        <Show when={inflation() !== null}>
          <div class="ledger-card">
            <h2>Publisher versus experimental</h2>
            <p class="num">
              publisher: {inflation()?.publisher_series} vs experimental:{" "}
              {inflation()?.experimental_series}
            </p>
            <p class="figure-caption">
              label {inflation()?.label}, is_official{" "}
              {String(inflation()?.is_official)}, method {inflation()?.method}. Trim{" "}
              {inflation()?.latest.trim_yoy.value} percent YoY, median{" "}
              {inflation()?.latest.median_yoy.value} percent YoY for{" "}
              {inflation()?.reference_month}. Publisher prints are final.
              Replica prints revise and stay labelled experimental.
            </p>
          </div>
          <div class="ledger-card" style={{ margin: "16px 0" }}>
            <h2>Decomposition (percentage points)</h2>
            <p class="figure-caption">
              All {inflation()?.component_count} components live behind the
              expansion below, sortable by rate, weight, or contribution with
              nulls last. Total {inflation()?.total_contribution_pp.toFixed(3)} pp,
              headline {inflation()?.headline_mom.value} percent per month, kept
              weight {inflation()?.kept_weight_fraction.toFixed(2)}, excluded{" "}
              {inflation()?.excluded_weight_fraction.toFixed(2)}. Each row
              recomputes as weight times rate over 100 within 0.01 pp.
            </p>
            <details class="expander">
              <summary>
                View full {inflation()?.component_count} component table
              </summary>
              <DataTable
                caption="All CPI contributions with rates in percent per month, weights in percent, and contributions in percentage points"
                exportFilename="inflation-contributions.csv"
                columns={[
                  { key: "component", header: "Component", kind: "string" },
                  { key: "rate", header: "Rate", unit: "percent_per_month", kind: "number" },
                  { key: "weight", header: "Weight", unit: "percent", kind: "number" },
                  { key: "contrib", header: "Contribution", unit: "percentage_points", kind: "number" },
                ]}
                rows={contributions().map((row) => ({
                  component: row.component_id,
                  rate: row.monthly_rate_percent.toFixed(3),
                  weight: row.weight_percent.toFixed(2),
                  contrib: row.contribution_pp.toFixed(3),
                }))}
              />
            </details>
          </div>
          <div class="ledger-card" style={{ margin: "16px 0" }}>
            <h2>Tax window flag (2024-12 to 2026-03)</h2>
            <p>
              GST holiday ran December 2024 to February 2025, the tax left in
              March 2025, and restoration lands March 2026. Replica months
              inside 2024-12 to 2026-03 carry the tax window flag and stay
              experimental and revisable.
            </p>
            <p class="figure-caption">
              Publisher headline absorbs the same window as final. The replica
              never smooths through it, it flags it.
            </p>
          </div>
          <div class="ledger-card" style={{ margin: "16px 0" }}>
            <h2>Validation flag</h2>
            <p>
              <span class="badge" data-state={flagState()}>
                {validation()?.flag}
              </span>
            </p>
            <p class="num">
              MAE {validation()?.trim.mae_pp.toFixed(4)} pp vs gate{" "}
              {validation()?.gate_pp} pp over {validation()?.months} months
            </p>
            <p class="figure-caption">
              {validation()?.note} The flag is honest either way and never
              blocks the build: within_gate or exceeds_gate_needs_explanation
              both pass when the flag matches the recompute.
            </p>
          </div>
          <div class="ledger-card" style={{ margin: "16px 0" }}>
            <h2>Curve context</h2>
            <p>
              The funding curve beside this replica is a solved zero curve,
              distinct from input YTM. Inputs price the bonds, zeros come from
              the solved discounts.
            </p>
            <p class="figure-caption">
              Sparse instrument disclosure lists cashflows, dirty prices, and
              reprice errors on the curve page. Degraded curve registers
              withhold repricing until settlement and anchors return. Method{" "}
              {props.snapshot?.observations.curve?.method ?? "method unknown"}.
            </p>
          </div>
          <div class="ledger-card" style={{ margin: "16px 0" }}>
            <h2>Weight vintage and bulk hashes</h2>
            <p class="num">
              expenditure {vintage()?.expenditure_year}, link month{" "}
              {vintage()?.link_month}, provisional {String(vintage()?.provisional)}
            </p>
            <p class="figure-caption">
              <For each={bulkEntries()}>
                {([name, entry]) => (
                  <span>
                    {name} {entry.product_id} sha12 {entry.zip_sha12}.{" "}
                  </span>
                )}
              </For>
              Seasonally adjusted values reused as published. Short sha12 prefixes
              match the leading 12 hex of each stored sha256.
            </p>
          </div>
          <RangeSelector />
          <div class="ledger-card" style={{ margin: "16px 0" }}>
            <h2>History: trim and median in percent per month</h2>
            <Show when={props.historyError}>
              <p class="figure-caption" role="status">
                History unavailable: {props.historyError}. History never blocks the desk.
              </p>
            </Show>
            <Show when={!props.historyError && (props.history?.cpi.length ?? 0) > 0}>
              <Chart
                title="Core inflation history"
                xLabel="Month (UTC)"
                yLabel="Rate (percent_per_month)"
                xKind="date"
                syncKey="inflation"
                note={joinNote(
                  cpiAggregationNote(),
                  percentileCaption(trimSummary(), "percent_per_month")
                )}
                series={[
                  { label: "Trim verified", color: "#2e7f79", points: trimHistory().verified },
                  {
                    label: "Trim backfilled",
                    color: "#9db8b5",
                    dash: [6, 4],
                    points: trimHistory().backfilled,
                  },
                  { label: "Median verified", color: "#1d2f3a", points: medianHistory().verified },
                  {
                    label: "Median backfilled",
                    color: "#a8b5bd",
                    dash: [6, 4],
                    points: medianHistory().backfilled,
                  },
                ]}
              />
              <p class="figure-caption">
                CPI history uses one uniform vintage (2024 expenditure, link
                month 2025-05, provisional). Backfilled months are unverified
                (source derived:backfill_v1) and render dashed and muted.
                Verified months carry snapshot digests. Annual rates compound
                the trailing 12 months within 0.01.
              </p>
            </Show>
          </div>
        </Show>
      </SectionState>
    </section>
  );
}
