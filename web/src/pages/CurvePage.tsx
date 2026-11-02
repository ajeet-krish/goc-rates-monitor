import { Show } from "solid-js";
import Chart from "../components/Chart";
import DataTable from "../components/DataTable";
import SectionState from "../components/SectionState";
import type { HistoryDoc, SnapshotDoc } from "../lib/types";
import { missingZeroTenors, zeroCurvePoints } from "../lib/curve-points";
import { historyRangeLabel, splitHistory } from "../lib/history-series";
import { fmtNum, fmtYieldPct } from "../lib/format";

interface Props {
  snapshot: SnapshotDoc | null;
  loading: boolean;
  error: string | null;
  history?: HistoryDoc | null;
  historyLoading?: boolean;
  historyError?: string | null;
}

export default function CurvePage(props: Props) {
  const curve = () => props.snapshot?.observations.curve;
  const knots = () => curve()?.knots ?? [];
  const instruments = () => curve()?.instruments ?? [];
  const anchors = () => curve()?.anchors ?? [];
  const settlement = () => curve()?.settlement_date ?? null;
  const sparse = () => instruments().length === 0 || anchors().length === 0 || settlement() === null;
  const zeroPoints = () => zeroCurvePoints(knots(), curve()?.zero_yields ?? {});
  const missingZeros = () => missingZeroTenors(knots(), curve()?.zero_yields ?? {});
  const anchorDate = (row: { date?: string; payment_date?: string }) =>
    row.payment_date ?? row.date ?? "date missing";
  const twoY = () => splitHistory(props.history, (_d, _i, row) => row.yields_percent["2Y"]);
  const tenY = () => splitHistory(props.history, (_d, _i, row) => row.yields_percent["10Y"]);
  const slope210 = () => splitHistory(props.history, (_d, _i, row) => row.slopes_bp["2Y_10Y"]);
  return (
    <section aria-label="Curve">
      <p class="hero-kicker">Curve: true zero curve, bootstrapped</p>
      <h2 class="hero-headline">Solved zeros, not quoted yields.</h2>
      <p class="hero-dek">
        The zero curve is distinct from input YTM. Benchmark yields to maturity
        price each bond to a dirty target per 100 face, then bisection solves
        each discount anchor in maturity order within 1.0 bp (V13, V24, V25).
        Knots use residual ACT over 365 years from settlement. Log discounts
        interpolate linearly between anchors, with a flat zero tail past the
        last anchor.
      </p>
      <SectionState
        loading={props.loading}
        error={props.error}
        empty={!props.loading && !props.error && knots().length === 0}
      >
        <p class="figure-caption">
          Settlement {settlement() ?? "settlement missing"}. Method{" "}
          {curve()?.method ?? "unknown"} (is_zero {String(curve()?.is_zero ?? "unknown")},
          is_par_approx {String(curve()?.is_par_approx ?? "unknown")}). Zero yields
          are solved semiannual zeros, never requoted inputs.
        </p>
        <Show when={sparse()}>
          <p class="figure-caption" role="status">
            Degraded: sparse instrument disclosure. Knots render while the
            instrument or anchor register is absent, so repricing stays
            unverified on this page until the pipeline republishes settlement,
            instruments, and anchors.
          </p>
        </Show>
        <div class="chart-card">
          <h2>Zero curve, yield in percent_yield</h2>
          <Show when={missingZeros().length > 0}>
            <p class="figure-caption" role="status">
              Unavailable: solved zero missing for {missingZeros().join(", ")} in
              percent_yield, plotted as a gap and never filled from input YTM.
            </p>
          </Show>
          <Chart
            title="Zero curve"
            xLabel="Tenor (years)"
            yLabel="Yield (percent_yield)"
            series={[
              {
                label: "Zero yield",
                color: "#2e7f79",
                points: zeroPoints(),
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
          caption="Curve knots with residual years in duration_years, input YTM in percent_yield, and discounts as unitless ratios"
          columns={[
            { key: "tenor", header: "Tenor" },
            { key: "years", header: "Years", unit: "duration_years" },
            { key: "yield", header: "Input YTM", unit: "percent_yield" },
            { key: "zero", header: "Zero", unit: "percent_yield" },
            { key: "discount", header: "Discount", unit: "unitless_ratio" },
          ]}
          rows={knots().map((k) => {
            const zero = curve()?.zero_yields[k.tenor]?.value;
            return {
              tenor: k.tenor,
              years: fmtNum(k.tenor_years, 2),
              yield: fmtYieldPct(k.yield_percent),
              zero: typeof zero === "number" ? fmtYieldPct(zero) : "NA",
              discount: fmtNum(k.discount, 6),
            };
          })}
        />
        <Show when={!sparse()}>
          <DataTable
            caption="Sparse instrument disclosure: tenor, maturity, coupon, cashflows, dirty price, reprice error"
            columns={[
              { key: "tenor", header: "Tenor" },
              { key: "maturity", header: "Maturity" },
              { key: "coupon", header: "Coupon", unit: "percent" },
              { key: "flows", header: "Cashflows", unit: "count" },
              { key: "price", header: "Dirty price", unit: "price_units_per_100_face" },
              { key: "reprice", header: "Reprice error", unit: "bp" },
            ]}
            rows={instruments().map((row) => ({
              tenor: row.tenor,
              maturity: row.maturity_date,
              coupon: fmtNum(row.coupon_percent, 2),
              flows: String(row.cashflow_count),
              price: fmtNum(row.dirty_price.value, 2),
              reprice: fmtNum(row.reprice_error_bp.value, 2),
            }))}
          />
          <DataTable
            caption="Solved discount anchors with years in duration_years and discounts as unitless ratios"
            columns={[
              { key: "date", header: "Anchor date" },
              { key: "years", header: "Years", unit: "duration_years" },
              { key: "discount", header: "Discount", unit: "unitless_ratio" },
            ]}
            rows={anchors().map((row) => ({
              date: anchorDate(row),
              years: fmtNum(row.years_from_settlement, 2),
              discount: fmtNum(row.discount, 6),
            }))}
          />
        </Show>
        <p class="figure-caption">
          {curve()?.long_proxy_note ?? "Long end note missing."} Method{" "}
          {curve()?.method ?? "unknown"}.
        </p>
        <div class="chart-card" style={{ margin: "16px 0" }}>
          <h2>History: 2Y and 10Y yields in percent</h2>
          <Show when={props.historyError}>
            <p class="figure-caption" role="status">
              History unavailable: {props.historyError}. Snapshot values above
              stay authoritative. History never blocks the desk.
            </p>
          </Show>
          <Show when={!props.historyError && (props.history?.daily.length ?? 0) > 0}>
            <Chart
              title="Benchmark yield history"
              xLabel="History order"
              yLabel="Yield (percent)"
              series={[
                { label: "2Y verified", color: "#2e7f79", points: twoY().verified },
                {
                  label: "2Y backfilled",
                  color: "#9db8b5",
                  dash: [6, 4],
                  points: twoY().backfilled,
                },
                { label: "10Y verified", color: "#1d2f3a", points: tenY().verified },
                {
                  label: "10Y backfilled",
                  color: "#a8b5bd",
                  dash: [6, 4],
                  points: tenY().backfilled,
                },
              ]}
            />
            <p class="figure-caption">
              Range {historyRangeLabel(props.history)}. Backfilled spans are
              unverified (source derived:backfill_v1) and render dashed and
              muted. Verified spans carry snapshot digests (source
              derived:history_verified_v1). History loads independently and
              never blocks the desk.
            </p>
          </Show>
          <Show when={!props.historyError && (props.history?.daily.length ?? 0) === 0}>
            <p class="figure-caption" role="status">
              {props.historyLoading ? "History is loading." : "History is empty for this build."}
            </p>
          </Show>
        </div>
        <div class="chart-card" style={{ margin: "16px 0" }}>
          <h2>History: 2s10s slope in bp</h2>
          <Show when={!props.historyError && (props.history?.daily.length ?? 0) > 0}>
            <Chart
              title="2s10s slope history"
              xLabel="History order"
              yLabel="Slope (basis_points)"
              series={[
                { label: "Slope verified", color: "#2e7f79", points: slope210().verified },
                {
                  label: "Slope backfilled",
                  color: "#9db8b5",
                  dash: [6, 4],
                  points: slope210().backfilled,
                },
              ]}
            />
            <p class="figure-caption">
              Slopes recompute as (10Y minus 2Y) times 100 within 1.0 bp.
              Backfilled spans stay dashed and muted until a snapshot seals them.
            </p>
          </Show>
        </div>
      </SectionState>
    </section>
  );
}
