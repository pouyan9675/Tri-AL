/**
 * What a whole is made of: one bar per row, split into the spec's `series`, each part shown as
 * its share of the bar (so every bar is 100%). Years run left to right as columns; other
 * categories are horizontal bars with their names on the left. The tooltip gives each part's
 * share and, for counts, the count.
 */
import { useMemo } from "react";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import type { ChartRow, ChartSpec } from "@/api/client";
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
} from "@/components/ui/chart";
import { formatPercent } from "@/lib/format";
import { useWidth } from "@/lib/use-width";
import {
  axisPercent,
  fitText,
  formatted,
  points,
  type SeriesInfo,
  seriesOf,
  textWidth,
  type WidgetProps,
} from "./common";

const ROW = 26;
const FONT = 12;
const LEGEND = 36;
const YEAR = /^\d{4}$/;

type Part = SeriesInfo & { dataKey: string; color: string };
type Datum = { label: string; total: number; values: number[] } & Record<string, unknown>;

/** The rows as bars of shares: each part's value over the bar's total, and the totals. */
export function stack(spec: ChartSpec, rows: ChartRow[]) {
  const parts: Part[] = seriesOf(spec).map((one, i) => ({
    ...one,
    dataKey: `part${i}`,
    color: `var(--chart-${(i % 8) + 1})`,
  }));
  const data: Datum[] = points(spec, rows).map(({ label, row }) => {
    const values = parts.map((part) => {
      const value = Number(row[part.key]);
      return Number.isFinite(value) && value > 0 ? value : 0;
    });
    const total = values.reduce((sum, value) => sum + value, 0);
    return {
      label,
      total,
      values,
      ...Object.fromEntries(
        parts.map((part, i) => [part.dataKey, total ? (values[i] ?? 0) / total : 0]),
      ),
    };
  });
  const config: ChartConfig = Object.fromEntries(
    parts.map((part) => [part.dataKey, { label: part.label, color: part.color }]),
  );
  return { data, parts, config };
}

export function StackedWidget({ spec, rows, height }: WidgetProps) {
  const { data, parts, config } = useMemo(() => stack(spec, rows), [spec, rows]);
  const [ref, width] = useWidth<HTMLDivElement>(480);
  const columns = data.length > 0 && data.every((point) => YEAR.test(point.label));
  const inOrder = (item: { dataKey?: unknown }) =>
    parts.findIndex((part) => part.dataKey === item.dataKey);

  const longest = Math.max(0, ...data.map((point) => textWidth(point.label, FONT)));
  const labelWidth = Math.ceil(Math.min(longest + 16, Math.max(80, width * 0.32)));
  const plotHeight = columns ? height : Math.max(height, data.length * ROW + LEGEND);

  const bars = parts.map((part, i) => (
    <Bar
      key={part.dataKey}
      dataKey={part.dataKey}
      name={part.label}
      stackId="whole"
      fill={`var(--color-${part.dataKey})`}
      maxBarSize={columns ? 36 : 20}
      radius={i === parts.length - 1 ? (columns ? [3, 3, 0, 0] : [0, 3, 3, 0]) : [0, 0, 0, 0]}
      isAnimationActive={false}
    />
  ));

  return (
    <div ref={ref} className="h-full min-h-0 w-full">
      <ChartContainer
        config={config}
        className="aspect-auto h-full w-full"
        style={{ minHeight: plotHeight }}
        initialDimension={{ width, height: plotHeight }}
      >
        {columns ? (
          <BarChart
            accessibilityLayer
            data={data}
            margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
            barCategoryGap="18%"
          >
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              minTickGap={8}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              width={44}
              domain={[0, 1]}
              ticks={[0, 0.25, 0.5, 0.75, 1]}
              tickFormatter={axisPercent}
            />
            <ChartTooltip
              cursor={{ className: "fill-muted/70" }}
              content={<StackTooltip parts={parts} />}
            />
            <ChartLegend itemSorter={inOrder} content={<ChartLegendContent />} />
            {bars}
          </BarChart>
        ) : (
          <BarChart
            accessibilityLayer
            data={data}
            layout="vertical"
            margin={{ top: 0, right: 8, bottom: 0, left: 0 }}
            barCategoryGap="20%"
          >
            <XAxis type="number" hide domain={[0, 1]} />
            <YAxis
              type="category"
              dataKey="label"
              width={labelWidth}
              tickLine={false}
              axisLine={false}
              interval={0}
              tick={({ x, y, payload }) => (
                <text
                  x={Number(x) - 8}
                  y={Number(y)}
                  dy={4}
                  textAnchor="end"
                  fontSize={FONT}
                  className="fill-muted-foreground"
                >
                  <title>{String(payload.value)}</title>
                  {fitText(String(payload.value), labelWidth - 12, FONT)}
                </text>
              )}
            />
            <ChartTooltip
              cursor={{ className: "fill-muted/70" }}
              content={<StackTooltip parts={parts} />}
            />
            <ChartLegend itemSorter={inOrder} content={<ChartLegendContent />} />
            {bars}
          </BarChart>
        )}
      </ChartContainer>
    </div>
  );
}

type TooltipProps = {
  active?: boolean;
  payload?: { payload?: Datum }[];
  parts: Part[];
};

/** Each part's share of the bar, biggest first, with its count when the series is counts. */
function StackTooltip({ active, payload, parts }: TooltipProps) {
  const datum = payload?.[0]?.payload;
  if (!active || !datum) return null;
  const order = parts
    .map((part, i) => ({ part, value: datum.values[i] ?? 0 }))
    .filter(({ value }) => value > 0)
    .sort((a, b) => b.value - a.value);
  return (
    <div className="grid min-w-44 gap-1 rounded-lg border border-border/60 bg-popover px-2.5 py-1.5 text-xs shadow-lg">
      <span className="text-muted-foreground">{datum.label}</span>
      {order.map(({ part, value }) => (
        <div key={part.dataKey} className="flex items-center gap-2">
          <span className="h-3 w-1 shrink-0 rounded-full" style={{ background: part.color }} />
          <span className="text-popover-foreground">{part.label}</span>
          <span className="ml-auto pl-4 font-semibold tabular text-popover-foreground">
            {formatPercent(datum.total ? value / datum.total : 0)}
          </span>
          {part.format === "number" && (
            <span className="w-14 text-right text-muted-foreground tabular">
              {formatted(value, "number")}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
