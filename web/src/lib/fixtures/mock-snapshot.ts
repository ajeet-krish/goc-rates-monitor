import type { DataIndex, InflationSection, SnapshotDoc, VerifyReport } from "../types";

function tbillPrice(yieldPercent: number, days: number): number {
  return 100 / (1 + (yieldPercent / 100) * (days / 365));
}

const curveDiscount = (y: number, t: number): number => 1 / Math.pow(1 + y / 200, 2 * t);

export const MOCK_DATE = "2026-10-30";

function mockInflation(): InflationSection {
  const weight = 100 / 55;
  const flatMonthly = 0.2;
  const flatYoy = 2.4266;
  const contributions = Array.from({ length: 55 }, (_, i) => {
    const id = "C" + String(i + 1).padStart(2, "0");
    return {
      component_id: id,
      monthly_rate_percent: flatMonthly,
      weight_percent: weight,
      contribution_pp: (weight * flatMonthly) / 100,
    };
  });
  const publishedMonths = Array.from({ length: 28 }, (_, i) => {
    const stamp = 2024 * 12 + 5 + i;
    const year = Math.floor(stamp / 12);
    const month = (stamp % 12) + 1;
    return year + "-" + String(month).padStart(2, "0");
  });
  const zeros = Array.from({ length: 28 }, () => 0);
  const historyMonths = Array.from({ length: 12 }, (_, i) => {
    const stamp = 2025 * 12 + 9 + i;
    const year = Math.floor(stamp / 12);
    const month = (stamp % 12) + 1;
    return year + "-" + String(month).padStart(2, "0");
  });
  const fakeSha =
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
  return {
    label: "experimental",
    is_official: false,
    publisher_series: "statcan",
    experimental_series: "derived:cpi_trim_median",
    method: "cpi_trim_median_weighted_sa_v1",
    owns_seasonal_adjustment: false,
    seasonally_adjusted_source: "statcan",
    component_count: 55,
    weight_vintage: { expenditure_year: 2024, link_month: "2025-05", provisional: true },
    reference_month: "2026-09",
    indexes: {
      months: ["2026-08", "2026-09"],
      trim: [100.4, 100.6].map((value) => ({
        value,
        unit: "index_points",
        quality: "observed",
        source_id: "derived:cpi_trim_median",
      })),
      median: [100.3, 100.5].map((value) => ({
        value,
        unit: "index_points",
        quality: "observed",
        source_id: "derived:cpi_trim_median",
      })),
    },
    latest: {
      month: "2026-09",
      trim_mom: {
        value: flatMonthly,
        unit: "percent_per_month",
        quality: "observed",
        source_id: "derived:cpi_trim_median",
      },
      median_mom: {
        value: flatMonthly,
        unit: "percent_per_month",
        quality: "observed",
        source_id: "derived:cpi_trim_median",
      },
      trim_yoy: {
        value: flatYoy,
        unit: "percent",
        quality: "observed",
        source_id: "derived:cpi_trim_median",
      },
      median_yoy: {
        value: flatYoy,
        unit: "percent",
        quality: "observed",
        source_id: "derived:cpi_trim_median",
      },
      median_component: "C28",
    },
    history: historyMonths.map((month) => ({
      month,
      trim_mom_percent: flatMonthly,
      median_mom_percent: flatMonthly,
      median_component: "C28",
      trim_yoy_percent: flatYoy,
      median_yoy_percent: flatYoy,
    })),
    history_months: 12,
    contributions,
    total_contribution_pp: contributions.reduce((sum, row) => sum + row.contribution_pp, 0),
    headline_mom: {
      value: flatMonthly,
      unit: "percent_per_month",
      quality: "observed",
      source_id: "derived:cpi_trim_median",
    },
    kept_weight_fraction: 0.6,
    excluded_weight_fraction: 0.4,
    validation: {
      months: 28,
      gate_pp: 0.1,
      trim: { mae_pp: 0, bias_pp: 0, max_abs_resid_pp: 0 },
      median: { mae_pp: 0, bias_pp: 0, max_abs_resid_pp: 0 },
      exceeds_gate: false,
      flag: "within_gate",
      note: "mock replica matches its published vintage",
      published_months: publishedMonths,
      residuals_trim_pp: zeros,
      residuals_median_pp: zeros,
    },
    bulk: {
      cpi_monthly: { product_id: 18100004, zip_sha256: fakeSha, zip_sha12: fakeSha.slice(0, 12) },
      core_statistics: { product_id: 18100256, zip_sha256: fakeSha, zip_sha12: fakeSha.slice(0, 12) },
      basket_weights: { product_id: 18100007, zip_sha256: fakeSha, zip_sha12: fakeSha.slice(0, 12) },
    },
  };
}

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
    spreads: {
      status: "ok",
      reason: null,
      records: [
        {
          tenor: "2Y",
          date: "2026-10-30",
          ca_date: "2026-10-30",
          us_date: "2026-10-30",
          ca_yield_percent: 3.5,
          us_yield_percent: 3.0,
          spread_bp: 50.0,
        },
        {
          tenor: "5Y",
          date: "2026-10-30",
          ca_date: "2026-10-30",
          us_date: "2026-10-30",
          ca_yield_percent: 3.62,
          us_yield_percent: 3.1,
          spread_bp: 52.0,
        },
        {
          tenor: "10Y",
          date: "2026-10-30",
          ca_date: "2026-10-30",
          us_date: "2026-10-30",
          ca_yield_percent: 3.9,
          us_yield_percent: 3.4,
          spread_bp: 50.0,
        },
        {
          tenor: "30Y",
          date: "2026-10-30",
          ca_date: "2026-10-30",
          us_date: "2026-10-30",
          ca_yield_percent: 4.19,
          us_yield_percent: 3.6,
          spread_bp: 59.0,
        },
      ],
    },
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
    inflation: mockInflation(),
    breaks: {
      method: "benchmark_switch_dod_gate_v1",
      snapshot_date: MOCK_DATE,
      print_date: MOCK_DATE,
      feed_source: "bench_CDN.pdf",
      feed_vintage: "2026-11-01",
      feed_sha256:
        "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
      threshold_bp: 15.0,
      threshold_unit: "basis_points",
      events: [
        {
          tenor: "5Y",
          effective_date: "2026-10-30",
          effective_joint_date: "2026-10-30",
          incoming_maturity: "2029-11-01",
          incoming_coupon_percent: 3.25,
          incoming_coupon_unit: "percent",
          outgoing_maturity: null,
          outgoing_coupon_percent: null,
          outgoing_coupon_unit: "percent",
        },
      ],
      records: [
        {
          tenor: "2Y",
          prev_date: "2026-10-29",
          current_date: MOCK_DATE,
          prev_yield_percent: 3.3,
          current_yield_percent: 3.32,
          prev_yield_unit: "percent",
          current_yield_unit: "percent",
          dod_bp: 2.0,
          dod_unit: "basis_points",
          gate: "comparable",
          switch_in_window: false,
          calendar_gap: false,
          history_count: 120,
          history_count_unit: "count",
          dod_quantity: {
            value: 2.0,
            unit: "basis_points",
            quality: "observed",
            source_id: "derived:dod_gate",
          },
          source_id: "derived:dod_gate",
        },
        {
          tenor: "5Y",
          prev_date: "2026-10-29",
          current_date: MOCK_DATE,
          prev_yield_percent: 3.6,
          current_yield_percent: 3.62,
          prev_yield_unit: "percent",
          current_yield_unit: "percent",
          dod_bp: null,
          dod_unit: "basis_points",
          gate: "switch_break",
          switch_in_window: true,
          calendar_gap: false,
          history_count: 120,
          history_count_unit: "count",
          dod_quantity: {
            value: null,
            unit: "basis_points",
            quality: "missing",
            source_id: "derived:dod_gate",
          },
          source_id: "derived:dod_gate",
        },
        {
          tenor: "10Y",
          prev_date: "2026-10-28",
          current_date: MOCK_DATE,
          prev_yield_percent: 3.88,
          current_yield_percent: 3.9,
          prev_yield_unit: "percent",
          current_yield_unit: "percent",
          dod_bp: 2.0,
          dod_unit: "basis_points",
          gate: "calendar_gap",
          switch_in_window: false,
          calendar_gap: true,
          history_count: 120,
          history_count_unit: "count",
          dod_quantity: {
            value: 2.0,
            unit: "basis_points",
            quality: "observed",
            source_id: "derived:dod_gate",
          },
          source_id: "derived:dod_gate",
        },
        {
          tenor: "30Y",
          prev_date: "2026-10-29",
          current_date: MOCK_DATE,
          prev_yield_percent: 4.18,
          current_yield_percent: 4.19,
          prev_yield_unit: "percent",
          current_yield_unit: "percent",
          dod_bp: 1.0,
          dod_unit: "basis_points",
          gate: "comparable",
          switch_in_window: false,
          calendar_gap: false,
          history_count: 120,
          history_count_unit: "count",
          dod_quantity: {
            value: 1.0,
            unit: "basis_points",
            quality: "observed",
            source_id: "derived:dod_gate",
          },
          source_id: "derived:dod_gate",
        },
      ],
    },
  },
  provenance: {
    valet: {
      source_url: "https://www.bankofcanada.ca/valet/",
      retrieved_utc: "2026-10-31T00:00:00Z",
      vintage: "2026-10-30",
    },
    benchmark_switches: {
      source_url: "https://www.bankofcanada.ca/stats/assets/pdf/bench_CDN.pdf",
      retrieved_utc: "2026-10-31T00:00:00Z",
      vintage: "2026-11-01",
      sha256: "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
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
  passed_count: 23,
  failed_count: 0,
  passed: true,
  snapshot_sha256: MOCK_SHA256,
  checks: Array.from({ length: 23 }, (_, i) => {
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
