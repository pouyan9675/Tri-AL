/**
 * How long trials take (#7), as Kaplan-Meier curves: the share of its trials still running
 * by months since they started, against comparable trials, for a phase group picked with a
 * toggle; and the share of its finished trials with results posted by months since they
 * finished. Trials still running count until today, so the curves aren't biased toward the
 * quick ones.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import type { Curve, TermDurations, TermKind } from "@/api/client";
import { termDurationsQuery } from "@/api/terms";
import { type ChartConfig, ChartContainer, ChartTooltip } from "@/components/ui/chart";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { TrialFilter } from "@/lib/filters";
import { formatNumber } from "@/lib/format";
import { useLabels } from "@/lib/labels";
import { AnalysisCard, Legend, months, PHASE_GROUPS, percent } from "./common";
import { onGrid } from "./math";

const TERM = "var(--chart-1)";
const BASELINE = "var(--muted-foreground)";
const GROUPS = ["all", ...PHASE_GROUPS] as const;

export function DurationsCard({
  kind,
  code,
  filter,
}: {
  kind: TermKind;
  code: string;
  filter: TrialFilter;
}) {
  const query = useQuery(termDurationsQuery(kind, code, filter));
  return (
    <AnalysisCard
      title="How long trials take"
      description="Kaplan-Meier curves: trials still running counted until today, so slow trials aren't missed. Comparable trials are the filter's others."
      query={query}
      testId="term-durations"
      height={360}
    >
      {(data) => <Durations data={data} />}
    </AnalysisCard>
  );
}

function Durations({ data }: { data: TermDurations }) {
  const label = useLabels();
  const [group, setGroup] = useState<string>("all");
  const term = data.completion.find((curve) => curve.group === group);
  const baseline = data.completion_baseline.find((curve) => curve.group === group);
  const name = (key: string) => (key === "all" ? "All" : label("phase_group", key));

  return (
    <div className="flex flex-col gap-4">
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        value={group}
        onValueChange={(value) => value && setGroup(value)}
        aria-label="Phase"
        className="flex-wrap"
      >
        {GROUPS.map((key) => {
          const count = data.completion.find((curve) => curve.group === key)?.trials ?? 0;
          return (
            <ToggleGroupItem key={key} value={key} disabled={!count} className="px-2 text-xs">
              {name(key)}
            </ToggleGroupItem>
          );
        })}
      </ToggleGroup>
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
          <span className="font-medium">Still running, by months since start</span>
          <span className="text-muted-foreground">
            Median {months(term?.median)}{" "}
            <span className="text-muted-foreground/80">vs {months(baseline?.median)}</span> ·{" "}
            {formatNumber(term?.trials ?? 0)} trials
          </span>
        </div>
        <CurveChart
          term={term}
          baseline={baseline}
          before={1}
          until={120}
          valueLabel="still running"
          monthsLabel="since start"
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
          <span className="font-medium">With results posted, by months since completion</span>
          <span className="text-muted-foreground">
            {formatNumber(data.results.trials)} finished interventional trials
          </span>
        </div>
        <CurveChart
          term={data.results}
          baseline={data.results_baseline}
          before={0}
          until={60}
          valueLabel="with results"
          monthsLabel="since completion"
        />
        <dl className="grid grid-cols-3 gap-2 text-xs">
          {data.results_at.map((at) => (
            <div key={at.months} className="rounded-lg bg-muted/50 px-2.5 py-1.5">
              <dt className="text-muted-foreground">By {at.months} months</dt>
              <dd>
                <span className="font-semibold tabular">{percent(at.share)}</span>{" "}
                <span className="text-muted-foreground">vs {percent(at.baseline)}</span>
              </dd>
            </div>
          ))}
        </dl>
      </div>
      <Legend
        items={[
          { label: "Its trials", color: TERM },
          { label: "Comparable trials", color: BASELINE },
        ]}
      />
    </div>
  );
}

function CurveChart({
  term,
  baseline,
  before,
  until,
  valueLabel,
  monthsLabel,
}: {
  term: Curve | undefined;
  baseline: Curve | undefined;
  before: number;
  until: number;
  valueLabel: string;
  monthsLabel: string;
}) {
  const rows = onGrid({ term, baseline }, until, before);
  const config = {
    term: { label: "Its trials", color: TERM },
    baseline: { label: "Comparable trials", color: BASELINE },
  } satisfies ChartConfig;
  return (
    <ChartContainer config={config} className="aspect-auto h-40 w-full">
      <LineChart data={rows} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
        <XAxis
          dataKey="month"
          type="number"
          domain={[0, until]}
          ticks={Array.from({ length: until / 12 + 1 }, (_, i) => i * 12)}
          tickFormatter={(value: number) => (value === 0 ? "0" : `${value / 12}y`)}
          tickLine={false}
          axisLine={false}
          tickMargin={6}
        />
        <YAxis
          domain={[0, 1]}
          ticks={[0, 0.25, 0.5, 0.75, 1]}
          tickFormatter={(value: number) => `${Math.round(value * 100)}%`}
          tickLine={false}
          axisLine={false}
          width={40}
        />
        <ChartTooltip
          cursor={{ stroke: "var(--border)", strokeWidth: 1 }}
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            return (
              <div className="grid min-w-40 gap-1 rounded-lg border border-border/60 bg-popover px-2.5 py-1.5 text-xs shadow-lg">
                <span className="text-muted-foreground">
                  {Number(label)} months {monthsLabel}
                </span>
                {payload.map((item) => (
                  <div key={String(item.dataKey)} className="flex items-center gap-2">
                    <span
                      className="h-3 w-1 shrink-0 rounded-full"
                      style={{ background: item.color }}
                    />
                    <span>{item.dataKey === "term" ? "Its trials" : "Comparable"}</span>
                    <span className="ml-auto pl-3 font-semibold tabular">
                      {percent(Number(item.value))} {valueLabel}
                    </span>
                  </div>
                ))}
              </div>
            );
          }}
        />
        <Line
          dataKey="baseline"
          type="stepAfter"
          stroke="var(--color-baseline)"
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
        <Line
          dataKey="term"
          type="stepAfter"
          stroke="var(--color-term)"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ChartContainer>
  );
}
