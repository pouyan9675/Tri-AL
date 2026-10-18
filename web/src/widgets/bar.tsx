/**
 * Bars, horizontal: category names on the left (cut to fit, whole on hover), one bar per
 * row in the API's order, and the value at each bar's tip.
 */
import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, LabelList, XAxis, YAxis } from "recharts";
import { type ChartConfig, ChartContainer, ChartTooltip } from "@/components/ui/chart";
import { formatNumber } from "@/lib/format";
import { useWidth } from "@/lib/use-width";
import { fitText, points, textWidth, type WidgetProps } from "./common";
import { SingleTooltip } from "./tooltip";

const ROW = 30;
const FONT = 12;

export function BarWidget({ spec, rows, height }: WidgetProps) {
  const data = useMemo(() => points(spec, rows), [spec, rows]);
  const [ref, width] = useWidth<HTMLDivElement>(480);
  const config = { value: { label: spec.title, color: "var(--chart-1)" } } satisfies ChartConfig;

  // Measure again once the web font has loaded: until then the canvas measures a fallback.
  const [, setFontsReady] = useState(false);
  useEffect(() => {
    void document.fonts?.ready.then(() => setFontsReady(true));
  }, []);
  const longest = Math.max(0, ...data.map((point) => textWidth(point.label, FONT)));
  const labelWidth = Math.ceil(Math.min(longest + 16, Math.max(96, width * 0.42)));
  const valueWidth = Math.ceil(
    Math.max(0, ...data.map((point) => textWidth(formatNumber(point.value), FONT))) + 12,
  );
  const plotHeight = Math.max(height, data.length * ROW + 8);

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
          barCategoryGap="22%"
        >
          <XAxis type="number" dataKey="value" hide domain={[0, "dataMax"]} />
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
          <ChartTooltip cursor={{ className: "fill-muted/70" }} content={<SingleTooltip />} />
          <Bar
            dataKey="value"
            fill="var(--color-value)"
            radius={[0, 4, 4, 0]}
            maxBarSize={22}
            isAnimationActive={false}
          >
            <LabelList
              dataKey="value"
              position="right"
              offset={8}
              fontSize={FONT}
              className="fill-foreground tabular"
              formatter={(value: unknown) => formatNumber(Number(value))}
            />
          </Bar>
        </BarChart>
      </ChartContainer>
    </div>
  );
}
