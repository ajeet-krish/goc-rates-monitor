import SectionState from "../components/SectionState";
import type { SnapshotDoc } from "../lib/types";

interface Props {
  snapshot: SnapshotDoc | null;
  loading: boolean;
  error: string | null;
}

export default function InflationPage(props: Props) {
  const reused = () => props.snapshot?.observations.statcan?.seasonally_adjusted_reused_as_is;
  return (
    <section aria-label="Inflation">
      <p class="hero-kicker">Inflation: pending Phase 4 engine</p>
      <h2 class="hero-headline">Headline is final. Core is vintage.</h2>
      <p class="hero-dek">
        StatCan seasonally adjusted values are reused as published, with no extra
        transformation. Core trims and medians are revisable vintages. This page
        stages the table pins until the Phase 4 trim and median engine lands.
      </p>
      <SectionState loading={props.loading} error={props.error} empty={false}>
        <div class="ledger-card">
          <h2>StatCan reuse flag</h2>
          <p class="num">seasonally_adjusted_reused_as_is: {String(reused() ?? "NA")}</p>
          <p class="figure-caption">
            Tables 18-10-0004-01, 18-10-0256-01, 18-10-0259-01, 18-10-0007-01. Weight
            vintage pinned per snapshot.
          </p>
        </div>
      </SectionState>
    </section>
  );
}
