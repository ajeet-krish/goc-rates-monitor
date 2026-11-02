import { Show } from "solid-js";
import Chart from "../components/Chart";
import DataTable from "../components/DataTable";
import SectionState from "../components/SectionState";
import type { SnapshotDoc } from "../lib/types";
import { missingZeroTenors, zeroCurvePoints } from "../lib/curve-points";
import { fmtBp, fmtYieldPct } from "../lib/format";

interface Props {
  snapshot: SnapshotDoc | null;
  loading: boolean;
  error: string | null;
}

export default function IndexPage(props: Props) {
  const knots = () => props.snapshot?.observations.curve?.knots ?? [];
  const zeroYields = () => props.snapshot?.observations.curve?.zero_yields ?? {};
  const zeroPoints = () => zeroCurvePoints(knots(), zeroYields());
  const missingZeros = () => missingZeroTenors(knots(), zeroYields());
  const twoY = () => knots().find((k) => k.tenor === "2Y")?.yield_percent ?? null;
  const tenY = () => knots().find((k) => k.tenor === "10Y")?.yield_percent ?? null;
  // Spreads envelope: the desk reads the stored 10Y record. Null when
  // the envelope is absent or degraded to a missing marker with a reason.
  const tenYearSpreadBp = () => {
    const section = props.snapshot?.observations.spreads;
    if (!section || section.status !== "ok") return null;
    const match = section.records.find((r) => r.tenor === "10Y");
    return match && Number.isFinite(match.spread_bp) ? match.spread_bp : null;
  };
  // No recompute: the desk reads the stored backtest slope. NA until the
  // pipeline publishes a slope series for this date.
  const slope = () => {
    const backtest = props.snapshot?.observations.backtest;
    if (!backtest || backtest.slopes_bp.length === 0) return null;
    const last = backtest.slopes_bp[backtest.slopes_bp.length - 1];
    return Number.isFinite(last) ? last : null;
  };

  return (
    <section aria-label="Desk today">
      <div class="hero-ledger">
        <div>
          <p class="hero-kicker">Internal research desk: read the curve first</p>
          <h2 class="hero-headline">The live curve is the thesis.</h2>
          <p class="hero-dek">
            Government of Canada benchmark yields to maturity price each bond to
            a dirty target, then bisection solves the zero curve on semiannual
            cashflows. The zero curve is distinct from input YTM: quotes enter,
            solved zeros leave. Flat zero tail past the last anchor, 30Y proxy at
            the long end. Everything else on this desk is commentary on this line.
          </p>
          <SectionState
            loading={props.loading}
            error={props.error}
            empty={!props.loading && !props.error && knots().length === 0}
          >
            <DataTable
              caption="Latest benchmark knot yields in percent yield with solved zeros and discounts as unitless ratios"
              columns={[
                { key: "tenor", header: "Tenor" },
                { key: "yield", header: "Input YTM", unit: "percent_yield" },
                { key: "zero", header: "Zero", unit: "percent_yield" },
                { key: "discount", header: "Discount", unit: "unitless_ratio" },
              ]}
              rows={knots().map((k) => {
                const zero = props.snapshot?.observations.curve?.zero_yields[k.tenor]?.value;
                return {
                  tenor: k.tenor,
                  yield: fmtYieldPct(k.yield_percent),
                  zero: typeof zero === "number" ? fmtYieldPct(zero) : "NA",
                  discount: Number(k.discount).toFixed(6),
                };
              })}
            />
          </SectionState>
        </div>
        <div class="ledger-card">
          <h2>Today on the desk</h2>
          <SectionState
            loading={props.loading}
            error={props.error}
            empty={!props.loading && !props.error && !props.snapshot}
          >
            <table class="kv-table">
              <tbody>
                <tr>
                  <th scope="row">2Y yield</th>
                  <td class="num">
                    {fmtYieldPct(twoY())}
                    <span class="unit-tag">percent_yield</span>
                  </td>
                </tr>
                <tr>
                  <th scope="row">10Y yield</th>
                  <td class="num">
                    {fmtYieldPct(tenY())}
                    <span class="unit-tag">percent_yield</span>
                  </td>
                </tr>
                <tr>
                  <th scope="row">2s10s slope</th>
                  <td class="num">
                    {fmtBp(slope())}
                    <span class="unit-tag">bp</span>
                  </td>
                </tr>
                <tr>
                  <th scope="row">CA-US 10Y</th>
                  <td class="num">
                    {fmtBp(tenYearSpreadBp())}
                    <span class="unit-tag">bp</span>
                  </td>
                </tr>
                <tr>
                  <th scope="row">Carry roll</th>
                  <td class="num">
                    {fmtBp(props.snapshot?.observations.carry?.carry_roll_bp ?? null)}
                    <span class="unit-tag">bp</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <p class="figure-caption">
              Method true_bootstrap_semiannual_log_discount_v1. Solved zero curve
              (is_zero true, is_par_approx false), distinct from input YTM. Long
              end is a 30Y proxy. Sparse instrument disclosure lists cashflows,
              dirty prices, and reprice errors on the curve page. Degraded curve
              registers withhold repricing until settlement and anchors return.
              The 2s10s slope is the stored backtest slope, never recomputed here.
              NA until the pipeline publishes a slope series.
            </p>
          </SectionState>
        </div>
      </div>
      <Show when={!props.loading && !props.error && knots().length > 0}>
        <div class="chart-card" style={{ margin: "16px 0" }}>
          <h2>Curve shape, zero in percent</h2>
          <Show when={missingZeros().length > 0}>
            <p class="figure-caption" role="status">
              Unavailable: solved zero missing for {missingZeros().join(", ")} in
              percent_yield, plotted as a gap and never filled from input YTM.
            </p>
          </Show>
          <Chart
            title="Bootstrapped zero curve"
            xLabel="Tenor (years)"
            yLabel="Yield (percent_yield)"
            series={[
              {
                label: "Zero",
                color: "#2e7f79",
                points: zeroPoints(),
              },
            ]}
          />
        </div>
      </Show>
    </section>
  );
}
