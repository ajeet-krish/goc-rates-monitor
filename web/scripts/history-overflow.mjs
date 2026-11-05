/**
 * Overflow policy for the merged daily history rows.
 *
 * Rows arrive sorted ascending by date. Verified rows carry a non null
 * snapshot_sha256 digest and are always kept. Backfilled rows carry a null
 * snapshot_sha256 digest, and the oldest backfilled rows are dropped first
 * so the published daily series never exceeds the cap.
 */

/**
 * Apply the daily history cap while keeping every verified row.
 *
 * When the rows already fit the cap the input is returned unchanged. When
 * they do not fit, every verified row is kept and only the oldest
 * backfilled rows are dropped until the total is within the cap. The
 * relative order of the surviving rows is preserved.
 *
 * @param {Array<Record<string, any>>} rows merged daily rows sorted ascending by date.
 * @param {number} cap maximum number of daily rows allowed.
 * @returns {{ rows: Array<Record<string, any>>, trimmedCount: number }}
 *   The capped rows in their original order, plus the number of dropped rows.
 * @throws {Error} If the cap is not a positive integer, if the rows are not
 *   strictly ascending unique date strings, or if the verified rows alone
 *   exceed the cap, because publishing would then mean discarding verified
 *   evidence.
 */
export function applyOverflowPolicy(rows, cap) {
  assertPreconditions(rows, cap);
  if (rows.length <= cap) {
    return { rows, trimmedCount: 0 };
  }
  const isVerified = (row) => typeof row?.snapshot_sha256 === "string";
  const verifiedCount = rows.filter(isVerified).length;
  if (verifiedCount > cap) {
    throw new Error(
      "verified daily rows " + verifiedCount + " alone exceed the " + cap +
        " cap: refusing to publish"
    );
  }
  const backfillRows = rows.filter((row) => !isVerified(row));
  const keepBackfillCount = cap - verifiedCount;
  const keptBackfill = new Set(
    backfillRows.slice(backfillRows.length - keepBackfillCount)
  );
  const kept = rows.filter((row) => isVerified(row) || keptBackfill.has(row));
  return { rows: kept, trimmedCount: backfillRows.length - keepBackfillCount };
}

/**
 * Validate the applyOverflowPolicy preconditions before any trimming runs.
 *
 * @param {Array<Record<string, any>>} rows merged daily rows.
 * @param {number} cap maximum number of daily rows allowed.
 * @throws {Error} If the cap is not a positive integer, if rows is not an
 *   array, if any row date is not a string, if dates repeat, or if the dates
 *   are not sorted ascending.
 */
function assertPreconditions(rows, cap) {
  if (!Number.isInteger(cap) || cap <= 0) {
    throw new Error("cap must be a positive integer, got " + String(cap));
  }
  if (!Array.isArray(rows)) {
    throw new Error("rows must be an array, got " + typeof rows);
  }
  const dates = rows.map((row, i) => {
    const date = row?.date;
    if (typeof date !== "string") {
      throw new Error("row " + i + " date must be a string, got " + JSON.stringify(date));
    }
    return date;
  });
  const seen = new Set();
  for (const date of dates) {
    if (seen.has(date)) {
      throw new Error("duplicate row date " + date + ": dates must be unique");
    }
    seen.add(date);
  }
  for (let i = 1; i < dates.length; i++) {
    if (dates[i] <= dates[i - 1]) {
      throw new Error(
        "rows must be sorted ascending by date, got " + dates[i - 1] +
          " followed by " + dates[i]
      );
    }
  }
}
