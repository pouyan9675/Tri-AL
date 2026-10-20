/**
 * Estimates with confidence intervals, a row each, on a log scale with a line at 1 (no
 * difference): the shape safety signals and effect sizes come in. Each row is named by `x`
 * (and a muted `detail` under it), its estimate is `y` and its interval `low` to `high`; the
 * spec's `series` are columns of numbers beside it. Plain HTML, positioned in percentages, so
 * it needs no measuring and labels wrap and cut like the rest of the page.
 */
import { useMemo } from "react";
import { cn } from "@/lib/utils";
import { formatted, type WidgetProps } from "./common";

const TICKS = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];

type Item = {
  label: string;
  detail: string | null;
  estimate: number;
  low: number;
  high: number;
  row: Record<string, unknown>;
};

/** A ratio as it's usually written: two decimals below 10, fewer above. */
export function formatRatio(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return value >= 100 ? value.toFixed(0) : value >= 10 ? value.toFixed(1) : value.toFixed(2);
}

/** Where a value sits on the log scale from `low` to `high`, as a percentage. */
export function scale(low: number, high: number) {
  const from = Math.log(low);
  const span = Math.log(high) - from || 1;
  return (value: number) => Math.min(100, Math.max(0, ((Math.log(value) - from) / span) * 100));
}

export function ForestWidget({ spec, rows, height }: WidgetProps) {
  const { items, domain, ticks } = useMemo(() => {
    const items: Item[] = rows
      .map((row) => ({
        label: String(row[spec.x] ?? "—"),
        detail: typeof row.detail === "string" ? row.detail : null,
        estimate: Number(row[spec.y]),
        low: Number(row.low),
        high: Number(row.high),
        row,
      }))
      .filter((item) => item.estimate > 0 && item.low > 0 && item.high > 0);
    const low = Math.max(0.01, Math.min(1, ...items.map((item) => item.low)) / 1.15);
    const high = Math.min(1000, Math.max(1, ...items.map((item) => item.high)) * 1.15);
    let ticks = TICKS.filter((tick) => tick >= low && tick <= high);
    if (ticks.length > 7) ticks = ticks.filter((tick, i) => tick === 1 || i % 2 === 0);
    return { items, domain: [low, high] as const, ticks };
  }, [rows, spec.x, spec.y]);
  const x = scale(domain[0], domain[1]);
  const columns = spec.series;

  return (
    <div className="overflow-auto" style={{ maxHeight: Math.max(height, 240) }}>
      <table className="w-full min-w-[36rem] border-collapse text-xs">
        <colgroup>
          <col className="w-[30%]" />
          <col />
          <col className="w-28" />
          {columns.map((column) => (
            <col key={column.key} className="w-20" />
          ))}
        </colgroup>
        <thead className="text-muted-foreground">
          <tr>
            <th />
            <th className="px-2 pb-1.5 text-center font-normal">Log scale, 1 is no difference</th>
            <th className="px-2 pb-1.5 text-right font-normal">Estimate (95% CI)</th>
            {columns.map((column) => (
              <th key={column.key} className="pb-1.5 pl-2 text-right font-normal">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={`${item.label}-${item.detail}`} className="border-t" data-testid="forest-row">
              <td className="max-w-0 py-1.5 pr-2">
                <span className="block truncate font-medium" title={item.label}>
                  {item.label}
                </span>
                {item.detail && <span className="block text-muted-foreground">{item.detail}</span>}
              </td>
              <td className="relative px-2">
                <span className="relative block h-8">
                  <span
                    className="absolute inset-y-0 border-l border-dashed border-muted-foreground/50"
                    style={{ left: `${x(1)}%` }}
                  />
                  <span
                    className="absolute top-1/2 h-0.5 -translate-y-1/2 rounded-full bg-(--chart-1)"
                    style={{ left: `${x(item.low)}%`, width: `${x(item.high) - x(item.low)}%` }}
                  />
                  <span
                    className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rotate-45 bg-(--chart-1) ring-2 ring-card"
                    style={{ left: `${x(item.estimate)}%` }}
                  />
                </span>
              </td>
              <td className="px-2 py-1.5 text-right whitespace-nowrap tabular">
                <span className="font-semibold">{formatRatio(item.estimate)}</span>{" "}
                <span className="text-muted-foreground">
                  ({formatRatio(item.low)}–{formatRatio(item.high)})
                </span>
              </td>
              {columns.map((column) => (
                <td key={column.key} className="py-1.5 pl-2 text-right tabular">
                  {formatted(item.row[column.key], column.format ?? spec.format)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t">
            <td />
            <td className="px-2">
              <span className="relative block h-5">
                {ticks.map((tick) => (
                  <span
                    key={tick}
                    className={cn(
                      "absolute top-1 -translate-x-1/2 text-[0.65rem] tabular",
                      tick === 1 ? "font-semibold text-foreground" : "text-muted-foreground",
                    )}
                    style={{ left: `${x(tick)}%` }}
                  >
                    {tick}
                  </span>
                ))}
              </span>
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
