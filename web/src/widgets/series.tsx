/**
 * Area and line charts: one series over `x` (dates or categories), with a crosshair tooltip.
 * Dates (`YYYY-MM-DD`) are shown as "Oct 3".
 */
import { useId, useMemo } from "react";
import { Area, AreaChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import { type ChartConfig, ChartContainer, ChartTooltip } from "@/components/ui/chart";
import { formatDate, formatShortDate } from "@/lib/format";
import { axisNumber, points, type WidgetProps } from "./common";
import { SingleTooltip } from "./tooltip";

const DATE = /^\d{4}-\d{2}-\d{2}/;

function useSeries({ spec, rows }: WidgetProps) {
  const data = useMemo(() => points(spec, rows), [spec, rows]);
  const dates = data.length > 0 && data.every((point) => DATE.test(point.label));
  const config = { value: { label: spec.title, color: "var(--chart-1)" } } satisfies ChartConfig;
  return { data, dates, config };
}

function axes(dates: boolean) {
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
      content={<SingleTooltip formatLabel={dates ? formatDate : undefined} />}
    />,
  ];
}

export function AreaWidget(props: WidgetProps) {
  const { data, dates, config } = useSeries(props);
  const gradient = `fill-${useId().replace(/:/g, "")}`;
  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height: props.height }}>
      <AreaChart accessibilityLayer data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-value)" stopOpacity={0.22} />
            <stop offset="100%" stopColor="var(--color-value)" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        {axes(dates)}
        <Area
          dataKey="value"
          type="linear"
          stroke="var(--color-value)"
          strokeWidth={2}
          fill={`url(#${gradient})`}
          activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
          isAnimationActive={false}
        />
      </AreaChart>
    </ChartContainer>
  );
}

export function LineWidget(props: WidgetProps) {
  const { data, dates, config } = useSeries(props);
  return (
    <ChartContainer config={config} className="aspect-auto w-full" style={{ height: props.height }}>
      <LineChart accessibilityLayer data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        {axes(dates)}
        <Line
          dataKey="value"
          type="linear"
          stroke="var(--color-value)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
          isAnimationActive={false}
        />
      </LineChart>
    </ChartContainer>
  );
}
