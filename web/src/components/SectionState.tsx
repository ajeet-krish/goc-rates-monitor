import { Match, Switch } from "solid-js";

interface Props {
  loading: boolean;
  error: string | null;
  empty: boolean;
  children: unknown;
}

export default function SectionState(props: Props) {
  return (
    <Switch>
      <Match when={props.loading}>
        <p role="status">Loading ledger entry. No chart until the snapshot arrives.</p>
      </Match>
      <Match when={props.error !== null}>
        <div class="alert" role="alert">
          <h3>Snapshot unavailable</h3>
          <p>{props.error}</p>
          <p>Charts and deltas show NA with reason. Retry or pick another date.</p>
        </div>
      </Match>
      <Match when={props.empty}>
        <div class="alert alert-warn" role="status">
          <h3>No rows for this date</h3>
          <p>The snapshot parsed but this section is empty. Provenance stays visible.</p>
        </div>
      </Match>
      <Match when={true}>
        <>{props.children as never}</>
      </Match>
    </Switch>
  );
}
