import type { Unit } from "./types";

export interface CsvColumn {
  key: string;
  header: string;
  unit?: Unit;
}

/** Header label always carries the unit, so exported files stay self describing. */
export function csvHeaderLabel(column: CsvColumn): string {
  if (column.unit) return column.header + " (" + column.unit + ")";
  return column.header;
}

/**
 * Formula guard plus RFC4180 escaping. A cell whose first non blank
 * character is a spreadsheet formula trigger (=, +, -, @) opens live in
 * spreadsheet apps, so one leading apostrophe neutralizes it as text.
 * Optional leading spaces and tabs are skipped when detecting the
 * trigger, since spreadsheet trimmers ignore them. The guard runs before
 * RFC4180 quoting, so guarded fields carrying commas still quote after.
 */
const FORMULA_TRIGGER = /^[ \t]*[=+\-@]/;

/**
 * Escape one RFC4180 field. Fields holding a quote, comma, CR, or LF are
 * wrapped in quotes with inner quotes doubled. Plain fields pass through.
 */
export function escapeCsvCell(value: string): string {
  let text = value ?? "";
  if (FORMULA_TRIGGER.test(text)) text = "'" + text;
  if (/["\r\n,]/.test(text)) {
    return '"' + text.replace(/"/g, '""') + '"';
  }
  return text;
}

/**
 * Build an RFC4180 CSV document with CRLF line endings and a trailing
 * newline. Missing cells export as NA, matching on screen tables.
 */
export function toCsv(
  columns: CsvColumn[],
  rows: Array<Record<string, string>>
): string {
  const header = columns.map((c) => escapeCsvCell(csvHeaderLabel(c))).join(",");
  const lines = rows.map((row) =>
    columns.map((c) => escapeCsvCell(row[c.key] ?? "NA")).join(",")
  );
  return [header, ...lines].join("\r\n") + "\r\n";
}

/**
 * Trigger a client side CSV download through a Blob URL. No server call,
 * so an export never blocks on the network. Safe to call only in browsers.
 */
export function downloadCsv(filename: string, csvText: string): void {
  const blob = new Blob([csvText], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}
