/**
 * Bars, horizontal: category names on the left (cut to fit, whole on hover), one bar per
 * row in the API's order, and the value at each bar's tip. A spec with several `series`
 * gets a bar for each, side by side in its own color, with a legend; values read as the
 * series' (or the chart's) `format`.
 */
import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, LabelList, XAxis, YAxis } from "recharts";
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
} from "@/components/ui/chart";
import { useWidth } from "@/lib/use-width";
import {
  fitText,
  formatted,
  points,
  seriesColors,
  seriesOf,
  textWidth,
  type WidgetProps,
} from "./common";
import { MultiTooltip, SingleTooltip } from "./tooltip";

const ROW = 30;
const SERIES_ROW = 18; // each further bar in a group
const FONT = 12;

export function BarWidget({ spec, rows, height }: WidgetProps) {
  const { data, bars, config } = useMemo(() => {
    const series = seriesOf(spec);
    const several = series.length > 1;
    const palette = several ? seriesColors(series.length) : ["var(--chart-1)"];
    const bars = series.map((one, i) => ({
      ...one,
      dataKey: several ? `series${i}` : "value",
      color: palette[i] ?? "var(--chart-1)",
    }));
    const data = points(spec, rows).map(({ label, row }) => ({
      label,
      row,
      ...Object.fromEntries(
        bars.map((bar) => {
          const value = Number(row[bar.key]);
          return [bar.dataKey, Number.isFinite(value) ? value : 0];
        }),
      ),
    }));
    const config: ChartConfig = Object.fromEntries(
      bars.map((bar) => [
        bar.dataKey,
        { label: several ? bar.label : spec.title, color: bar.color },
      ]),
    );
    return { data, bars, config };
  }, [spec, rows]);
  const [ref, width] = useWidth<HTMLDivElement>(480);
  const formats = new Map(bars.map((bar) => [bar.dataKey, bar.format]));
  const formatValue = (value: number, key: string) =>
    formatted(value, formats.get(key) ?? "number");

  // Measure again once the web font has loaded: until then the canvas measures a fallback.
  const [, setFontsReady] = useState(false);
  useEffect(() => {
    void document.fonts?.ready.then(() => setFontsReady(true));
  }, []);
  const longest = Math.max(0, ...data.map((point) => textWidth(point.label, FONT)));
  const labelWidth = Math.ceil(Math.min(longest + 16, Math.max(96, width * 0.42)));
  const valueWidth = Math.ceil(
    Math.max(
      0,
      ...data.flatMap((point) =>
        bars.map((bar) =>
          textWidth(formatValue(Number(point[bar.dataKey as keyof typeof point]), bar.dataKey)),
        ),
      ),
    ) + 12,
  );
  const several = bars.length > 1;
  const rowHeight = ROW + (bars.length - 1) * SERIES_ROW;
  const plotHeight = Math.max(height, data.length * rowHeight + 8 + (several ? 32 : 0));
  const inOrder = (item: { dataKey?: unknown }) =>
    bars.findIndex((bar) => bar.dataKey === item.dataKey);

  return (
    <div ref={ref} className="h-full min-h-0 w-full">
      <ChartContainer
        config={config}
        className="aspect-auto h-full w-full"
        style={{ minHeight: plotHeight }}
        initialDimension={{ width, height: plotHeight }}
      >
        <BarChart
          accessibilityLayer
          data={data}
          layout="vertical"
          margin={{ top: 0, right: valueWidth, bottom: 0, left: 0 }}
          barCategoryGap={several ? "16%" : "22%"}
          barGap={2}
        >
          <XAxis type="number" hide domain={[0, "dataMax"]} />
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
            content={
              several ? (
                <MultiTooltip formatValue={formatValue} order={inOrder} />
              ) : (
                <SingleTooltip formatValue={formatValue} />
              )
            }
          />
          {several && <ChartLegend itemSorter={inOrder} content={<ChartLegendContent />} />}
          {bars.map((bar) => (
            <Bar
              key={bar.dataKey}
              dataKey={bar.dataKey}
              name={bar.label}
              fill={`var(--color-${bar.dataKey})`}
              radius={[0, 4, 4, 0]}
              maxBarSize={several ? 16 : 22}
              isAnimationActive={false}
            >
              <LabelList
                dataKey={bar.dataKey}
                position="right"
                offset={8}
                fontSize={several ? 11 : FONT}
                className="fill-foreground tabular"
                formatter={(value: unknown) => formatValue(Number(value), bar.dataKey)}
              />
            </Bar>
          ))}
        </BarChart>
      </ChartContainer>
    </div>
  );
}
