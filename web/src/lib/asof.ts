export const STRICT_ISO = /^\d{4}-\d{2}-\d{2}$/;

export function isStrictIsoDate(text: string): boolean {
  if (!STRICT_ISO.test(text)) return false;
  const parsed = new Date(text + "T00:00:00Z");
  if (Number.isNaN(parsed.getTime())) return false;
  return parsed.toISOString().slice(0, 10) === text;
}

export interface AsofRequest {
  /** A well formed date from the query string, or null when absent. */
  requested: string | null;
  /** The raw value when the query string holds a malformed date. */
  invalid: string | null;
}

/**
 * Read the asof query value, keeping malformed input distinct from absence.
 * Malformed values used to collapse to null and were silently rewritten to
 * latest, so no unknown date state ever appeared.
 */
export function readAsofState(search: string): AsofRequest {
  const params = new URLSearchParams(search);
  const raw = params.get("asof");
  if (raw === null) return { requested: null, invalid: null };
  const trimmed = raw.trim();
  if (trimmed.length === 0) return { requested: null, invalid: null };
  if (!isStrictIsoDate(trimmed)) return { requested: null, invalid: trimmed };
  return { requested: trimmed, invalid: null };
}

/** Legacy reader: returns the valid date or null for both absent and malformed. */
export function readAsofParam(search: string): string | null {
  return readAsofState(search).requested;
}

export function resolveAsof(
  requested: string | null,
  invalid: string | null,
  available: string[],
  latest: string | null
): { asof: string | null; unknownDate: string | null } {
  if (invalid !== null) {
    return { asof: latest, unknownDate: invalid };
  }
  if (!requested) {
    return { asof: latest, unknownDate: null };
  }
  if (available.includes(requested)) {
    return { asof: requested, unknownDate: null };
  }
  return { asof: latest, unknownDate: requested };
}

export function latestN(dates: string[], count: number): string[] {
  return [...dates].sort().slice(-count);
}
