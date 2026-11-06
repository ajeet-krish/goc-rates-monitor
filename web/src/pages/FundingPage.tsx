import { Show } from "solid-js";
import Chart from "../components/Chart";
import DataTable from "../components/DataTable";
import RangeSelector from "../components/RangeSelector";
import SectionState from "../components/SectionState";
import type { HistoryDoc, SnapshotDoc, SpreadTenor } from "../lib/types";
import { ALLOWED_SPREAD_TENORS } from "../lib/validate";
import { historyRangeLabel } from "../lib/history-series";
import { dateToEpochSec } from "../lib/history";
import {
  aggregationNote,
  joinNote,
  percentileCaption,
  windowSeries,
} from "../lib/history-window";
import { rangeKey } from "../lib/history-range";
import { percentileSummary } from "../lib/percentiles";
import { fmtBp, fmtNum } from "../lib/format";

interface Props {
  snapshot: SnapshotDoc | null;
  loading: boolean;
  error: string | null;
  history?: HistoryDoc | null;
  historyLoading?: boolean;
  historyError?: string | null;
}

const TENOR_ORDER: ReadonlyArray<SpreadTenor> = ALLOWED_SPREAD_TENORS;
const TENOR_COLORS: Record<string, string> = {
  "2Y": "#2e7f79",
  "5Y": "#8a6d3b",
  "10Y": "#3b5b8a",
  "30Y": "#7a3b5b",
};

export default function FundingPage(props: Props) {
  const spreadSection = () => props.snapshot?.observations.spreads;
  const spreads = () => spreadSection()?.records ?? [];
  // Fail closed: an absent envelope withholds chart and table exactly
  // like an explicit missing marker. No silent empty frame.
  const spreadsAvailable = () =>
    spreadSection()?.status === "ok" && spreads().length > 0;
  const spreadsReason = () => spreadSection()?.reason ?? "no spreads envelope published";
  const spreadDates = () => [...new Set(spreads().map((r) => r.date))].sort();
  const spreadSeries = () => {
    const dates = spreadDates();
    return TENOR_ORDER.filter((tenor) => spreads().some((r) => r.tenor === tenor)).map(
      (tenor) => ({
        label: tenor + " spread",
        color: TENOR_COLORS[tenor] ?? "#2e7f79",
        points: dates.map((date) => {
          const match = spreads().find((r) => r.date === date && r.tenor === tenor);
          return { x: dateToEpochSec(date), y: match ? match.spread_bp : null };
        }),
      })
    );
  };
  const spreadRows = () =>
    [...spreads()].sort((a, b) => {
      if (a.date !== b.date) return a.date < b.date ? -1 : 1;
      return TENOR_ORDER.indexOf(a.tenor) - TENOR_ORDER.indexOf(b.tenor);
    });
  const carry = () => props.snapshot?.observations.carry;
  const risk = () => props.snapshot?.observations.risk;
  // Read inside the reactive scope so a range change re-renders the chart.
  const range = () => rangeKey();
  const spread10YHistory = () =>
    windowSeries(props.history, range(), (row) => row.spreads_bp["10Y"]);
  const spreadSummary = () => percentileSummary(spread10YHistory().windowPoints);
  return (
    <section aria-label="Funding">
      <p class="hero-kicker">Funding: CORRA, spreads, carry, risk</p>
      <h2 class="hero-headline">What it costs to hold the trade.</h2>
      <p class="hero-dek">
        CORRA value dates lag publication by one business day. CA-US spreads join
        on common business days with no forward fill. The zero curve is distinct
        from input YTM: carry and risk read solved semiannual zeros from the
        bootstrapped curve, never requoted yields. Carry is horizon 0.25 years,
        ex coupon and ex funding, on an unchanged curve. DV01 is closed form
        semiannual per million.
      </p>
      <SectionState
        loading={props.loading}
        error={props.error}
        empty={!props.loading && !props.error && !props.snapshot}
      >
        <div class="grid-two">
          <div class="ledger-card">
            <h2>Carry and risk</h2>
            <table class="kv-table">
              <tbody>
                <tr>
                  <th scope="row">Carry roll</th>
                  <td class="num">
                    {fmtBp(carry()?.carry_roll_bp)}
                    <span class="unit-tag">bp</span>
                  </td>
                </tr>
                <tr>
                  <th scope="row">Horizon</th>
                  <td class="num">
                    {fmtNum(carry()?.horizon_years, 2)}
                    <span class="unit-tag">duration_years</span>
                  </td>
                </tr>
                <tr>
                  <th scope="row">DV01</th>
                  <td class="num">
                    {fmtNum(risk()?.dv01_per_million, 2)}
                    <span class="unit-tag">dv01_per_million</span>
                  </td>
                </tr>
                <tr>
                  <th scope="row">Mod duration</th>
                  <td class="num">
                    {fmtNum(risk()?.modified_duration_years, 4)}
                    <span class="unit-tag">duration_years</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="ledger-card">
            <h2>CORRA note</h2>
            <table class="kv-table">
              <tbody>
                <tr>
                  <th scope="row">Value date</th>
                  <td class="num">{props.snapshot?.observations.corra?.value_date ?? "NA"}</td>
                </tr>
                <tr>
                  <th scope="row">Pub date</th>
                  <td class="num">{props.snapshot?.observations.corra?.pub_date ?? "NA"}</td>
                </tr>
                <tr>
                  <th scope="row">Role</th>
                  <td class="num">{props.snapshot?.observations.corra?.date_role ?? "NA"}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <Show when={!spreadsAvailable()}>
          <p class="figure-caption" role="status">
            Spreads unavailable: {spreadsReason()}.
            CA-US spread by tenor, carry chart, and table are withheld until the US leg returns.
            Degraded spreads stay explicit with a reason, never a silent gap.
          </p>
        </Show>
        <Show
          when={
            (props.snapshot?.observations.curve?.instruments ?? []).length === 0 ||
            !props.snapshot?.observations.curve?.settlement_date
          }
        >
          <p class="figure-caption" role="status">
            Degraded: sparse instrument disclosure on the curve register. Carry
            and risk still read the stored zero section, but per bond repricing
            is unverified until settlement, instruments, and anchors republish.
          </p>
        </Show>
        <Show when={spreadsAvailable()}>
          <div class="chart-card" style={{ margin: "16px 0" }}>
            <h2>CA-US spread by tenor, spread in bp</h2>
            <Chart
              title="Canada minus US spread by tenor"
              xLabel="Date (UTC)"
              yLabel="Spread (bp)"
              xKind="date"
              syncKey="funding"
              series={spreadSeries()}
            />
          </div>
          <DataTable
            caption="CA-US spreads in bp on shared dates, by tenor"
            exportFilename="funding-spreads.csv"
            columns={[
              { key: "date", header: "Date", kind: "date" },
              { key: "tenor", header: "Tenor", kind: "string" },
              { key: "ca", header: "CA yield", unit: "percent_yield", kind: "number" },
              { key: "us", header: "US yield", unit: "percent_yield", kind: "number" },
              { key: "spread", header: "Spread", unit: "bp", kind: "number" },
            ]}
            rows={spreadRows().map((r) => ({
              date: r.date,
              tenor: r.tenor,
              ca: fmtNum(r.ca_yield_percent, 2),
              us: fmtNum(r.us_yield_percent, 2),
              spread: fmtBp(r.spread_bp),
            }))}
          />
        </Show>
        <RangeSelector />
        <div class="chart-card" style={{ margin: "16px 0" }}>
          <h2>History: 10Y CA-US spread in bp</h2>
          <Show when={props.historyError}>
            <p class="figure-caption" role="status">
              History unavailable: {props.historyError}. History never blocks the desk.
            </p>
          </Show>
          <Show when={!props.historyError && (props.history?.daily.length ?? 0) > 0}>
            <Chart
              title="10Y spread history"
              xLabel="Date (UTC)"
              yLabel="Spread (basis_points)"
              xKind="date"
              syncKey="funding"
              note={joinNote(
                aggregationNote(spread10YHistory().granularity),
                percentileCaption(spreadSummary(), "basis_points")
              )}
              series={[
                {
                  label: "10Y spread verified",
                  color: "#3b5b8a",
                  points: spread10YHistory().verified,
                },
                {
                  label: "10Y spread backfilled",
                  color: "#a8b5bd",
                  dash: [6, 4],
                  points: spread10YHistory().backfilled,
                },
              ]}
            />
            <p class="figure-caption">
              Range {historyRangeLabel(props.history)}. Backfilled spans are
              unverified (source derived:backfill_v1) and render dashed and
              muted. Verified spans carry snapshot digests. Missing US legs stay
              null with status missing or partial, never filled.
            </p>
          </Show>
        </div>
      </SectionState>
    </section>
  );
}
