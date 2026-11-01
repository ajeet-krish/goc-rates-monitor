import Chart from "../components/Chart";
import DataTable from "../components/DataTable";
import SectionState from "../components/SectionState";
import type { SnapshotDoc } from "../lib/types";
import { fmtBp } from "../lib/format";

interface Props {
  snapshot: SnapshotDoc | null;
  loading: boolean;
  error: string | null;
}

export default function BreaksPage(props: Props) {
  const backtest = () => props.snapshot?.observations.backtest;
  const pts = () => {
    const b = backtest();
    if (!b) return [];
    return b.slopes_bp.map((s, i) => ({ x: i, y: s }));
  };
  return (
    <section aria-label="Breaks">
      <p class="hero-kicker">Breaks: fixed rule, gross moves only</p>
      <h2 class="hero-headline">One rule, no story.</h2>
      <p class="hero-dek">
        Rule <span class="num">2s10s_z252_meanrev_v1</span>: trailing 252 slopes
        excluding the current day, entry at 1.0 z, next day DV01 neutral PnL. No
        Sharpe, no live signal claim. Costs disclosed as zero.
      </p>
      <SectionState
        loading={props.loading}
        error={props.error}
        empty={!props.loading && !props.error && !backtest()}
      >
        <div class="chart-card">
          <h2>2s10s slope history, slope in bp</h2>
          <Chart
            title="Backtest slopes"
            xLabel="Observation index"
            yLabel="Slope (bp)"
            series={[{ label: "2s10s", color: "#a44a2a", points: pts() }]}
          />
          <p class="figure-caption">
            Rust is reserved for breaks. Total PnL{" "}
            {fmtBp(backtest()?.total_pnl_bp ?? null)} (unit: bp).
          </p>
        </div>
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
                obs: String(backtest()?.dates.length ?? 0),
                pnl: fmtBp(backtest()?.total_pnl_bp ?? null),
              },
            ]}
          />
        </div>
      </SectionState>
    </section>
  );
}
