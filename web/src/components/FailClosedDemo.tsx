import { createEffect, createSignal, Show } from "solid-js";

/**
 * Fail closed demo: a local only toggle that shows synthetic NA rows.
 * Values are hardcoded display strings, never derived, never checked,
 * and never written back. Changing asof resets the toggle to off.
 */
export default function FailClosedDemo(props: { asof: string | null }) {
  const [open, setOpen] = createSignal(false);
  createEffect(() => {
    void props.asof;
    setOpen(false);
  });
  return (
    <div class="ledger-card" aria-label="Fail closed demo">
      <h2>Fail closed demo (synthetic, no check id)</h2>
      <p>
        This toggle renders hardcoded NA rows for{" "}
        <span class="num">{props.asof ?? "date missing"}</span>. Demo values
        carry no V id, enter no snapshot, and mutate no store.
      </p>
      <button
        class="btn btn-secondary"
        type="button"
        aria-expanded={open() ? "true" : "false"}
        onClick={() => setOpen((v) => !v)}
      >
        {open() ? "Hide demo rows" : "Show demo rows"}
      </button>
      <Show when={open()}>
        <div class="alert" role="note" aria-label="Demo blocked notice">
          <h3>Derived displays blocked</h3>
          <p>
            Demo mode stands in for a failed check. Every derived value below
            stays NA until every named check passes.
          </p>
        </div>
        <table>
          <caption>DEMO sample, synthetic NA values (unit: mixed)</caption>
          <thead>
            <tr>
              <th scope="col">Tenor</th>
              <th scope="col">Day over day (bp)</th>
              <th scope="col">Gate</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>2Y</td>
              <td class="num">NA</td>
              <td>demo_break (not a pipeline gate)</td>
            </tr>
            <tr>
              <td>10Y</td>
              <td class="num">NA</td>
              <td>demo_break (not a pipeline gate)</td>
            </tr>
          </tbody>
        </table>
        <p class="figure-caption">
          DEMO rows are display strings only. Close the toggle or change the
          date to clear them.
        </p>
      </Show>
    </div>
  );
}
