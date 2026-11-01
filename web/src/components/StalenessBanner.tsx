import { Show } from "solid-js";
import { A } from "@solidjs/router";
import { isStrictIsoDate } from "../lib/asof";

interface StalenessBannerProps {
  /** Latest published snapshot date (YYYY-MM-DD) from the index, or null when none is published. */
  latest: string | null | undefined;
  /** True when dates exist in the index. False when the index holds no dates. */
  hasDates: boolean;
  /** Current verify result for the viewed date. Null while loading or unknown. */
  verifyPassed: boolean | null | undefined;
  /** Override for the view time, in UTC. Defaults to the current time. Used in tests. */
  now?: Date;
}

/** View date (YYYY-MM-DD) in the America/Toronto time zone for the given instant. */
export function torontoViewDate(now: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Toronto",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

/** Calendar day difference between latest and the Toronto view date. Never negative. */
export function calendarAgeDays(latest: string, viewDate: string): number {
  const start = Date.parse(latest + "T00:00:00Z");
  const end = Date.parse(viewDate + "T00:00:00Z");
  if (!Number.isFinite(start) || !Number.isFinite(end)) return 0;
  return Math.max(0, Math.round((end - start) / 86_400_000));
}

/**
 * Ledger staleness notice. Silent when the latest snapshot is 0 to 3
 * calendar days old and verification passes. Warns when the latest is 4
 * or more calendar days old, when no dates are published, or when
 * verification failed. Age is measured in calendar days from index.latest
 * to the view date in America/Toronto. This banner is a nudge only:
 * check V12 enforces the 5 business day rule, weekends age this banner
 * but never fail that check.
 */
export default function StalenessBanner(props: StalenessBannerProps) {
  const viewDate = () => torontoViewDate(props.now ?? new Date());

  const noDates = () => !props.hasDates || props.latest == null;

  const ageDays = () => {
    if (props.latest == null || !isStrictIsoDate(props.latest)) return null;
    if (!isStrictIsoDate(viewDate())) return null;
    return calendarAgeDays(props.latest, viewDate());
  };

  const isStale = () => {
    const age = ageDays();
    return age !== null && age >= 4;
  };

  const verifyFailed = () => props.verifyPassed === false;

  const show = () => {
    if (props.latest === undefined) return false;
    if (noDates()) return true;
    if (verifyFailed()) return true;
    return isStale();
  };

  const headline = () => {
    if (noDates()) return "Ledger has no published snapshot";
    if (verifyFailed() && isStale()) return "Ledger is stale and unverified";
    if (verifyFailed()) return "Ledger verification failed";
    return "Ledger may be stale";
  };

  return (
    <Show when={show()}>
      <div class="alert alert-warn" role="status" aria-label="Snapshot staleness notice">
        <h3>{headline()}</h3>
        <Show when={noDates()}>
          <p>No snapshot dates are published yet. Derived values stay NA until a snapshot ships.</p>
        </Show>
        <Show when={!noDates() && props.latest != null}>
          <p>
            Latest snapshot <span class="num">{props.latest}</span> is{" "}
            <span class="num">{ageDays() ?? 0} calendar_days</span> old as viewed in
            America/Toronto on <span class="num">{viewDate()}</span>. The desk treats 4 or more
            calendar_days as stale. Check V12 separately enforces 5 business_days,
            so weekends age this banner but never fail that check.
          </p>
        </Show>
        <Show when={verifyFailed()}>
          <p>Verification failed for the viewed date. Derived values stay NA until every check passes.</p>
        </Show>
        <p>
          <A href="/verification">Open verification for the named checks</A>.
        </p>
      </div>
    </Show>
  );
}
