/**
 * A donut: up to seven slices in the categorical palette's fixed order, the rest folded into
 * "Other", with a legend that carries each slice's name, count and share.
 */
import { useMemo } from "react";
import { Cell, Pie, PieChart } from "recharts";
import { type ChartConfig, ChartContainer, ChartTooltip } from "@/components/ui/chart";
import { formatNumber } from "@/lib/format";
import { points, type WidgetProps } from "./common";
import { SingleTooltip } from "./tooltip";

const SLICES = 7;

export function PieWidget({ spec, rows, height }: WidgetProps) {
  const data = useMemo(() => {
    const all = points(spec, rows).filter((point) => point.value > 0);
    if (all.length <= SLICES + 1) return all;
    const rest = all.slice(SLICES).reduce((sum, point) => sum + point.value, 0);
    return [...all.slice(0, SLICES), { label: "Other", value: rest, row: {} }];
  }, [spec, rows]);
  const total = data.reduce((sum, point) => sum + point.value, 0);
  const config = { value: { label: spec.title, color: "var(--chart-1)" } } satisfies ChartConfig;

  return (
    <div className="flex h-full flex-col items-center gap-4 sm:flex-row">
      <ChartContainer
        config={config}
        className="aspect-square shrink-0"
        style={{ height: Math.min(height, 240), width: Math.min(height, 240) }}
      >
        <PieChart>
          <ChartTooltip content={<SingleTooltip />} />
          <Pie
            data={data}
            dataKey="value"
            nameKey="label"
            innerRadius="58%"
            outerRadius="100%"
            stroke="var(--card)"
            strokeWidth={2}
            isAnimationActive={false}
          >
            {data.map((point, index) => (
              <Cell key={point.label} fill={`var(--chart-${(index % 8) + 1})`} />
            ))}
          </Pie>
        </PieChart>
      </ChartContainer>
      <ul className="grid w-full min-w-0 gap-1.5 text-sm">
        {data.map((point, index) => (
          <li key={point.label} className="flex items-center gap-2">
            <span
              className="size-2.5 shrink-0 rounded-[3px]"
              style={{ background: `var(--chart-${(index % 8) + 1})` }}
            />
            <span className="min-w-0 flex-1 truncate text-muted-foreground">{point.label}</span>
            <span className="tabular font-medium">{formatNumber(point.value)}</span>
            <span className="w-12 text-right text-xs tabular text-muted-foreground">
              {total ? `${((point.value / total) * 100).toFixed(1)}%` : ""}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
