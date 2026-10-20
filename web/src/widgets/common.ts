/** What every widget shares: the rows a chart spec's `x` and `y` keys point at. */
import type { ChartRow, ChartSpec } from "@/api/client";
import type { TrialFilter } from "@/lib/filters";
import { formatCompact, formatNumber, formatValue, type NumberFormat } from "@/lib/format";

export type WidgetProps = {
  spec: ChartSpec;
  rows: ChartRow[];
  /** Pixels the widget's plot should take (the layout's height × a row height). */
  height: number;
  /** The page's filter, which the rows were computed under. */
  filter?: TrialFilter;
};

export type Point = { label: string; value: number; row: ChartRow };

/** The rows as label/value points, reading the spec's `x` and `y` keys. */
export function points(spec: ChartSpec, rows: ChartRow[]): Point[] {
  return rows.map((row) => {
    const label = row[spec.x];
    const value = Number(row[spec.y] ?? 0);
    return {
      label: label === null || label === undefined ? "—" : String(label),
      value: Number.isFinite(value) ? value : 0,
      row,
    };
  });
}

export type SeriesInfo = { key: string; label: string; format: NumberFormat };

/** The numbers each row has: the spec's series, or its one number, `y`. */
export function seriesOf(spec: ChartSpec): SeriesInfo[] {
  const series = spec.series.length > 0 ? spec.series : [{ key: spec.y, label: spec.title }];
  return series.map((one) => ({
    key: one.key,
    label: one.label,
    format: ("format" in one && one.format) || spec.format,
  }));
}

/** A number as its series or chart reads it; null is "—". */
export function formatted(value: unknown, format: NumberFormat): string {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  return Number.isFinite(number) ? formatValue(number, format) : String(value);
}

/**
 * Two series stay in the app's blue: the brand blue and the deepest step of the blue ramp
 * (navy on light, pale on dark, far enough apart to tell even with color blindness). More
 * need hues of their own, in the chart palette's order.
 */
export function seriesColors(count: number): string[] {
  if (count === 2) return ["var(--chart-1)", "var(--seq-700)"];
  return Array.from({ length: count }, (_, i) => `var(--chart-${(i % 8) + 1})`);
}

export const axisNumber = (value: number) => formatCompact(value);
export const axisPercent = (value: number) => `${Math.round(value * 100)}%`;
export const fullNumber = (value: unknown) =>
  typeof value === "number" ? formatNumber(value) : String(value ?? "");

let canvas: CanvasRenderingContext2D | null | undefined;

/** The width of `text` in the UI font at `size` px (an estimate where there's no canvas). */
export function textWidth(text: string, size = 12): number {
  if (canvas === undefined) {
    try {
      canvas = document.createElement("canvas").getContext("2d");
    } catch {
      canvas = null;
    }
  }
  if (canvas) {
    canvas.font = `${size}px "Geist Variable", ui-sans-serif, system-ui, sans-serif`;
    const width = canvas.measureText(text).width;
    // A little extra, in case the page draws it in a slightly wider face than was measured.
    if (width > 0) return width * 1.04;
  }
  return text.length * size * 0.58;
}

/** `text` cut with an ellipsis to fit in `width` px. */
export function fitText(text: string, width: number, size = 12): string {
  if (textWidth(text, size) <= width) return text;
  let low = 0;
  let high = text.length;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (textWidth(`${text.slice(0, mid).trimEnd()}…`, size) <= width) low = mid;
    else high = mid - 1;
  }
  return `${text.slice(0, low).trimEnd()}…`;
}
