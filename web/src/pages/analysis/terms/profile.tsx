/**
 * Design and population (#8): each measure for its trials beside comparable trials (the
 * filter's others, weighted to its mix of phases), and how far apart they are as a
 * standardized difference, drawn on a track from -1 to 1 (beyond is clipped, with the
 * number): blue where its trials have more, orange less. Then enrollment by size, both ways.
 */
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import type { Benchmark, TermKind, TermProfile } from "@/api/client";
import { termProfileQuery } from "@/api/terms";
import { type ChartConfig, ChartContainer, ChartTooltip } from "@/components/ui/chart";
import type { TrialFilter } from "@/lib/filters";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AnalysisCard, Legend, percent } from "./common";
import { trackPosition } from "./math";

const MORE = "var(--chart-1)";
const LESS = "var(--chart-2)";
const BASELINE = "var(--phase-other)";

export function ProfileCard({
  kind,
  code,
  filter,
}: {
  kind: TermKind;
  code: string;
  filter: TrialFilter;
}) {
  const query = useQuery(termProfileQuery(kind, code, filter));
  return (
    <AnalysisCard
      title="Design and population, against comparable trials"
      description="Comparable trials are the filter's others, weighted to the same mix of phases. Differences are standardized: 0.2 is small, 0.5 medium, 0.8 large."
      query={query}
      testId="term-profile"
      height={420}
      wide
    >
      {(data) => (
        <div className="grid grid-cols-1 gap-6 @4xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <Benchmarks rows={data.rows} />
          <Enrollment data={data} />
        </div>
      )}
    </AnalysisCard>
  );
}

function shown(row: Benchmark, value: number | null): string {
  if (value === null) return "—";
  switch (row.unit) {
    case "share":
      return percent(value);
    case "years":
      return `${Math.round(value)} yr`;
    default:
      return formatNumber(Math.round(value));
  }
}

const SIZE = (d: number) =>
  Math.abs(d) >= 0.8
    ? "large"
    : Math.abs(d) >= 0.5
      ? "medium"
      : Math.abs(d) >= 0.2
        ? "small"
        : "negligible";

function Benchmarks({ rows }: { rows: Benchmark[] }) {
  const sections = [...new Set(rows.map((row) => row.section))];
  return (
    <div className="flex flex-col gap-3" data-testid="benchmarks">
      <div className="grid grid-cols-[minmax(0,1fr)_3.5rem_3.5rem_minmax(6rem,10rem)_2.5rem] items-end gap-x-3 text-[0.7rem] text-muted-foreground">
        <span />
        <span className="text-right">Its trials</span>
        <span className="text-right">Others</span>
        <span className="flex justify-between">
          <span>Less</span>
          <span>More</span>
        </span>
        <span className="text-right">d</span>
      </div>
      {sections.map((section) => (
        <div key={section} className="flex flex-col">
          <div className="pb-1 text-xs font-medium">{section}</div>
          {rows
            .filter((row) => row.section === section)
            .map((row) => (
              <BenchmarkRow key={row.key} row={row} />
            ))}
        </div>
      ))}
    </div>
  );
}

function BenchmarkRow({ row }: { row: Benchmark }) {
  const d = row.difference;
  const position = d === null ? 0.5 : trackPosition(d);
  const beyond = d !== null && Math.abs(d) > 1;
  return (
    <div
      className={cn(
        "grid grid-cols-[minmax(0,1fr)_3.5rem_3.5rem_minmax(6rem,10rem)_2.5rem] items-center gap-x-3 border-t py-1.5 text-xs",
        (d === null || Math.abs(d) < 0.2) && "text-muted-foreground",
      )}
      title={
        d === null
          ? undefined
          : `${row.label}: a ${SIZE(d)} difference (d = ${d.toFixed(2)}), measured on ${formatNumber(row.trials)} of its trials.`
      }
    >
      <span className="truncate">{row.label}</span>
      <span className="text-right font-medium text-foreground tabular">
        {shown(row, row.value)}
      </span>
      <span className="text-right tabular">{shown(row, row.baseline)}</span>
      <span className="relative h-3" aria-hidden="true">
        <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
        {[0.2, 0.5, 0.8].flatMap((tick) => [
          <span
            key={`-${tick}`}
            className="absolute inset-y-1 w-px bg-border/60"
            style={{ left: `${trackPosition(-tick) * 100}%` }}
          />,
          <span
            key={`+${tick}`}
            className="absolute inset-y-1 w-px bg-border/60"
            style={{ left: `${trackPosition(tick) * 100}%` }}
          />,
        ])}
        {d !== null && (
          <span
            className={cn(
              "absolute top-1/2 h-1.5 -translate-y-1/2",
              d >= 0 ? "rounded-r-full" : "rounded-l-full",
            )}
            style={{
              left: `${Math.min(position, 0.5) * 100}%`,
              width: `${Math.abs(position - 0.5) * 100}%`,
              background: d >= 0 ? MORE : LESS,
              opacity: beyond ? 1 : 0.85,
            }}
          />
        )}
      </span>
      <span className="text-right tabular">
        {d === null ? "—" : `${d > 0 ? "+" : ""}${d.toFixed(1)}`}
      </span>
    </div>
  );
}

function Enrollment({ data }: { data: TermProfile }) {
  const rows = data.enrollment.map((bin) => ({
    label:
      bin.high === null
        ? `${formatNumber(bin.low)}+`
        : `${formatNumber(bin.low)}–${formatNumber(bin.high)}`,
    term: bin.share * 100,
    baseline: bin.baseline * 100,
  }));
  const config = {
    term: { label: "Its trials", color: MORE },
    baseline: { label: "Comparable trials", color: BASELINE },
  } satisfies ChartConfig;
  return (
    <div className="flex flex-col gap-2" data-testid="enrollment-bins">
      <div className="text-xs font-medium">Enrollment</div>
      <ChartContainer config={config} className="aspect-auto h-56 w-full">
        <BarChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barGap={2}>
          <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={false}
            tickMargin={6}
            fontSize={10}
            interval={0}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={36}
            tickFormatter={(value: number) => `${Math.round(value)}%`}
          />
          <ChartTooltip
            cursor={{ className: "fill-muted/70" }}
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <div className="grid min-w-36 gap-1 rounded-lg border border-border/60 bg-popover px-2.5 py-1.5 text-xs shadow-lg">
                  <span className="text-muted-foreground">{String(label)} participants</span>
                  {payload.map((item) => (
                    <div key={String(item.dataKey)} className="flex items-center gap-2">
                      <span
                        className="h-3 w-1 shrink-0 rounded-full"
                        style={{ background: item.color }}
                      />
                      {item.dataKey === "term" ? "Its trials" : "Comparable"}
                      <span className="ml-auto pl-3 font-semibold tabular">
                        {Number(item.value).toFixed(1)}%
                      </span>
                    </div>
                  ))}
                </div>
              ) : null
            }
          />
          <Bar
            dataKey="term"
            fill="var(--color-term)"
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
          />
          <Bar
            dataKey="baseline"
            fill="var(--color-baseline)"
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
          />
        </BarChart>
      </ChartContainer>
      <Legend
        items={[
          { label: "Its trials", color: MORE },
          { label: "Comparable trials", color: BASELINE },
        ]}
      />
      <p className="text-[0.7rem] text-muted-foreground">
        Share of trials with an enrollment in each range: {formatNumber(data.trials)} of its trials
        against {formatNumber(data.baseline_trials)} others.
      </p>
    </div>
  );
}
