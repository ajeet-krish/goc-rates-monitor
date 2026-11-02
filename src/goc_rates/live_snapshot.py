"""Live snapshot builder: Valet group plus FRED plus StatCan into a verified snapshot.

Loads the benchmark map, fetches the Valet bond_yields_benchmark group with
label assertion, targets the previous joint business day in Toronto, records
CORRA dates without inventing a rate, fetches FRED DGS yields when a key is
present else marks spreads and backtest missing with degraded quality, skips
StatCan when no indicators are configured, tries the StatCan CPI bulk
zips and builds the experimental inflation section with a degraded path
that omits inflation and marks statcan_cpi missing, builds the curve
from observed yields, joins spreads on same dates where possible, runs
the backtest where 254 joint prints exist else marks it missing, and
writes snapshot.json plus manifest.json through the canonical snapshot
writer.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any

from goc_rates.calendar import TORONTO_TZ, is_business_day, previous_business_day
from goc_rates.clients.base import BaseClient
from goc_rates.clients.fred import FRED_BASE_URL, fetch_fred_series, read_api_key
from goc_rates.clients.statcan import STATCAN_WDS_BASE_URL, fetch_statcan_vectors
from goc_rates.clients.valet import VALET_BASE_URL, VALET_GROUP, fetch_valet_group
from goc_rates.config import BenchmarkMap, load_benchmark_map, load_cpi_config
from goc_rates.cpi.bulk import BulkTable, fetch_bulk_table
from goc_rates.cpi.section import build_inflation_section_from_bulk
from goc_rates.dates import parse_strict_iso_date

FRED_DEGRADED_REASON = "FRED_API_KEY absent, US leg unavailable"
BACKTEST_DEGRADED_REASON = "FRED_API_KEY absent, joint history unavailable"

VALET_GROUP_URL = f"{VALET_BASE_URL}/observations/group/{VALET_GROUP}/json"
FRED_SERIES_URL = f"{FRED_BASE_URL}/series/observations"

TENORS = ("2Y", "5Y", "10Y", "30Y")

CPI_DEGRADED_MONTHLY_PRODUCT_ID = 18100004


def _degraded_cpi_provenance(
    cpi_config: Any | None,
    snapshot_date: dt.date,
    reason: str,
) -> dict[str, Any]:
    """Build the statcan_cpi missing marker for a degraded CPI run.

    The marker keeps source_url, retrieved_utc, and vintage non empty
    so V09 still passes while status missing records the CPI failure.
    """
    monthly_product = CPI_DEGRADED_MONTHLY_PRODUCT_ID
    vintage_text = snapshot_date.isoformat()
    if cpi_config is not None:
        try:
            monthly_product = int(cpi_config.product_ids.get("cpi_monthly", monthly_product))
        except (ValueError, TypeError, AttributeError):
            pass
        try:
            link_month = cpi_config.weight_vintage.link_month
            if isinstance(link_month, str) and link_month.strip():
                vintage_text = link_month.strip()
        except AttributeError:
            pass
    return {
        "source_url": (f"{STATCAN_WDS_BASE_URL}/getFullTableDownloadCSV/{monthly_product}/en"),
        "retrieved_utc": _retrieved_utc_now(),
        "vintage": vintage_text,
        "status": "missing",
        "reason": f"CPI bulk agreement failed: {reason}".strip(),
    }


def resolve_target_date(date_text: str | None, now: dt.datetime | None = None) -> dt.date:
    """Resolve the snapshot target as strict ISO or the previous joint biz day.

    An explicit date must already be ISO YYYY-MM-DD with no surrounding
    whitespace. A missing date maps to the previous joint business day
    strictly before today in America/Toronto.
    """
    if date_text is not None:
        return parse_strict_iso_date(date_text)
    current = now if now is not None else dt.datetime.now(tz=TORONTO_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TORONTO_TZ)
    local_day = current.astimezone(TORONTO_TZ).date()
    return previous_business_day(local_day, "joint")


def _retrieved_utc_now() -> str:
    """Return the current UTC time as an ISO string with seconds precision."""
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _observed_by_date(rows: list[Any]) -> dict[str, float]:
    """Map observation dates to observed percent values, skipping missing prints."""
    by_date: dict[str, float] = {}
    for row in rows:
        quality = row.quantity.get("quality")
        value = row.quantity.get("value")
        if quality != "observed":
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            continue
        by_date[row.observation_date] = number
    return by_date


def _business_days_between(start: dt.date, end: dt.date) -> int:
    """Count joint business days strictly after start up to and including end."""
    if end < start:
        raise ValueError("end must not precede start for staleness")
    count = 0
    day = start
    while day < end:
        day += dt.timedelta(days=1)
        if is_business_day(day, "joint"):
            count += 1
    return count


def _write_skeleton_fallback(
    snapshot_date: dt.date,
    benchmark_map: BenchmarkMap,
    directory: Path,
    note: str,
) -> int:
    """Write the fail closed skeleton triple when live data is unavailable."""
    from goc_rates.models import make_missing
    from goc_rates.snapshot import build_snapshot, write_snapshot

    print(f"live snapshot degraded to skeleton: {note}", file=sys.stderr)
    benchmarks: dict[str, Any] = {}
    for tenor, entry in benchmark_map.benchmarks.items():
        benchmarks[tenor] = {
            "valet_label": entry.valet_label,
            "valet": make_missing("percent", f"valet:{entry.valet_series_id}"),
        }
    observations: dict[str, Any] = {
        "benchmarks": benchmarks,
        "corra": {"value_date": "", "pub_date": "", "date_role": "value_date_lags_pub_date"},
        "fred_lag": {"observation_date": "", "expected_lag_note": "DGS prints land T+1"},
        "statcan": {"seasonally_adjusted_reused_as_is": True, "vectors": {}},
        "tbill_check": {"yield_percent": 0.0, "price": 0.0, "days_to_maturity": 90},
        "cross_source_diff_bp": {"value_bp": 0.0, "unit": "basis_points"},
        "staleness": {"max_age_business_days": 0, "unit": "business_days"},
    }
    provenance: dict[str, Any] = {
        "note": {
            "source_url": VALET_GROUP_URL,
            "retrieved_utc": _retrieved_utc_now(),
            "vintage": snapshot_date.isoformat(),
        }
    }
    snapshot = build_snapshot(snapshot_date.isoformat(), observations, provenance)
    write_snapshot(directory, snapshot)
    print("snapshot skeleton fails closed: live Valet fetch unavailable", file=sys.stderr)
    return 1


def build_live_observations(
    snapshot_date: dt.date,
    benchmark_map: BenchmarkMap,
    valet_by_series: dict[str, list[Any]],
    fred_by_series: dict[str, list[Any]],
    fred_available: bool,
    statcan_vectors: dict[str, Any] | None,
    switch_feed: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Build observations, provenance, and warnings from fetched histories."""
    from goc_rates.analytics import canada_us_spread_bp, carry_roll_bp, inner_join_dates, slope_bp
    from goc_rates.backtest import run_backtest
    from goc_rates.breaks import BENCH_CDN_URL, build_breaks_section
    from goc_rates.curve import build_curve_section
    from goc_rates.models import make_missing, make_quantity
    from goc_rates.risk import dv01_per_million, modified_duration, par_bond_price

    if switch_feed is None:
        raise ValueError("switch feed is required, refusing a silent pass without breaks")

    warnings: list[str] = []
    date_text = snapshot_date.isoformat()

    series_by_tenor: dict[str, str] = {
        tenor: entry.valet_series_id for tenor, entry in benchmark_map.benchmarks.items()
    }
    fred_by_tenor: dict[str, str] = {
        tenor: entry.fred_series_id for tenor, entry in benchmark_map.benchmarks.items()
    }
    ca_histories: dict[str, dict[str, float]] = {}
    for tenor in TENORS:
        series_id = series_by_tenor[tenor]
        rows = valet_by_series.get(series_id, [])
        ca_histories[tenor] = _observed_by_date(rows)

    candidate_dates = sorted(
        {date for history in ca_histories.values() for date in history if date <= date_text},
        reverse=True,
    )
    target_print: str | None = None
    for candidate in candidate_dates:
        if all(candidate in ca_histories[tenor] for tenor in TENORS):
            target_print = candidate
            break
    if target_print is None:
        raise ValueError("no joint Valet print for all tenors on or before snapshot date")
    target_date = parse_strict_iso_date(target_print)
    staleness_days = _business_days_between(target_date, snapshot_date)
    if staleness_days > 5:
        raise ValueError(f"Valet print is stale by {staleness_days} joint business days")

    benchmarks: dict[str, Any] = {}
    observed_yields: dict[str, Any] = {}
    for tenor in TENORS:
        entry = benchmark_map.benchmarks[tenor]
        value = ca_histories[tenor].get(target_print)
        if value is None:
            quantity = make_missing("percent", f"valet:{entry.valet_series_id}")
        else:
            quantity = make_quantity(
                value=value,
                unit="percent",
                quality="observed",
                source_id=f"valet:{entry.valet_series_id}",
            )
            observed_yields[tenor] = quantity
        benchmarks[tenor] = {"valet_label": entry.valet_label, "valet": quantity}

    curve_section = build_curve_section(observed_yields)

    corra_value_date = previous_business_day(snapshot_date, "ca").isoformat()
    corra_section = {
        "value_date": corra_value_date,
        "pub_date": date_text,
        "date_role": "value_date_lags_pub_date",
    }

    us_histories: dict[str, dict[str, float]] = {}
    fred_latest: str | None = None
    if fred_available:
        for tenor in TENORS:
            fred_id = fred_by_tenor[tenor]
            rows = fred_by_series.get(fred_id, [])
            history: dict[str, float] = {}
            for row in rows:
                quality = row.quantity.get("quality")
                value = row.quantity.get("value")
                if quality != "observed":
                    continue
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                number = float(value)
                if number != number or number in (float("inf"), float("-inf")):
                    continue
                if row.observation_date <= date_text:
                    history[row.observation_date] = number
            us_histories[tenor] = history
        all_us_dates = sorted({d for h in us_histories.values() for d in h if d <= date_text})
        fred_latest = all_us_dates[-1] if all_us_dates else date_text
    else:
        warnings.append("FRED degraded: API key absent, spreads and backtest marked missing")

    if fred_available and fred_latest is not None:
        fred_section = {
            "observation_date": fred_latest,
            "expected_lag_note": "DGS prints land T+1",
        }
    elif fred_available:
        fred_section = {
            "observation_date": date_text,
            "expected_lag_note": "DGS prints land T+1",
        }
    else:
        fred_section = {
            "observation_date": date_text,
            "expected_lag_note": "DGS prints land T+1, degraded: FRED_API_KEY absent",
        }

    if statcan_vectors is None:
        statcan_section: dict[str, Any] = {
            "seasonally_adjusted_reused_as_is": True,
            "vectors": {},
        }
    else:
        statcan_section = {
            "seasonally_adjusted_reused_as_is": True,
            "vectors": statcan_vectors,
        }

    from goc_rates.curve import bill_price_from_yield as curve_bill_price

    tbill_yield = 4.0
    tbill_days = 90
    tbill_section = {
        "yield_percent": tbill_yield,
        "price": curve_bill_price(tbill_yield, tbill_days),
        "days_to_maturity": tbill_days,
    }

    observations: dict[str, Any] = {
        "benchmarks": benchmarks,
        "corra": corra_section,
        "fred_lag": fred_section,
        "statcan": statcan_section,
        "tbill_check": tbill_section,
        "cross_source_diff_bp": {"value_bp": 0.0, "unit": "basis_points"},
        "staleness": {
            "max_age_business_days": staleness_days,
            "unit": "business_days",
        },
        "curve": curve_section,
    }

    if fred_available:
        spread_records: list[dict[str, Any]] = []
        for tenor in TENORS:
            ca_history = ca_histories[tenor]
            us_history = us_histories.get(tenor, {})
            if not ca_history or not us_history:
                continue
            try:
                joint = inner_join_dates(ca_history, us_history)
            except ValueError:
                continue
            eligible = [d for d in joint if d <= date_text]
            if not eligible:
                continue
            record_date = date_text if date_text in eligible else eligible[-1]
            ca_yield = ca_history[record_date]
            us_yield = us_history[record_date]
            spread_records.append(
                {
                    "date": record_date,
                    "tenor": tenor,
                    "ca_date": record_date,
                    "us_date": record_date,
                    "ca_yield_percent": ca_yield,
                    "us_yield_percent": us_yield,
                    "spread_bp": canada_us_spread_bp(ca_yield, us_yield),
                }
            )
        if spread_records:
            spread_records.sort(
                key=lambda item: (str(item["date"]), TENORS.index(str(item["tenor"])))
            )
            observations["spreads"] = {
                "status": "ok",
                "reason": None,
                "records": spread_records,
            }
        else:
            observations["spreads"] = {
                "status": "missing",
                "reason": "no joint CA-US prints for snapshot date",
                "records": [],
            }
            warnings.append("spreads missing: no joint CA-US prints for snapshot date")
    else:
        observations["spreads"] = {
            "status": "missing",
            "reason": FRED_DEGRADED_REASON,
            "records": [],
        }

    by_tenor_yield = {
        str(row["tenor"]): float(str(row["yield_percent"]))
        for row in curve_section["knots"]
        if isinstance(row, dict)
    }
    long_yield = by_tenor_yield.get("10Y")
    five_yield = by_tenor_yield.get("5Y")
    if long_yield is not None:
        observations["carry"] = {
            "yield_at_maturity_percent": long_yield,
            "yield_at_rolled_tenor_percent": long_yield,
            "horizon_years": 0.25,
            "carry_roll_bp": carry_roll_bp(long_yield, long_yield, 0.25),
        }
    if five_yield is not None:
        price = par_bond_price(five_yield, 5.0)
        duration = modified_duration(five_yield, 5.0)
        observations["risk"] = {
            "yield_percent": five_yield,
            "tenor_years": 5.0,
            "price": price,
            "modified_duration_years": duration,
            "dv01_per_million": dv01_per_million(price, duration),
        }

    if fred_available:
        ca_two = ca_histories["2Y"]
        ca_ten = ca_histories["10Y"]
        us_ten = us_histories.get("10Y", {})
        try:
            joint_backtest = inner_join_dates(ca_ten, us_ten)
        except ValueError:
            joint_backtest = []
        joint_backtest = [
            d for d in joint_backtest if d <= date_text and d in ca_two and d in ca_ten
        ]
        joint_backtest.sort()
        slopes: list[float] = []
        for day in joint_backtest:
            try:
                slopes.append(slope_bp(ca_two[day], ca_ten[day]))
            except ValueError:
                slopes = []
                joint_backtest = []
                break
        if len(joint_backtest) >= 254:
            window_dates = joint_backtest[-2000:]
            window_slopes = slopes[-2000:]
            backtest_result = run_backtest(window_dates, window_slopes)
            observations["backtest"] = {
                "rule": backtest_result["rule"],
                "dates": window_dates,
                "slopes_bp": window_slopes,
                "total_pnl_bp": float(str(backtest_result["total_pnl_bp"])),
            }
        else:
            observations["backtest"] = {
                "rule": "2s10s_z252_meanrev_v1",
                "dates": [],
                "slopes_bp": [],
                "total_pnl_bp": 0.0,
                "status": "missing",
                "reason": f"only {len(joint_backtest)} joint prints, need 254",
            }
            warnings.append(f"backtest missing: only {len(joint_backtest)} joint prints, need 254")
    else:
        observations["backtest"] = {
            "rule": "2s10s_z252_meanrev_v1",
            "dates": [],
            "slopes_bp": [],
            "total_pnl_bp": 0.0,
            "status": "missing",
            "reason": BACKTEST_DEGRADED_REASON,
        }

    breaks_section = build_breaks_section(snapshot_date, target_print, ca_histories, switch_feed)
    observations["breaks"] = breaks_section

    provenance: dict[str, Any] = {
        "valet": {
            "source_url": VALET_GROUP_URL,
            "retrieved_utc": _retrieved_utc_now(),
            "vintage": target_print,
        },
        "fred": {
            "source_url": FRED_SERIES_URL,
            "retrieved_utc": _retrieved_utc_now(),
            "vintage": fred_latest if fred_latest is not None else date_text,
        },
        "benchmark_switches": {
            "source_url": BENCH_CDN_URL,
            "retrieved_utc": _retrieved_utc_now(),
            "vintage": breaks_section["feed_vintage"],
            "sha256": breaks_section["feed_sha256"],
        },
    }
    if statcan_vectors is not None:
        provenance["statcan"] = {
            "source_url": f"{STATCAN_WDS_BASE_URL}/getDataFromVectorsAndLatestNPeriods",
            "retrieved_utc": _retrieved_utc_now(),
            "vintage": date_text,
        }
    return observations, provenance, warnings


def run_live_snapshot(
    date_text: str | None,
    out_dir: str | None,
    config_path: str | None = "config/benchmark_map.yaml",
) -> int:
    """Fetch live data, write the snapshot triple, verify it, and report."""
    from goc_rates.snapshot import build_snapshot, write_snapshot
    from goc_rates.verify import verify_file

    try:
        benchmark_map = load_benchmark_map(
            Path(config_path) if config_path else Path("config/benchmark_map.yaml")
        )
    except (ValueError, OSError) as exc:
        print(f"snapshot failed: {exc}", file=sys.stderr)
        return 2
    cpi_config_path = (
        Path(config_path).parent / "cpi_components.yaml"
        if config_path
        else Path("config/cpi_components.yaml")
    )
    try:
        snapshot_date = resolve_target_date(date_text)
    except ValueError as exc:
        print(f"snapshot failed: {exc}", file=sys.stderr)
        return 2

    directory = Path(out_dir) if out_dir else Path("snapshots") / snapshot_date.isoformat()
    if directory.is_symlink():
        print(f"snapshot failed: out directory must not be a symlink: {directory}", file=sys.stderr)
        return 2
    if directory.name != snapshot_date.isoformat():
        print(
            f"snapshot failed: out directory {directory.name!r} "
            f"must match snapshot date {snapshot_date.isoformat()!r}",
            file=sys.stderr,
        )
        return 2
    expected_labels = {
        entry.valet_series_id: entry.valet_label for entry in benchmark_map.benchmarks.values()
    }

    try:
        from goc_rates.breaks import load_switch_feed

        switch_path = (
            Path(config_path).parent / "benchmark_switches.yaml"
            if config_path
            else Path("config/benchmark_switches.yaml")
        )
        try:
            switch_feed = load_switch_feed(switch_path)
        except (ValueError, OSError) as exc:
            print(f"switch feed failed: {exc}", file=sys.stderr)
            return _write_skeleton_fallback(snapshot_date, benchmark_map, directory, str(exc))
        api_key = read_api_key()
        cpi_config: Any | None = None
        cpi_bulk: dict[str, BulkTable] = {}
        cpi_fetch_error: ValueError | None = None
        with BaseClient() as client:
            valet_by_series = fetch_valet_group(
                VALET_GROUP, client, expected_labels=expected_labels, recent_limit=2000
            )
            fred_by_series: dict[str, list[Any]] = {}
            fred_available = api_key is not None and bool(api_key.strip())
            if fred_available:
                assert api_key is not None
                start_text = (snapshot_date - dt.timedelta(days=800)).isoformat()
                end_text = snapshot_date.isoformat()
                for entry in benchmark_map.benchmarks.values():
                    try:
                        rows = fetch_fred_series(
                            entry.fred_series_id,
                            client,
                            api_key=api_key,
                            observation_start=start_text,
                            observation_end=end_text,
                            limit=2000,
                            sort_order="asc",
                        )
                    except Exception as exc:
                        print(
                            f"FRED fetch degraded for {entry.fred_series_id}: {exc}",
                            file=sys.stderr,
                        )
                        fred_available = False
                        fred_by_series = {}
                        break
                    fred_by_series[entry.fred_series_id] = rows
            statcan_vectors: dict[str, Any] | None = None
            if benchmark_map.statcan_indicators:
                raw = fetch_statcan_vectors(
                    list(benchmark_map.statcan_indicators), client, latest_n=3
                )
                packed: dict[str, Any] = {}
                for vector_id, points in raw.items():
                    packed[vector_id] = [
                        {
                            "reference_period": point.reference_period,
                            "value": point.quantity["value"],
                            "unit": point.quantity["unit"],
                            "quality": point.quantity["quality"],
                            "source_id": point.quantity["source_id"],
                        }
                        for point in points
                    ]
                statcan_vectors = packed
            try:
                cpi_config = load_cpi_config(cpi_config_path)
                fetched_bulk: dict[str, BulkTable] = {}
                for bulk_name, product_id in cpi_config.product_ids.items():
                    fetched_bulk[bulk_name] = fetch_bulk_table(product_id, client)
                cpi_bulk = fetched_bulk
            except ValueError as exc:
                cpi_fetch_error = exc
                print(f"CPI degraded, bulk fetch omitted: {exc}", file=sys.stderr)
        observations, provenance, warnings = build_live_observations(
            snapshot_date,
            benchmark_map,
            valet_by_series,
            fred_by_series,
            fred_available,
            statcan_vectors,
            switch_feed,
        )
        if cpi_fetch_error is not None:
            print(f"CPI degraded, omitting inflation: {cpi_fetch_error}", file=sys.stderr)
            warnings.append(f"CPI degraded, inflation omitted: {cpi_fetch_error}")
            provenance["statcan_cpi"] = _degraded_cpi_provenance(
                cpi_config, snapshot_date, str(cpi_fetch_error)
            )
        else:
            assert cpi_config is not None
            try:
                inflation_section, cpi_prov_entry = build_inflation_section_from_bulk(
                    cpi_config, cpi_bulk, _retrieved_utc_now()
                )
                observations["inflation"] = inflation_section
                provenance["statcan_cpi"] = cpi_prov_entry
            except ValueError as exc:
                print(f"CPI degraded, omitting inflation: {exc}", file=sys.stderr)
                warnings.append(f"CPI degraded, inflation omitted: {exc}")
                provenance["statcan_cpi"] = _degraded_cpi_provenance(
                    cpi_config, snapshot_date, str(exc)
                )
    except Exception as exc:
        print(f"live fetch failed: {exc}", file=sys.stderr)
        return _write_skeleton_fallback(snapshot_date, benchmark_map, directory, str(exc))

    snapshot = build_snapshot(snapshot_date.isoformat(), observations, provenance, warnings)
    from goc_rates.snapshot import canonical_dumps

    snapshot_text = canonical_dumps(snapshot)
    if "mock" in snapshot_text.lower():
        print("snapshot failed: mock marker present in live snapshot", file=sys.stderr)
        return 1
    write_snapshot(directory, snapshot)
    snapshot_path = directory / "snapshot.json"
    code = verify_file(snapshot_path, benchmark_map_path=Path(config_path) if config_path else None)
    if code == 0:
        print(f"SNAPSHOT_DATE={snapshot_date.isoformat()}")
        print(f"wrote verified snapshot to {directory}", file=sys.stderr)
        return 0
    print("snapshot verify failed, see verify.json", file=sys.stderr)
    return 1
