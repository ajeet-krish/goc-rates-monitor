export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "NA";
  return value.toFixed(digits);
}

export function fmtYieldPct(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "NA";
  return value.toFixed(2) + " pct";
}

export function fmtBp(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "NA";
  const sign = value > 0 ? "+" : "";
  return sign + value.toFixed(1) + " bp";
}

export function fmtShortSha(sha: string | undefined): string {
  if (!sha) return "missing sha";
  if (sha.length <= 8) return sha;
  return sha.slice(0, 8) + " (short sha, 8 of " + sha.length + ")";
}

export function fmtDateUtc(date: string | undefined): string {
  if (!date) return "date missing";
  return date;
}
