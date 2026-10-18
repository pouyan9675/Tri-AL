/** What every widget shares: the rows a chart spec's `x` and `y` keys point at. */
import type { ChartRow, ChartSpec } from "@/api/client";
import type { TrialFilter } from "@/lib/filters";
import { formatCompact, formatNumber } from "@/lib/format";

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

export const axisNumber = (value: number) => formatCompact(value);
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
