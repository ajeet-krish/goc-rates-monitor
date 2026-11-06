import { createMemo, createSignal, For, Show } from "solid-js";
import type { Unit } from "../lib/types";
import {
  inferKind,
  nextSortState,
  sortRows,
  type SortState,
} from "../lib/table-sort";
import ExportButton from "./ExportButton";

export interface TableColumn {
  key: string;
  header: string;
  unit?: Unit;
  /** Explicit sort kind. When absent, the kind is inferred from cell text. */
  kind?: "number" | "date" | "string";
}

export interface TableRow {
  [key: string]: string;
}

interface Props {
  caption: string;
  columns: TableColumn[];
  rows: TableRow[];
  /** When set, a CSV export button renders above the table with unit headers. */
  exportFilename?: string;
  exportLabel?: string;
}

/**
 * Display caps: validated payloads are already bounded, but tables
 * render one DOM row per record, so an excessive frame is refused here
 * rather than constructed. Limits mirror the validator collection caps.
 */
export const MAX_TABLE_ROWS = 2000;
export const MAX_TABLE_COLUMNS = 32;

export default function DataTable(props: Props) {
  const [sort, setSort] = createSignal<SortState | null>(null);

  const excessive = () =>
    props.rows.length > MAX_TABLE_ROWS || props.columns.length > MAX_TABLE_COLUMNS;

  const kindOf = (col: TableColumn): "number" | "date" | "string" =>
    col.kind ?? inferKind(col.key, props.rows);

  const sortedRows = createMemo(() => sortRows(props.rows, props.columns, sort()));

  const toggleSort = (key: string) => {
    setSort(nextSortState(sort(), key));
  };

  const ariaSort = (key: string): "none" | "ascending" | "descending" => {
    const active = sort();
    if (!active || active.key !== key) return "none";
    return active.dir === "asc" ? "ascending" : "descending";
  };

  const sortGlyph = (key: string): string => {
    const active = sort();
    if (!active || active.key !== key) return " ";
    return active.dir === "asc" ? "▲" : "▼";
  };

  return (
    <div class="table-wrap">
      <Show
        when={!excessive()}
        fallback={
          <p role="alert">
            Table refused: {props.rows.length} rows and {props.columns.length} columns
            exceed the cap of {MAX_TABLE_ROWS} rows and {MAX_TABLE_COLUMNS} columns
            for {props.caption}. Pick a narrower view.
          </p>
        }
      >
        <Show when={props.exportFilename}>
          <div class="table-tools">
            <ExportButton
              filename={props.exportFilename as string}
              columns={props.columns}
              rows={sortedRows()}
              label={props.exportLabel ?? "Export CSV"}
            />
          </div>
        </Show>
        <table class="kv-table">
          <caption class="sr-only">{props.caption}</caption>
          <thead>
            <tr>
              <For each={props.columns}>
                {(col) => (
                  <th scope="col" aria-sort={ariaSort(col.key)}>
                    <button
                      class="th-sort"
                      type="button"
                      aria-label={
                        "Sort by " + col.header + " (" + kindOf(col) + ", nulls last)"
                      }
                      onClick={() => toggleSort(col.key)}
                    >
                      <span aria-hidden="true" class="th-glyph">
                        {sortGlyph(col.key)}
                      </span>
                      {col.header}
                      {col.unit ? <span class="unit-tag">{col.unit}</span> : null}
                    </button>
                  </th>
                )}
              </For>
            </tr>
          </thead>
          <tbody>
            <For each={sortedRows()}>
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
