import { For, Show } from "solid-js";
import SectionState from "../components/SectionState";
import type { SnapshotDoc } from "../lib/types";

interface Props {
  snapshot: SnapshotDoc | null;
  loading: boolean;
  error: string | null;
}

function topContributors(snapshot: SnapshotDoc) {
  const rows = snapshot.observations.inflation?.contributions ?? [];
  return [...rows]
    .sort((a, b) => Math.abs(b.contribution_pp) - Math.abs(a.contribution_pp))
    .slice(0, 8);
}

export default function InflationPage(props: Props) {
  const inflation = () => props.snapshot?.observations.inflation ?? null;
  const vintage = () => inflation()?.weight_vintage ?? null;
  const validation = () => inflation()?.validation ?? null;
  const bulkEntries = () => Object.entries(inflation()?.bulk ?? {});
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
              {inflation()?.reference_month}.
            </p>
          </div>
          <div class="ledger-card">
            <h2>Decomposition (percentage points)</h2>
            <table>
              <thead>
                <tr>
                  <th>Component</th>
                  <th>Rate (pct per month)</th>
                  <th>Weight (pct)</th>
                  <th>Contribution (pp)</th>
                </tr>
              </thead>
              <tbody>
                <For each={props.snapshot ? topContributors(props.snapshot) : []}>
                  {(row) => (
                    <tr>
                      <td>{row.component_id}</td>
                      <td>{row.monthly_rate_percent.toFixed(3)}</td>
                      <td>{row.weight_percent.toFixed(2)}</td>
                      <td>{row.contribution_pp.toFixed(3)}</td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
            <p class="figure-caption">
              Top 8 of {inflation()?.component_count} by absolute contribution.
              Total {inflation()?.total_contribution_pp.toFixed(3)} pp, headline{" "}
              {inflation()?.headline_mom.value} percent per month, kept weight{" "}
              {inflation()?.kept_weight_fraction.toFixed(2)}, excluded{" "}
              {inflation()?.excluded_weight_fraction.toFixed(2)}.
            </p>
          </div>
          <div class="ledger-card">
            <h2>Validation flag</h2>
            <p class="num">
              {validation()?.flag}: MAE {validation()?.trim.mae_pp.toFixed(4)} pp vs gate{" "}
              {validation()?.gate_pp} pp over {validation()?.months} months
            </p>
            <p class="figure-caption">{validation()?.note}</p>
          </div>
          <div class="ledger-card">
            <h2>Weight vintage and bulk hashes</h2>
            <p class="num">
              expenditure {vintage()?.expenditure_year}, link month{" "}
              {vintage()?.link_month}, provisional {String(vintage()?.provisional)}
            </p>
            <p class="figure-caption">
              <For each={bulkEntries()}>
                {([name, entry]) => (
                  <span>
                    {name} {entry.product_id} sha {entry.zip_sha12}.{" "}
                  </span>
                )}
              </For>
              Seasonally adjusted values reused as published.
            </p>
          </div>
        </Show>
      </SectionState>
    </section>
  );
}
