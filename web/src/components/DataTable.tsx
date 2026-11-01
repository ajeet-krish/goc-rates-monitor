import { For, Show } from "solid-js";
import type { Unit } from "../lib/types";

export interface TableColumn {
  key: string;
  header: string;
  unit?: Unit;
}

export interface TableRow {
  [key: string]: string;
}

interface Props {
  caption: string;
  columns: TableColumn[];
  rows: TableRow[];
}

/**
 * Display caps: validated payloads are already bounded, but tables
 * render one DOM row per record, so an excessive frame is refused here
 * rather than constructed. Limits mirror the validator collection caps.
 */
export const MAX_TABLE_ROWS = 2000;
export const MAX_TABLE_COLUMNS = 32;

export default function DataTable(props: Props) {
  const excessive = () =>
    props.rows.length > MAX_TABLE_ROWS || props.columns.length > MAX_TABLE_COLUMNS;
  return (
    <div class="table-wrap">
      <Show
        when={!excessive()}
        fallback={
          <p role="alert">
            Table refused: {props.rows.length} rows and {props.columns.length} columns
            exceed the display cap of {MAX_TABLE_ROWS} rows and {MAX_TABLE_COLUMNS} columns
            for {props.caption}. Pick a narrower view.
          </p>
        }
      >
        <table class="kv-table">
          <caption class="sr-only">{props.caption}</caption>
          <thead>
            <tr>
              <For each={props.columns}>
                {(col) => (
                  <th scope="col">
                    {col.header}
                    {col.unit ? <span class="unit-tag">{col.unit}</span> : null}
                  </th>
                )}
              </For>
            </tr>
          </thead>
          <tbody>
            <For each={props.rows}>
              {(row) => (
                <tr>
                  <For each={props.columns}>
                    {(col) => <td class="num">{row[col.key] ?? "NA"}</td>}
                  </For>
                </tr>
              )}
            </For>
          </tbody>
        </table>
      </Show>
    </div>
  );
}
