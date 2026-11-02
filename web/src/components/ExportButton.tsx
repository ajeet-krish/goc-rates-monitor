import { Show } from "solid-js";
import { downloadCsv, toCsv, type CsvColumn } from "../lib/csv";

interface Props {
  filename: string;
  columns: CsvColumn[];
  rows: Array<Record<string, string>>;
  label?: string;
}

export default function ExportButton(props: Props) {
  const count = () => props.rows.length;
  const onExport = () => {
    if (count() === 0) return;
    downloadCsv(props.filename, toCsv(props.columns, props.rows));
  };
  return (
    <Show
      when={count() > 0}
      fallback={
        <span class="figure-caption" role="status">
          No rows to export for {props.filename}.
        </span>
      }
    >
      <button
        class="btn btn-secondary"
        type="button"
        aria-label={(props.label ?? "Export table as CSV") + " (" + count() + " rows)"}
        onClick={onExport}
      >
        {props.label ?? "Export CSV"} ({count()})
      </button>
    </Show>
  );
}
