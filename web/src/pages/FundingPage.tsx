import Chart from "../components/Chart";
import DataTable from "../components/DataTable";
import SectionState from "../components/SectionState";
import type { SnapshotDoc } from "../lib/types";
import { fmtBp, fmtNum } from "../lib/format";

interface Props {
  snapshot: SnapshotDoc | null;
  loading: boolean;
  error: string | null;
}

export default function FundingPage(props: Props) {
  const spreads = () => props.snapshot?.observations.spreads ?? [];
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
        <div class="chart-card" style={{ margin: "16px 0" }}>
          <h2>CA-US spread, spread in bp</h2>
          <Chart
            title="Canada minus US spread"
            xLabel="Record index"
            yLabel="Spread (bp)"
            series={[
              {
                label: "Spread",
                color: "#2e7f79",
                points: spreads().map((r, i) => ({ x: i, y: r.spread_bp })),
              },
            ]}
          />
        </div>
        <DataTable
          caption="CA-US spreads in bp on shared dates"
          columns={[
            { key: "date", header: "Date" },
            { key: "ca", header: "CA yield", unit: "percent_yield" },
            { key: "us", header: "US yield", unit: "percent_yield" },
            { key: "spread", header: "Spread", unit: "bp" },
          ]}
          rows={spreads().map((r) => ({
            date: r.date,
            ca: fmtNum(r.ca_yield_percent, 2),
            us: fmtNum(r.us_yield_percent, 2),
            spread: fmtBp(r.spread_bp),
          }))}
        />
      </SectionState>
    </section>
  );
}
