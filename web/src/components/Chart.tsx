import { createEffect, onCleanup, onMount } from "solid-js";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

export interface ChartPoint {
  x: number;
  y: number | null;
}

interface Props {
  title: string;
  xLabel: string;
  yLabel: string;
  series: { label: string; points: ChartPoint[]; color: string }[];
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

export default function Chart(props: Props) {
  let host: HTMLDivElement | undefined;
  let plot: uPlot | null = null;
  let seriesCount = -1;
  let raf = 0;

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
    plot = new uPlot(
      {
        width,
        height: 300,
        legend: { show: true },
        cursor: { show: true },
        axes: [
          { label: props.xLabel, values: (_u, vals) => vals.map((v) => String(v)) },
          { label: props.yLabel },
        ],
        series: [
          {},
          ...props.series.map((s) => ({
            label: s.label,
            stroke: s.color,
            width: 2,
            points: { show: false },
            spanGaps: false,
          })),
        ],
      },
      built.data,
      host
    );
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
    if (!plot || !host) return;
    if (series.length !== seriesCount) {
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
          Chart refused: {props.series.length} series exceed the display cap of{" "}
          {MAX_CHART_SERIES} series and {MAX_CHART_POINTS} points per series for{" "}
          {props.title}. Pick a narrower view.
        </p>
      ) : (
        <div class="chart-shell" ref={host} role="img" aria-label={props.title} />
      )}
      <figcaption class="figure-caption">
        {props.title}: {props.yLabel}. Axis labels carry units always.
      </figcaption>
    </figure>
  );
}
