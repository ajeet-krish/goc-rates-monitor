/**
 * Pure table sort helpers shared by the DataTable component and the
 * node:test suite. Kept in a JSX free module so tests import the real
 * logic directly instead of asserting on component source substrings.
 * Every numeric field carries explicit units in the header; cell text
 * may carry a desk unit suffix (pct, bp, pp, %) after the literal.
 */

export type SortDir = "asc" | "desc";

export interface SortState {
  key: string;
  dir: SortDir;
}

export interface SortableColumn {
  key: string;
  kind?: "number" | "date" | "string";
}

export type SortableRow = Record<string, string>;

const MISSING_TOKENS = new Set(["", "na", "n/a", "null", "none", "missing"]);

export function isMissingCell(text: string): boolean {
  return MISSING_TOKENS.has(text.trim().toLowerCase());
}

/**
 * Full token numeric literal with an optional desk unit suffix.
 * Prefix matching misread ISO dates as the leading year ("2026-10-30"
 * parsed as 2026), so the whole trimmed cell must be one number plus
 * an optional suffix. Tenor tags such as "2Y" are not numeric: the
 * suffix vocabulary is pct, bp, pp, and percent sign only.
 */
const NUMERIC_TOKEN =
  /^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?(?:\s*(?:pct|bp|pp|%))?$/i;
const NUMERIC_PREFIX =
  /^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?/;

/** Numeric parse tolerant of unit suffixes (pct, bp) and leading plus signs. */
export function parseNumericCell(text: string): number | null {
  const trimmed = text.trim();
  if (isMissingCell(trimmed)) return null;
  if (!NUMERIC_TOKEN.test(trimmed)) return null;
  const match = trimmed.match(NUMERIC_PREFIX);
  if (!match) return null;
  const value = Number(match[0]);
  return Number.isFinite(value) ? value : null;
}

export function parseDateCell(text: string): number | null {
  const trimmed = text.trim();
  if (isMissingCell(trimmed)) return null;
  const ms = Date.parse(trimmed.length === 7 ? trimmed + "-01T00:00:00Z" : trimmed);
  if (!Number.isFinite(ms)) return null;
  return ms;
}

const STRICT_TABLE_DATE = /^\d{4}-\d{2}(?:-\d{2})?$/;

/**
 * Strict calendar check used before numeric inference, so ISO dates win
 * over the leading year number. Month precision (YYYY-MM) counts, since
 * history tables group by month.
 */
export function isStrictTableDate(text: string): boolean {
  const trimmed = text.trim();
  if (!STRICT_TABLE_DATE.test(trimmed)) return false;
  if (trimmed.length === 7) {
    return Number.isFinite(Date.parse(trimmed + "-01T00:00:00Z"));
  }
  const ms = Date.parse(trimmed);
  if (!Number.isFinite(ms)) return false;
  return new Date(ms).toISOString().slice(0, 10) === trimmed;
}

export function inferKind(key: string, rows: SortableRow[]): "number" | "date" | "string" {
  let sawNumber = false;
  let sawDate = false;
  let sawOther = false;
  for (const row of rows) {
    const text = row[key] ?? "";
    if (isMissingCell(text)) continue;
    if (isStrictTableDate(text)) {
      sawDate = true;
      continue;
    }
    if (parseNumericCell(text) !== null) {
      sawNumber = true;
      continue;
    }
    if (parseDateCell(text) !== null) {
      sawDate = true;
      continue;
    }
    sawOther = true;
    break;
  }
  if (sawOther) return "string";
  if (sawDate && !sawNumber) return "date";
  if (sawNumber && !sawDate) return "number";
  if (sawNumber && sawDate) return "string";
  return "string";
}

export function compareCells(
  a: string,
  b: string,
  kind: "number" | "date" | "string",
  dir: SortDir
): number {
  const aMissing = isMissingCell(a ?? "");
  const bMissing = isMissingCell(b ?? "");
  if (aMissing && bMissing) return 0;
  if (aMissing) return 1;
  if (bMissing) return -1;
  let order = 0;
  if (kind === "number") {
    const av = parseNumericCell(a) ?? Number.NaN;
    const bv = parseNumericCell(b) ?? Number.NaN;
    order = av < bv ? -1 : av > bv ? 1 : 0;
  } else if (kind === "date") {
    const av = parseDateCell(a) ?? Number.NaN;
    const bv = parseDateCell(b) ?? Number.NaN;
    order = av < bv ? -1 : av > bv ? 1 : 0;
  } else {
    order = a.localeCompare(b);
  }
  return dir === "asc" ? order : -order;
}

/**
 * Header click cycle: first click sorts ascending, second flips to
 * descending, third clears back to the published row order.
 */
export function nextSortState(active: SortState | null, key: string): SortState | null {
  if (!active || active.key !== key) {
    return { key, dir: "asc" };
  }
  if (active.dir === "asc") {
    return { key, dir: "desc" };
  }
  return null;
}

/** Pure row ordering behind the DataTable memo and the CSV export. */
export function sortRows(
  rows: SortableRow[],
  columns: SortableColumn[],
  active: SortState | null
): SortableRow[] {
  if (!active) return rows;
  const col = columns.find((c) => c.key === active.key);
  if (!col) return rows;
  const kind = col.kind ?? inferKind(col.key, rows);
  return [...rows].sort((ra, rb) =>
    compareCells(ra[active.key] ?? "", rb[active.key] ?? "", kind, active.dir)
  );
}
