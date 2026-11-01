import { For, Show } from "solid-js";
import Chart from "../components/Chart";
import DataTable from "../components/DataTable";
import SectionState from "../components/SectionState";
import type { SnapshotDoc } from "../lib/types";
import { fmtBp, fmtShortSha } from "../lib/format";

interface Props {
  snapshot: SnapshotDoc | null;
  loading: boolean;
  error: string | null;
}

function gateReason(gate: string): string {
  if (gate === "comparable") return "Clean compare, both legs present.";
  if (gate === "switch_break") return "Suppressed for a switch in window, no splice.";
  if (gate === "calendar_gap") return "Kept across a calendar gap, flagged.";
  if (gate === "missing_prev") return "No previous leg, delta stays NA.";
  if (gate === "insufficient_history") return "Short history, delta stays NA.";
  return "Unknown gate, treated as NA.";
}

function couponText(value: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "NA";
  return value.toFixed(3) + " pct";
}

export default function BreaksPage(props: Props) {
  const breaks = () => props.snapshot?.observations.breaks ?? null;
  const backtest = () => props.snapshot?.observations.backtest;
  const pts = () => {
    const b = backtest();
    if (!b || !Array.isArray(b.slopes_bp)) return [];
    return b.slopes_bp.map((s, i) => ({ x: i, y: s }));
  };
  return (
    <section aria-label="Breaks">
      <p class="hero-kicker">Breaks: switches suppress, never splice</p>
      <h2 class="hero-headline">A named reason for every NA.</h2>
      <p class="hero-dek">
        Method <span class="num">benchmark_switch_dod_gate_v1</span> reads the
        pinned switch feed and gates each tenor day over day move as comparable,
        switch_break, calendar_gap, missing_prev, or insufficient_history.
        Suppressed deltas stay null with their gate named beside them.
      </p>
      <SectionState
        loading={props.loading}
        error={props.error}
        empty={!props.loading && !props.error && !breaks()}
      >
        <Show when={breaks() !== null}>
          <div class="ledger-card">
            <h2>
              Switch register (feed {breaks()?.feed_source}, vintage{" "}
              {breaks()?.feed_vintage}, sha {fmtShortSha(breaks()?.feed_sha256)})
            </h2>
            <p class="figure-caption">
              Joint dates roll forward to the first joint business day on or
              after the effective date. Threshold {breaks()?.threshold_bp}{" "}
              {breaks()?.threshold_unit} marks a break that needs explanation.
            </p>
            <table>
              <caption>Benchmark switch events in joint date order</caption>
              <thead>
                <tr>
                  <th scope="col">Tenor</th>
                  <th scope="col">Effective</th>
                  <th scope="col">Joint</th>
                  <th scope="col">Incoming</th>
                  <th scope="col">Outgoing</th>
                </tr>
              </thead>
              <tbody>
                <For each={breaks()?.events ?? []}>
                  {(event) => (
                    <tr>
                      <td class="num">{event.tenor}</td>
                      <td class="num">{event.effective_date}</td>
                      <td class="num">{event.effective_joint_date}</td>
                      <td class="num">
                        {event.incoming_maturity ?? "NA"} at{" "}
                        {couponText(event.incoming_coupon_percent)}
                      </td>
                      <td class="num">
                        {event.outgoing_maturity ?? "NA"} at{" "}
                        {couponText(event.outgoing_coupon_percent)}
                      </td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
          </div>
          <div class="ledger-card" style={{ margin: "16px 0" }}>
            <h2>Gate table (print {breaks()?.print_date})</h2>
            <table>
              <caption>Day over day moves with gates, nulls name their reason</caption>
              <thead>
                <tr>
                  <th scope="col">Tenor</th>
                  <th scope="col">Prev to current</th>
                  <th scope="col">DoD (bp)</th>
                  <th scope="col">Gate</th>
                  <th scope="col">Reason</th>
                </tr>
              </thead>
              <tbody>
                <For each={breaks()?.records ?? []}>
                  {(record) => (
                    <tr>
                      <td class="num">{record.tenor}</td>
                      <td class="num">
                        {record.prev_date} to {record.current_date}
                      </td>
                      <td class="num">{fmtBp(record.dod_bp)}</td>
                      <td>
                        <span
                          class="badge"
                          data-state={record.dod_bp === null ? "warn" : "ok"}
                        >
                          {record.gate}
                        </span>
                      </td>
                      <td>{gateReason(record.gate)}</td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
            <p class="figure-caption">
              Quantities carry unit {breaks()?.records[0]?.dod_unit ?? "basis_points"}{" "}
              with source derived:dod_gate (observed with numbers, missing with
              nulls). Switch flags and calendar flags are booleans, history
              counts are integers.
            </p>
          </div>
          <div class="ledger-card" style={{ margin: "16px 0" }}>
            <h2>Secondary: backtest sketch (separate from breaks)</h2>
            <p class="figure-caption">
              Rule <span class="num">{backtest()?.rule ?? "rule missing"}</span>{" "}
              with {(backtest()?.dates ?? []).length} obs. Total PnL{" "}
              {fmtBp(backtest()?.total_pnl_bp ?? null)} (unit: bp). Gross by
              construction, costs disclosed as zero.
            </p>
            <Chart
              title="Backtest slopes"
              xLabel="Observation index"
              yLabel="Slope (bp)"
              series={[{ label: "2s10s", color: "#a44a2a", points: pts() }]}
            />
            <div style={{ margin: "16px 0" }}>
              <DataTable
                caption="Backtest summary in bp"
                columns={[
                  { key: "rule", header: "Rule" },
                  { key: "obs", header: "Obs" },
                  { key: "pnl", header: "Total PnL", unit: "bp" },
                ]}
                rows={[
                  {
                    rule: String(backtest()?.rule ?? "NA"),
                    obs: String(backtest()?.dates?.length ?? 0),
                    pnl: fmtBp(backtest()?.total_pnl_bp ?? null),
                  },
                ]}
              />
            </div>
          </div>
        </Show>
      </SectionState>
    </section>
  );
}
