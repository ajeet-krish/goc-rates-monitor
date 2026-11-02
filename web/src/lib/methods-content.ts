/**
 * Shared methods copy for the Methods page.
 * Every entry states what v1 claims and what v1 refuses to claim.
 * Copy uses plain punctuation only (commas, colons, parentheses, periods).
 */

export interface MethodSection {
  id: string;
  kicker: string;
  title: string;
  method: string;
  summary: string;
  points: string[];
  limits: string[];
}

export interface AssumptionRow {
  topic: string;
  assumption: string;
  consequence: string;
}

export interface LimitRow {
  topic: string;
  limit: string;
  rationale: string;
}

export interface CheckFamily {
  range: string;
  title: string;
  blurb: string;
}

export const CHECK_FAMILIES: CheckFamily[] = [
  {
    range: "V01 to V12",
    title: "Core snapshot",
    blurb:
      "Canonical form, units, labels, bill price, CORRA roles, FRED lag, StatCan reuse, vintage markers, manifest match, cross source tolerance, staleness.",
  },
  {
    range: "V13 to V18",
    title: "Curve and funding",
    blurb:
      "Bootstrap reprice within 1.0 bp, discount range, derived units and sources, spread recompute, carry and DV01 recompute, backtest rule and count and next day recompute.",
  },
  {
    range: "V19 to V22",
    title: "Inflation replica",
    blurb:
      "Input pins, trim and median recompute, contribution reconcile, experimental label and gate honesty. The gate flag never blocks the build.",
  },
  {
    range: "V23",
    title: "Breaks gate",
    blurb:
      "Switch feed digest, tenor closure, recomputed joint dates, calendar gaps, switch flags, gates, day over day deltas, nullness rules.",
  },
  {
    range: "V24 to V25",
    title: "Bootstrap instruments",
    blurb:
      "Settlement dating with residual ACT over 365 years, instrument cashflow counts with dirty prices, reprice errors within 1.0 bp, anchor monotonicity, knot tenor agreement.",
  },
];

export const METHOD_SECTIONS: MethodSection[] = [
  {
    id: "curve",
    kicker: "Curve engine",
    title: "True bootstrap, stated plainly",
    method: "true_bootstrap_semiannual_log_discount_v1",
    summary:
      "Benchmark yields to maturity enter as dirty price targets and leave as a solved zero curve on semiannual cashflows. The zero curve is distinct from input YTM: inputs price the bonds, zeros come from the solved discounts.",
    points: [
      "Inputs are benchmark yields in percent, priced to dirty targets per 100 face (is_par_approx false, is_zero true).",
      "Knot tenors are residual ACT over 365 years from settlement to each maturity, in duration_years.",
      "Each anchor solves by bisection so its model price matches its dirty target within 1.0 bp, with earlier anchors held fixed.",
      "Log discounts interpolate linearly between anchors. Beyond the last anchor the zero rate holds flat for extrapolation.",
      "Instruments disclose tenor, maturity date, coupon in percent, cashflow count, dirty price per 100 face, and reprice error in bp. Anchors disclose date, years, and discount. Sparse disclosure degrades the page, never silently.",
      "Long is a 30Y proxy and is labelled as a proxy wherever it appears.",
    ],
    limits: [
      "One curve per date, solved in maturity order. No Nelson Siegel Svensson fit and no multi curve tenor basis.",
      "Zero yields shown beside the curve are the solved semiannual zeros, never requoted inputs.",
    ],
  },
  {
    id: "carry-risk",
    kicker: "Carry and risk",
    title: "One horizon, one million, no funding story",
    method: "carry_roll_v1 and semiannual_risk_v1",
    summary:
      "Carry and risk are closed form illustrations on an unchanged curve. They exclude coupons and funding.",
    points: [
      "Carry roll uses horizon 0.25 years on an unchanged curve, reported in basis points.",
      "Risk uses semiannual closed forms for par price per 100 face, modified duration in years, and DV01 per one million face.",
      "DV01 scaling is linear in one million face. No convexity adjustment is included.",
    ],
    limits: [
      "Carry is ex coupon and ex funding. It answers the roll question only, not the holding return.",
      "Risk assumes a flat parallel move at the stated tenor. Curve twists are out of scope.",
    ],
  },
  {
    id: "spreads",
    kicker: "Canada US spreads",
    title: "Same date inner join, no fill",
    method: "canada_us_spread_v1",
    summary:
      "Spreads join Canadian and US closes on shared dates only. Missing legs stay missing, never filled.",
    points: [
      "Records join on one shared date (ca_date and us_date both equal date). Non shared dates are dropped.",
      "No forward fill and no interpolation is applied to either leg at any step.",
      "Canadian leg closes at the Bank of Canada close. US leg prints by about 16:15 Eastern.",
      "CORRA value dates lag publication by one business day, so snapshots store value date, pub date, and a date role flag.",
    ],
    limits: [
      "FRED prints land with T+1 latency and are never revised, so the US leg trails the Canadian leg by design.",
      "A missing FRED key degrades spreads to an explicit missing marker with a reason, not a silent gap.",
    ],
  },
  {
    id: "backtest",
    kicker: "Backtest sketch",
    title: "Fixed rule, gross moves only",
    method: "2s10s_z252_meanrev_v1",
    summary:
      "One fixed 2s10s mean reversion sketch with a 252 day trailing window, next day DV01 neutral profit and loss, reported gross.",
    points: [
      "Entry at absolute z score 1.0 on the trailing 252 slope window excluding the current day.",
      "Profit and loss accrues next day, DV01 neutral, summed in basis points with no compounding.",
      "Rule text, dates, slopes, and the total are all stored in the snapshot and recomputed by V18.",
    ],
    limits: [
      "Costs are disclosed as zero. The sketch is gross by construction, not net of trading cost.",
      "No Sharpe ratio and no live signal claim is made. The rule is fixed and never refit in sample.",
    ],
  },
  {
    id: "inflation",
    kicker: "Inflation replica",
    title: "Experimental trim and median, revisable by design",
    method: "cpi_trim_median_weighted_sa_v1",
    summary:
      "StatCan values are reused as published. The replica trim and median are experimental vintages that revise with the bulk source.",
    points: [
      "Seasonally adjusted StatCan values are reused as published. No X-13 style refit is run in this pipeline (owns_seasonal_adjustment false).",
      "Trim drops the bottom and top 20 percent of cumulative weight with partial splits on straddlers. Median reads the first component past 50 percent.",
      "Annual rates compound the trailing 12 monthly cores, never average them.",
      "Weights follow the 2024 expenditure vintage with link month 2025-05, provisional until StatCan finalises the basket.",
      "A tax window flag covers 2024-12 to 2026-03 for GST effects (holiday December 2024 to February 2025, removal March 2025, restoration March 2026). Replica months inside the window stay experimental and revisable.",
    ],
    limits: [
      "Publisher series stay final while the replica stays experimental (label experimental, is_official false).",
      "Validation compares the replica against published vintages over a trailing 36 month window with a 24 month minimum. A mean error over 0.10 percentage points flags for explanation and never blocks the build.",
    ],
  },
  {
    id: "breaks",
    kicker: "Benchmark switches",
    title: "Switches suppress, never splice",
    method: "benchmark_switch_dod_gate_v1",
    summary:
      "Benchmark rotations come from a pinned feed. A switch inside the day over day window suppresses the delta to null with a named gate.",
    points: [
      "Feed pins source bench_CDN.pdf with vintage 2026-11-01 and a sha256 digest matched against provenance.",
      "Joint effective dates roll forward to the first joint business day on or after the effective date.",
      "A switch in (prev, current] suppresses day over day to null with gate switch_break. Calendar gaps keep the number with gate calendar_gap.",
      "Missing legs use missing_prev or insufficient_history with null deltas. Threshold 15.0 basis points marks a break that needs explanation.",
      "Every record carries a dod quantity in basis points with source derived:dod_gate (observed with numbers, missing with nulls).",
    ],
    limits: [
      "Suppression is not splicing. No adjusted history is published and no backfill rewrites past prints.",
      "Gate flags are booleans without coercion and history counts are integers, so stringly typed inputs fail closed.",
    ],
  },
  {
    id: "verification",
    kicker: "Verification",
    title: "Twenty five checks, fail closed",
    method: "verify V01 to V25 at 1.0 bp tolerance",
    summary:
      "Every derived display waits on all twenty five checks. Any failure blocks the build and turns derived values to NA.",
    points: [
      "Tolerance is 1.0 basis point wherever a basis point comparison applies (mixed units name their own tolerances in the detail text).",
      "Every check names its unit in its detail string, so a pass states what was compared.",
      "The inflation validation flag is honest either way: within_gate or exceeds_gate_needs_explanation both pass V22 when the flag matches the recompute.",
      "Bootstrap checks V24 and V25 pin settlement dating, cashflow counts, dirty prices, reprice errors, and anchor monotonicity beside the V13 reprice.",
      "The validation flag never blocks the build. A breached gate asks for an explanation note, not a rebuild.",
    ],
    limits: [
      "Quantity caps, digest matches, and date grammars are checked before any recompute, so oversized or malformed payloads reject fast.",
      "Fail closed demo values on the verification page are synthetic, carry no check id, and never enter the snapshot.",
    ],
  },
  {
    id: "history",
    kicker: "History merge",
    title: "Verified precedence, backfilled spans stay dashed",
    method: "history_merge_v1",
    summary:
      "The sealed backfill plus published snapshots merge into one history document. Verified snapshot rows win, backfilled rows fill the rest, and any overlap beyond tolerance fails the build.",
    points: [
      "Sources are Valet group bond_yields_benchmark for Canadian legs, FRED DGS for US legs with T+1 latency, and StatCan bulk 18100004 plus 18100256 plus 18100007 for CPI.",
      "Windows are joint complete daily rows (up to 1250) and monthly CPI rows (up to 60) within a 5 MiB document cap.",
      "Overlap checks compare snapshot yields to backfill yields within 1.0 bp and CPI moms within 0.01 pp. Verified rows carry snapshot digests with source derived:history_verified_v1, backfilled rows carry source derived:backfill_v1.",
      "Backfilled spans render dashed and muted with an unverified caption. History loads independently and never blocks the desk.",
      "CPI history uses one uniform vintage (2024 expenditure, link month 2025-05, provisional) so every month reads the same basket.",
    ],
    limits: [
      "A tampered manifest, a promoted row with verified true in the backfill, an overlap conflict, or an absent artifact all fail the build with nothing published.",
      "History counts and bytes are capped before any recompute, dates must be strictly increasing, and row digests must recompute from the canonical form.",
    ],
  },
];

export const ASSUMPTION_ROWS: AssumptionRow[] = [
  {
    topic: "Curve shape",
    assumption: "Benchmark yields price each bond to a dirty target on semiannual cashflows.",
    consequence: "Levels near knots are solved, curvature between anchors follows log linear discounts.",
  },
  {
    topic: "Curve ends",
    assumption: "Beyond the last anchor the zero rate holds flat.",
    consequence: "Long end extrapolation inherits the last solved zero, stated openly.",
  },
  {
    topic: "Carry path",
    assumption: "The curve is unchanged over the 0.25 year horizon.",
    consequence: "Carry isolates roll down only, not realised return.",
  },
  {
    topic: "Spread dates",
    assumption: "Only shared Canada US dates enter, with no fill.",
    consequence: "Holiday gaps appear as gaps, never as flat lines.",
  },
  {
    topic: "Seasonal adjustment",
    assumption: "StatCan seasonally adjusted values are reused as published.",
    consequence: "No refit risk in this pipeline, but StatCan revisions flow straight through.",
  },
  {
    topic: "Switch windows",
    assumption: "A switch inside (prev, current] suppresses the day over day delta.",
    consequence: "Rotation days read as NA with a named reason instead of a false jump.",
  },
];

export const LIMIT_ROWS: LimitRow[] = [
  {
    topic: "Curve fit",
    limit: "One semiannual bootstrap in maturity order, no Nelson Siegel Svensson fit.",
    rationale: "Solved anchors beat an unstated model. Bisection error stays within 1.0 bp per bond.",
  },
  {
    topic: "Long tenor",
    limit: "30Y is a proxy tenor.",
    rationale: "Benchmark availability ends before true 30Y maturity, so the label says proxy.",
  },
  {
    topic: "Break threshold",
    limit: "15.0 basis points marks a break.",
    rationale: "Small noise stays comparable. Larger moves need a written explanation.",
  },
  {
    topic: "Inflation gate",
    limit: "0.10 percentage points mean error over the trailing window.",
    rationale: "Replica drift past the gate flags for explanation while the build stays green.",
  },
  {
    topic: "Staleness",
    limit: "Banner warns at 4 calendar days in Toronto, V12 fails past 5 business days.",
    rationale: "The banner is a nudge, the check is the rule. Weekends age the banner but not the check.",
  },
];
