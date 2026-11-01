import Chart from "../components/Chart";
import DataTable from "../components/DataTable";
import SectionState from "../components/SectionState";
import type { SnapshotDoc } from "../lib/types";
import { fmtNum, fmtYieldPct } from "../lib/format";

interface Props {
  snapshot: SnapshotDoc | null;
  loading: boolean;
  error: string | null;
}

export default function CurvePage(props: Props) {
  const knots = () => props.snapshot?.observations.curve?.knots ?? [];
  return (
    <section aria-label="Curve">
      <p class="hero-kicker">Curve: par approximation, stated limits</p>
      <h2 class="hero-headline">Knots, discounts, zero yields.</h2>
      <p class="hero-dek">
        Benchmark YTM inputs treated as par. Discount proxy D equals 1 over (1 plus
        y over 2) to the 2T. Log discounts interpolate linearly. Ends hold the
        nearest yield flat. Verify reprices knots within 1.0 bp (V13).
      </p>
      <SectionState
        loading={props.loading}
        error={props.error}
        empty={!props.loading && !props.error && knots().length === 0}
      >
        <div class="chart-card">
          <h2>Yield curve, yield in percent_yield</h2>
          <Chart
            title="Curve yields"
            xLabel="Tenor (years)"
            yLabel="Yield (percent_yield)"
            series={[
              {
                label: "Par approx yield",
                color: "#2e7f79",
                points: knots().map((k) => ({ x: k.tenor_years, y: k.yield_percent })),
              },
            ]}
          />
        </div>
        <div class="chart-card" style={{ margin: "16px 0" }}>
          <h2>Discount function, unitless_ratio</h2>
          <Chart
            title="Discounts"
            xLabel="Tenor (years)"
            yLabel="Discount (unitless_ratio)"
            series={[
              {
                label: "Discount",
                color: "#1d2f3a",
                points: knots().map((k) => ({ x: k.tenor_years, y: k.discount })),
              },
            ]}
          />
        </div>
        <DataTable
          caption="Curve knots with yields in percent_yield and discounts as unitless ratios"
          columns={[
            { key: "tenor", header: "Tenor" },
            { key: "years", header: "Years", unit: "duration_years" },
            { key: "yield", header: "Yield", unit: "percent_yield" },
            { key: "discount", header: "Discount", unit: "unitless_ratio" },
          ]}
          rows={knots().map((k) => ({
            tenor: k.tenor,
            years: fmtNum(k.tenor_years, 1),
            yield: fmtYieldPct(k.yield_percent),
            discount: fmtNum(k.discount, 6),
          }))}
        />
        <p class="figure-caption">
          {props.snapshot?.observations.curve?.long_proxy_note ?? "Long end note missing."}{" "}
          Method {props.snapshot?.observations.curve?.method ?? "unknown"}.
        </p>
      </SectionState>
    </section>
  );
}
