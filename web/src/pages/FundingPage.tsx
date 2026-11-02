import { Show } from "solid-js";
import Chart from "../components/Chart";
import DataTable from "../components/DataTable";
import SectionState from "../components/SectionState";
import type { SnapshotDoc, SpreadTenor } from "../lib/types";
import { ALLOWED_SPREAD_TENORS } from "../lib/validate";
import { fmtBp, fmtNum } from "../lib/format";

interface Props {
  snapshot: SnapshotDoc | null;
  loading: boolean;
  error: string | null;
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
        points: dates.map((date, i) => {
          const match = spreads().find((r) => r.date === date && r.tenor === tenor);
          return { x: i, y: match ? match.spread_bp : null };
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
  return (
    <section aria-label="Funding">
      <p class="hero-kicker">Funding: CORRA, spreads, carry, risk</p>
      <h2 class="hero-headline">What it costs to hold the trade.</h2>
      <p class="hero-dek">
        CORRA value dates lag publication by one business day. CA-US spreads join
        on common business days with no forward fill. Carry is horizon 0.25 years,
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
          </p>
        </Show>
        <Show when={spreadsAvailable()}>
          <div class="chart-card" style={{ margin: "16px 0" }}>
            <h2>CA-US spread by tenor, spread in bp</h2>
            <Chart
              title="Canada minus US spread by tenor"
              xLabel="Date order"
              yLabel="Spread (bp)"
              series={spreadSeries()}
            />
          </div>
          <DataTable
            caption="CA-US spreads in bp on shared dates, by tenor"
            columns={[
              { key: "date", header: "Date" },
              { key: "tenor", header: "Tenor" },
              { key: "ca", header: "CA yield", unit: "percent_yield" },
              { key: "us", header: "US yield", unit: "percent_yield" },
              { key: "spread", header: "Spread", unit: "bp" },
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
      </SectionState>
    </section>
  );
}
