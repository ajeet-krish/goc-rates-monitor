export type Unit =
  | "percent"
  | "basis_points"
  | "index_points"
  | "business_days"
  | "price_units_per_100_face"
  | "days"
  | "percent_yield"
  | "bp"
  | "bp_per_annum"
  | "duration_years"
  | "dv01_per_million"
  | "unitless_ratio";

export type Quality = "observed" | "missing" | "stale" | "revised";

export interface Quantity {
  value: number | null;
  unit: Unit;
  quality: Quality;
  source_id: string;
}

export interface CurveKnotRow {
  tenor: string;
  tenor_years: number;
  tenor_unit: Unit;
  yield_percent: number;
  yield_unit: Unit;
  discount: number;
  discount_unit: Unit;
  source_id: string;
}

export interface CurveSection {
  method: string;
  is_par_approx: boolean;
  is_zero: boolean;
  knots: CurveKnotRow[];
  discounts: Record<string, Quantity>;
  zero_yields: Record<string, Quantity>;
  curve_source_id: string;
  long_proxy_note?: string;
}

export interface SpreadRecord {
  date: string;
  ca_date: string;
  us_date: string;
  ca_yield_percent: number;
  us_yield_percent: number;
  spread_bp: number;
}

export interface CarrySection {
  yield_at_maturity_percent: number;
  yield_at_rolled_tenor_percent: number;
  horizon_years: number;
  carry_roll_bp: number;
}

export interface RiskSection {
  yield_percent: number;
  tenor_years: number;
  price: number;
  modified_duration_years: number;
  dv01_per_million: number;
}

export interface BacktestSection {
  rule: string;
  dates: string[];
  slopes_bp: number[];
  total_pnl_bp: number;
}

export interface SnapshotDoc {
  metadata: {
    snapshot_date: string;
    created_utc?: string;
    schema_version: number;
  };
  observations: {
    tbill_check?: { yield_percent: number; price: number; days_to_maturity: number };
    benchmarks?: Record<string, { valet_label: string; valet: Quantity }>;
    corra?: { value_date: string; pub_date: string; date_role: string };
    fred_lag?: { observation_date: string; expected_lag_note: string };
    statcan?: { seasonally_adjusted_reused_as_is: boolean; vectors: Record<string, unknown> };
    cross_source_diff_bp?: { value_bp: number; unit: string };
    staleness?: { max_age_business_days: number; unit: string };
    curve?: CurveSection;
    spreads?: SpreadRecord[];
    carry?: CarrySection;
    risk?: RiskSection;
    backtest?: BacktestSection;
    [key: string]: unknown;
  };
  provenance: Record<string, { source_url: string; retrieved_utc: string; vintage: string }>;
  warnings: string[];
  manifest?: { snapshot?: { sha256?: string }; files?: Record<string, { sha256: string }> };
}

export interface VerifyCheck {
  id: string;
  passed: boolean;
  detail: string;
}

export interface VerifyReport {
  checked_utc?: string;
  tolerance_bp: number;
  tolerance_unit: string;
  passed_count: number;
  failed_count: number;
  passed: boolean;
  snapshot_sha256?: string;
  checks: VerifyCheck[];
}

export interface DataIndex {
  generated_utc: string;
  dates: string[];
  latest: string | null;
  entries: Record<
    string,
    { snapshot_sha256: string; verify_passed: boolean | null; bytes_utf8: number }
  >;
}
