import { createEffect, onCleanup, onMount } from "solid-js";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import type { ChartBand } from "../lib/types";

export interface ChartPoint {
  x: number;
  y: number | null;
}

interface Props {
  title: string;
  xLabel: string;
  yLabel: string;
  series: { label: string; points: ChartPoint[]; color: string; dash?: number[]; width?: number }[];
  /** Number uses raw values, date treats x as epoch seconds and ticks YYYY-MM-DD. */
  xKind?: "number" | "date";
  /** Charts sharing a key sync crosshairs. One key per page, never across pages. */
  syncKey?: string;
  /** Shaded x spans behind the series, applied on date axes only. */
  bands?: ChartBand[];
  /** Sentence appended to the caption after the default text, units always. */
  note?: string;
}

interface BuiltData {
  xs: number[];
  data: uPlot.AlignedData;
}

/**
 * Render caps: charts align every series onto one x grid, so an
 * excessive frame is refused before uPlot construction instead of
 * allocating unbounded aligned arrays. Limits mirror the validator
 * collection caps (spreads and backtest at 2000 observations).
 */
export const MAX_CHART_SERIES = 16;
/**
 * Phase 8.4 aggregation contract: the render path must keep every series
 * at or below 2000 points at Max range over 2750 daily rows, so this cap
 * stays fixed while the history caps are raised to 10 years.
 */
export const MAX_CHART_POINTS = 2000;

function toData(series: Props["series"]): BuiltData {
  const xs = new Set<number>();
  for (const s of series) for (const p of s.points) xs.add(p.x);
  const sortedX = [...xs].sort((a, b) => a - b);
  const aligned: (number | null)[][] = series.map((s) => {
    const byX = new Map(s.points.map((p) => [p.x, p.y]));
    return sortedX.map((x) => byX.get(x) ?? null);
  });
  return { xs: sortedX, data: [sortedX, ...aligned] as uPlot.AlignedData };
}

/** Tick formatter for epoch second axes. Guards NaN so gaps never print Invalid Date. */
export function formatDateTick(epochSec: number): string {
  if (!Number.isFinite(epochSec)) return "";
  const date = new Date(epochSec * 1000);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 10);
}

/**
 * Paint band fills on the cleared canvas. uPlot fires drawClear after
 * clearRect and before the axes and series draw order, so shading sits
 * behind every line. Coordinates are device pixels: valToPos with canvas
 * pixels and the bbox clip both read the same device pixel space as the
 * canvas backing store, and the clip keeps shading inside the plot area so
 * axis gutters stay clean. A band outside the current x scale maps to a
 * position past the plot edge and is clipped away rather than wrapped.
 */
function paintBands(u: uPlot, bands: ChartBand[]): void {
  if (bands.length === 0) return;
  const box = u.bbox;
  const { left, top, width, height } = box;
  if (![left, top, width, height].every(Number.isFinite)) return;
  if (width <= 0 || height <= 0) return;
  const ctx = u.ctx;
  ctx.save();
  ctx.beginPath();
  ctx.rect(left, top, width, height);
  ctx.clip();
  for (const band of bands) {
    if (!(band.x1 > band.x0)) continue;
    const x0 = u.valToPos(band.x0, "x", true);
    const x1 = u.valToPos(band.x1, "x", true);
    if (!Number.isFinite(x0) || !Number.isFinite(x1)) continue;
    const start = Math.min(x0, x1);
    const span = Math.abs(x1 - x0);
    if (span <= 0) continue;
    ctx.fillStyle = band.fill;
    ctx.fillRect(start, top, span, height);
  }
  ctx.restore();
}

export default function Chart(props: Props) {
  let host: HTMLDivElement | undefined;
  let plot: uPlot | null = null;
  let seriesCount = -1;
  let raf = 0;

  const xKind = (): "number" | "date" => props.xKind ?? "number";

  /** Bands apply on date axes only, so a number axis never shades. */
  const bandList = (): ChartBand[] =>
    xKind() === "date" ? props.bands ?? [] : [];

  /**
   * Presentation signature: every option baked into uPlot construction
   * (labels, colors, dash, width, axis kind, sync key, axis titles, bands).
   * Data alone flows through setData, but a signature change rebuilds
   * the plot so stale labels, colors, dash, xKind, sync keys, or band
   * shading never linger when the series count is unchanged.
   */
  const signature = (): string =>
    JSON.stringify({
      title: props.title,
      xLabel: props.xLabel,
      yLabel: props.yLabel,
      xKind: xKind(),
      syncKey: props.syncKey ?? null,
      series: props.series.map((s) => [s.label, s.color, s.dash ?? null, s.width ?? 2]),
      bands: bandList().map((band) => [band.x0, band.x1, band.fill]),
    });
  let lastSignature = "";

  const excessive = (): boolean => {
    if (props.series.length > MAX_CHART_SERIES) return true;
    let total = 0;
    for (const s of props.series) {
      if (s.points.length > MAX_CHART_POINTS) return true;
      total += s.points.length;
    }
    return total > MAX_CHART_SERIES * MAX_CHART_POINTS;
  };

  const measure = (): number => {
    if (!host) return 0;
    return Math.floor(host.clientWidth);
  };

  const build = () => {
    if (!host) return;
    destroyPlot();
    if (excessive()) return;
    const built = toData(props.series);
    if (built.xs.length === 0) return;
    const width = measure();
    if (width <= 0) return;
    seriesCount = props.series.length;
    lastSignature = signature();
    const kind = xKind();
    const bands = bandList();
    const opts: uPlot.Options = {
      width,
      height: 300,
      legend: { show: true },
      cursor: props.syncKey
        ? { show: true, sync: { key: props.syncKey, setSeries: true } }
        : { show: true },
      scales: kind === "date" ? { x: { time: true } } : undefined,
      axes: [
        {
          label: props.xLabel,
          values:
            kind === "date"
              ? (_u, vals) => vals.map((v) => formatDateTick(v))
              : (_u, vals) => vals.map((v) => String(v)),
        },
        { label: props.yLabel },
      ],
      series: [
        {},
        ...props.series.map((s) => ({
          label: s.label,
          stroke: s.color,
          width: s.width ?? 2,
          dash: s.dash,
          points: { show: false },
          spanGaps: false,
        })),
      ],
    };
    // Bands are captured here, and a band change alters the signature, so
    // the hook always paints the current shading and never a stale copy.
    if (bands.length > 0) {
      opts.hooks = { drawClear: [(u) => paintBands(u, bands)] };
    }
    plot = new uPlot(opts, built.data, host);
  };

  const destroyPlot = () => {
    if (plot) {
      try {
        plot.destroy();
      } catch {
        // noop
      }
      plot = null;
    }
    if (host) host.innerHTML = "";
    seriesCount = -1;
    lastSignature = "";
  };

  const resize = () => {
    if (!plot || !host) return;
    const width = measure();
    if (width <= 0) return;
    plot.setSize({ width, height: 300 });
  };

  const onResize = () => {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      resize();
    });
  };

  let observer: ResizeObserver | null = null;
  onMount(() => {
    build();
    if (host && typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(onResize);
      observer.observe(host);
    } else {
      window.addEventListener("resize", onResize);
    }
  });

  createEffect(() => {
    const series = props.series;
    const sig = signature();
    if (!plot || !host) return;
    if (series.length !== seriesCount || sig !== lastSignature) {
      build();
      return;
    }
    plot.setData(toData(series).data);
  });

  onCleanup(() => {
    if (raf) cancelAnimationFrame(raf);
    destroyPlot();
    if (observer) observer.disconnect();
    window.removeEventListener("resize", onResize);
  });

  return (
    <figure style={{ margin: 0 }}>
      {excessive() ? (
        <p role="alert">
          Chart refused: {props.series.length} series exceed the cap of{" "}
          {MAX_CHART_SERIES} series and {MAX_CHART_POINTS} points per series for{" "}
          {props.title}. Pick a narrower view.
        </p>
      ) : (
        <div class="chart-shell" ref={host} role="img" aria-label={props.title} />
      )}
      <figcaption class="figure-caption">
        {props.title}: {props.yLabel}.
        {props.note ? " " + props.note : ""}
      </figcaption>
    </figure>
  );
}
