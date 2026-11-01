import type { DataIndex, SnapshotDoc, VerifyReport } from "../types";

function tbillPrice(yieldPercent: number, days: number): number {
  return 100 / (1 + (yieldPercent / 100) * (days / 365));
}

const curveDiscount = (y: number, t: number): number => 1 / Math.pow(1 + y / 200, 2 * t);

export const MOCK_DATE = "2026-10-30";

export const mockSnapshot: SnapshotDoc = {
  metadata: { snapshot_date: MOCK_DATE, created_utc: "2026-10-31T00:00:00Z", schema_version: 1 },
  observations: {
    tbill_check: { yield_percent: 4.0, price: tbillPrice(4.0, 90), days_to_maturity: 90 },
    benchmarks: {
      "10Y": {
        valet_label: "10-year benchmark bond yield",
        valet: {
          value: 3.85,
          unit: "percent",
          quality: "observed",
          source_id: "valet:BD.CDN.10YR.DQ.YLD",
        },
      },
      "2Y": {
        valet_label: "2-year benchmark bond yield",
        valet: {
          value: 3.32,
          unit: "percent",
          quality: "observed",
          source_id: "valet:BD.CDN.2YR.DQ.YLD",
        },
      },
      "5Y": {
        valet_label: "5-year benchmark bond yield",
        valet: {
          value: 3.62,
          unit: "percent",
          quality: "observed",
          source_id: "valet:BD.CDN.5YR.DQ.YLD",
        },
      },
    },
    corra: {
      value_date: "2026-10-29",
      pub_date: "2026-10-30",
      date_role: "value_date_lags_pub_date",
    },
    fred_lag: {
      observation_date: "2026-10-29",
      expected_lag_note: "DGS prints land T+1",
    },
    statcan: { seasonally_adjusted_reused_as_is: true, vectors: {} },
    cross_source_diff_bp: { value_bp: 0.5, unit: "basis_points" },
    staleness: { max_age_business_days: 1, unit: "business_days" },
    curve: {
      method: "par_approx_semiannual_log_discount_v1",
      is_par_approx: true,
      is_zero: false,
      knots: [
        {
          tenor: "2Y",
          tenor_years: 2,
          tenor_unit: "duration_years",
          yield_percent: 3.32,
          yield_unit: "percent_yield",
          discount: curveDiscount(3.32, 2),
          discount_unit: "unitless_ratio",
          source_id: "derived:curve",
        },
        {
          tenor: "5Y",
          tenor_years: 5,
          tenor_unit: "duration_years",
          yield_percent: 3.62,
          yield_unit: "percent_yield",
          discount: curveDiscount(3.62, 5),
          discount_unit: "unitless_ratio",
          source_id: "derived:curve",
        },
        {
          tenor: "10Y",
          tenor_years: 10,
          tenor_unit: "duration_years",
          yield_percent: 3.9,
          yield_unit: "percent_yield",
          discount: curveDiscount(3.9, 10),
          discount_unit: "unitless_ratio",
          source_id: "derived:curve",
        },
        {
          tenor: "30Y",
          tenor_years: 30,
          tenor_unit: "duration_years",
          yield_percent: 4.19,
          yield_unit: "percent_yield",
          discount: curveDiscount(4.19, 30),
          discount_unit: "unitless_ratio",
          source_id: "derived:curve",
        },
      ],
      discounts: {
        "2Y": { value: curveDiscount(3.32, 2), unit: "unitless_ratio", quality: "observed", source_id: "derived:curve" },
        "5Y": { value: curveDiscount(3.62, 5), unit: "unitless_ratio", quality: "observed", source_id: "derived:curve" },
        "10Y": { value: curveDiscount(3.9, 10), unit: "unitless_ratio", quality: "observed", source_id: "derived:curve" },
        "30Y": { value: curveDiscount(4.19, 30), unit: "unitless_ratio", quality: "observed", source_id: "derived:curve" },
      },
      zero_yields: {
        "2Y": { value: 3.32, unit: "percent_yield", quality: "observed", source_id: "derived:curve" },
        "5Y": { value: 3.62, unit: "percent_yield", quality: "observed", source_id: "derived:curve" },
        "10Y": { value: 3.9, unit: "percent_yield", quality: "observed", source_id: "derived:curve" },
        "30Y": { value: 4.19, unit: "percent_yield", quality: "observed", source_id: "derived:curve" },
      },
      curve_source_id: "derived:curve",
      long_proxy_note: "30Y tenor used directly",
    },
    spreads: [
      {
        date: "2026-10-30",
        ca_date: "2026-10-30",
        us_date: "2026-10-30",
        ca_yield_percent: 3.5,
        us_yield_percent: 3.0,
        spread_bp: 50.0,
      },
    ],
    carry: {
      yield_at_maturity_percent: 3.0,
      yield_at_rolled_tenor_percent: 3.0,
      horizon_years: 0.25,
      carry_roll_bp: 75.0,
    },
    risk: {
      yield_percent: 3.0,
      tenor_years: 5.0,
      price: 100.0,
      modified_duration_years: 4.58,
      dv01_per_million: 4580.0,
    },
    backtest: {
      rule: "2s10s_z252_meanrev_v1",
      dates: [],
      slopes_bp: [],
      total_pnl_bp: 0,
    },
  },
  provenance: {
    valet: {
      source_url: "https://www.bankofcanada.ca/valet/",
      retrieved_utc: "2026-10-31T00:00:00Z",
      vintage: "2026-10-30",
    },
  },
  warnings: [],
};

export const MOCK_SHA256 =
  "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

export const mockVerify: VerifyReport = {
  checked_utc: "2026-10-31T00:00:00Z",
  tolerance_bp: 1.0,
  tolerance_unit: "basis_points",
  passed_count: 18,
  failed_count: 0,
  passed: true,
  snapshot_sha256: MOCK_SHA256,
  checks: Array.from({ length: 18 }, (_, i) => {
    const id = "V" + String(i + 1).padStart(2, "0");
    return { id, passed: true, detail: id + " passed on mock fixture (unit: mixed)" };
  }),
};

export const mockIndex: DataIndex = {
  generated_utc: "2026-10-31T00:00:00Z",
  dates: [MOCK_DATE],
  latest: MOCK_DATE,
  entries: {
    [MOCK_DATE]: { snapshot_sha256: MOCK_SHA256, verify_passed: true, bytes_utf8: 1024 },
  },
};
