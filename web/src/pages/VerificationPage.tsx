import { Show } from "solid-js";
import DataTable from "../components/DataTable";
import SectionState from "../components/SectionState";
import type { VerifyReport } from "../lib/types";

interface Props {
  verify: VerifyReport | null;
  loading: boolean;
  error: string | null;
}

export default function VerificationPage(props: Props) {
  return (
    <section aria-label="Verification">
      <Show
        when={props.verify}
        fallback={<p class="hero-kicker">Verification: checks pending</p>}
      >
        <p class="hero-kicker">
          Verification: {props.verify?.checks.length ?? 0} checks at {props.verify?.tolerance_bp}{" "}
          {props.verify?.tolerance_unit}
        </p>
      </Show>
      <h2 class="hero-headline">Fail closed, with names.</h2>
      <Show
        when={props.verify}
        fallback={
          <p class="hero-dek">
            Every check names its unit. The tolerance comes from the verify report.
            A single failure blocks derived displays and the build.
          </p>
        }
      >
        <p class="hero-dek">
          Every check names its unit. Tolerance is {props.verify?.tolerance_bp}{" "}
          {props.verify?.tolerance_unit}. A single failure blocks derived displays
          and the build.
        </p>
      </Show>
      <SectionState
        loading={props.loading}
        error={props.error}
        empty={!props.loading && !props.error && !props.verify}
      >
        <p>
          <span
            class="badge"
            data-state={props.verify?.passed ? "pass" : "fail"}
          >
            {props.verify?.passed ? "verify pass" : "verify fail"}:{" "}
            {props.verify?.passed_count ?? 0} of {(props.verify?.checks.length ?? 0)}
          </span>
        </p>
        <DataTable
          caption="Verification checks with pass state and detail including units"
          columns={[
            { key: "id", header: "Check" },
            { key: "state", header: "State" },
            { key: "detail", header: "Detail" },
          ]}
          rows={(props.verify?.checks ?? []).map((c) => ({
            id: c.id,
            state: c.passed ? "pass" : "FAIL",
            detail: c.detail,
          }))}
        />
      </SectionState>
    </section>
  );
}
