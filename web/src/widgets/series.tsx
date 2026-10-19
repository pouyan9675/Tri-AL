/**
 * Area and line charts over `x` (dates or categories), with a crosshair tooltip. A spec with
 * several `series` gets a line or area for each, in its own color, and a legend; otherwise the
 * one series is `y`. Dates (`YYYY-MM-DD`) are shown as "Oct 3".
 */
import { useId, useMemo } from "react";
import { Area, AreaChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
} from "@/components/ui/chart";
import { formatDate, formatShortDate } from "@/lib/format";
import { axisNumber, points, type WidgetProps } from "./common";
import { MultiTooltip, SingleTooltip } from "./tooltip";

const DATE = /^\d{4}-\d{2}-\d{2}/;

/**
 * Two series stay in the app's blue: the brand blue and the deepest step of the blue ramp
 * (navy on light, pale on dark, far enough apart to tell even with color blindness). More
 * need hues of their own, in the chart palette's order.
 */
function colors(count: number): string[] {
  if (count === 2) return ["var(--chart-1)", "var(--seq-700)"];
  return Array.from({ length: count }, (_, i) => `var(--chart-${(i % 8) + 1})`);
}

/**
 * The points, each with a number per series under `keys`: `value` for one series, or
 * `series0`, `series1`… (safe as CSS variable names, whatever the row keys are).
 */
function useSeries({ spec, rows }: WidgetProps) {
  return useMemo(() => {
    const series = spec.series.length > 0 ? spec.series : [{ key: spec.y, label: spec.title }];
    const several = series.length > 1;
    const palette = colors(series.length);
    const lines = series.map((one, i) => ({
      key: several ? `series${i}` : "value",
      label: one.label,
      color: palette[i],
      values: points({ ...spec, y: one.key }, rows).map((point) => point.value),
    }));
    const data = points(spec, rows).map(({ label, row }, i) => ({
      label,
      row,
      ...Object.fromEntries(lines.map((line) => [line.key, line.values[i] ?? 0])),
    }));
    const config: ChartConfig = Object.fromEntries(
      lines.map(({ key, label, color }) => [key, { label, color }]),
    );
    const dates = data.length > 0 && data.every((point) => DATE.test(point.label));
    return { data, keys: lines.map((line) => line.key), config, dates };
  }, [spec, rows]);
}

function axes(dates: boolean, keys: string[]) {
  const formatLabel = dates ? formatDate : undefined;
  const inOrder = (item: { dataKey?: unknown }) => keys.indexOf(String(item.dataKey));
  return [
    <CartesianGrid key="grid" vertical={false} stroke="var(--chart-grid)" />,
    <XAxis
      key="x"
      dataKey="label"
      tickLine={false}
      axisLine={false}
      tickMargin={8}
      minTickGap={28}
      tickFormatter={dates ? formatShortDate : undefined}
    />,
    <YAxis
      key="y"
      tickLine={false}
      axisLine={false}
      tickMargin={4}
      width={44}
      tickFormatter={axisNumber}
      allowDecimals={false}
    />,
    <ChartTooltip
      key="tooltip"
      cursor={{ stroke: "var(--border)", strokeWidth: 1 }}
      content={
        keys.length > 1 ? (
          <MultiTooltip formatLabel={formatLabel} order={inOrder} />
        ) : (
          <SingleTooltip formatLabel={formatLabel} />
        )
      }
    />,
    keys.length > 1 && (
      <ChartLegend key="legend" itemSorter={inOrder} content={<ChartLegendContent />} />
    ),
  ];
}

/** Last series first, so the first is drawn on top; the legend and tooltip keep spec order. */
const backToFront = (keys: string[]) => [...keys].reverse();

export function AreaWidget(props: WidgetProps) {
  const { data, keys, config, dates } = useSeries(props);
  const gradient = `fill-${useId().replace(/:/g, "")}`;
  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height: props.height }}>
      <AreaChart accessibilityLayer data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          {keys.map((key) => (
            <linearGradient key={key} id={`${gradient}-${key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={`var(--color-${key})`} stopOpacity={0.22} />
              <stop offset="100%" stopColor={`var(--color-${key})`} stopOpacity={0.02} />
            </linearGradient>
          ))}
        </defs>
        {axes(dates, keys)}
        {backToFront(keys).map((key) => (
          <Area
            key={key}
            dataKey={key}
            name={String(config[key]?.label ?? key)}
            type="monotone"
            stroke={`var(--color-${key})`}
            strokeWidth={2}
            fill={`url(#${gradient}-${key})`}
            activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
            isAnimationActive={false}
          />
        ))}
      </AreaChart>
    </ChartContainer>
  );
}

export function LineWidget(props: WidgetProps) {
  const { data, keys, config, dates } = useSeries(props);
  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height: props.height }}>
      <LineChart accessibilityLayer data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        {axes(dates, keys)}
        {backToFront(keys).map((key) => (
          <Line
            key={key}
            dataKey={key}
            name={String(config[key]?.label ?? key)}
            type="monotone"
            stroke={`var(--color-${key})`}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ChartContainer>
  );
}
