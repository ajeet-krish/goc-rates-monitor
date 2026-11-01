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
  | "unitless_ratio"
  | "percent_per_month"
  | "percentage_points";

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

export interface InflationContribution {
  component_id: string;
  monthly_rate_percent: number;
  weight_percent: number;
  contribution_pp: number;
}

export interface InflationHistoryRow {
  month: string;
  trim_mom_percent: number;
  median_mom_percent: number;
  median_component: string;
  trim_yoy_percent: number | null;
  median_yoy_percent: number | null;
}

export interface TrimMedianValidation {
  months: number;
  gate_pp: number;
  trim: { mae_pp: number; bias_pp: number; max_abs_resid_pp: number };
  median: { mae_pp: number; bias_pp: number; max_abs_resid_pp: number };
  exceeds_gate: boolean;
  flag: string;
  note: string;
  published_months: string[];
  residuals_trim_pp: number[];
  residuals_median_pp: number[];
}

export interface InflationSection {
  label: string;
  is_official: boolean;
  publisher_series: string;
  experimental_series: string;
  method: string;
  owns_seasonal_adjustment: boolean;
  seasonally_adjusted_source: string;
  component_count: number;
  weight_vintage: { expenditure_year: number; link_month: string; provisional: boolean };
  reference_month: string;
  indexes: { months: string[]; trim: Quantity[]; median: Quantity[] };
  latest: {
    month: string;
    trim_mom: Quantity;
    median_mom: Quantity;
    trim_yoy: Quantity;
    median_yoy: Quantity;
    median_component: string;
  };
  history: InflationHistoryRow[];
  history_months: number;
  contributions: InflationContribution[];
  total_contribution_pp: number;
  headline_mom: Quantity;
  kept_weight_fraction: number;
  excluded_weight_fraction: number;
  validation: TrimMedianValidation;
  bulk: Record<string, { product_id: number; zip_sha256: string; zip_sha12: string }>;
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
    inflation?: InflationSection;
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
