/**
 * Upcoming results (#2): active trials by when their primary completion is due, over the next
 * two years, by quarter and phase, then the trials themselves, soonest first. The dates are
 * mostly sponsors' estimates, and active trials whose date has passed are counted apart.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { Bar, BarChart, XAxis, YAxis } from "recharts";
import type { TermKind, TermReadouts } from "@/api/client";
import { termReadoutsQuery } from "@/api/terms";
import { StatusBadge } from "@/components/status-badge";
import { type ChartConfig, ChartContainer, ChartTooltip } from "@/components/ui/chart";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { TrialFilter } from "@/lib/filters";
import { formatDate, formatNumber } from "@/lib/format";
import { useLabels } from "@/lib/labels";
import { axisNumber } from "@/widgets/common";
import { MultiTooltip } from "@/widgets/tooltip";
import { AnalysisCard, PHASE_COLORS, PHASE_GROUPS } from "./common";
import { phaseGroupOf } from "./math";

export function ReadoutsCard({
  kind,
  code,
  filter,
}: {
  kind: TermKind;
  code: string;
  filter: TrialFilter;
}) {
  const query = useQuery(termReadoutsQuery(kind, code, filter));
  return (
    <AnalysisCard
      title="Upcoming results"
      description="Active trials by when their primary outcome is due: when their main results come."
      query={query}
      testId="term-readouts"
      height={320}
    >
      {(data) => <Readouts data={data} />}
    </AnalysisCard>
  );
}

function Readouts({ data }: { data: TermReadouts }) {
  const label = useLabels();
  const [group, setGroup] = useState<string>("all");
  const config: ChartConfig = Object.fromEntries(
    PHASE_GROUPS.map((key, i) => [
      key,
      { label: label("phase_group", key), color: PHASE_COLORS[i] },
    ]),
  );
  const rows = data.quarters.map((quarter) => ({
    label: quarter.quarter.replace("-", " "),
    ...Object.fromEntries(PHASE_GROUPS.map((key, i) => [key, quarter.phases[i] ?? 0])),
  }));
  const shown = data.trials.filter(
    (readout) => group === "all" || PHASE_GROUPS[phaseGroupOf(readout.trial.phase)] === group,
  );

  if (data.total === 0) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        No active trial is due to complete by {formatDate(data.until)}
        {data.overdue > 0
          ? `; ${formatNumber(data.overdue)} active trials are past their date.`
          : "."}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground tabular">{formatNumber(data.total)}</span> due
        by {formatDate(data.until)}.{" "}
        {data.overdue > 0 &&
          `${formatNumber(data.overdue)} more are still active past their date, likely an estimate never updated.`}
      </p>
      <ChartContainer config={config} className="aspect-auto h-36 w-full">
        <BarChart
          accessibilityLayer
          data={rows}
          margin={{ top: 4, right: 4, bottom: 0, left: 0 }}
          barCategoryGap="16%"
        >
          <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={6} fontSize={11} />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={36}
            tickFormatter={axisNumber}
            allowDecimals={false}
          />
          <ChartTooltip
            cursor={{ className: "fill-muted/70" }}
            content={<MultiTooltip order={(item) => PHASE_GROUPS.indexOf(item.dataKey as never)} />}
          />
          {PHASE_GROUPS.map((key) => (
            <Bar
              key={key}
              dataKey={key}
              stackId="phases"
              fill={`var(--color-${key})`}
              stroke="var(--card)"
              strokeWidth={1}
              radius={2}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ChartContainer>
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        value={group}
        onValueChange={(value) => value && setGroup(value)}
        aria-label="Phase"
        className="flex-wrap"
      >
        <ToggleGroupItem value="all" className="px-2 text-xs">
          All
        </ToggleGroupItem>
        {PHASE_GROUPS.map((key, i) => (
          <ToggleGroupItem key={key} value={key} className="gap-1.5 px-2 text-xs">
            <span className="size-2 rounded-[2px]" style={{ background: PHASE_COLORS[i] }} />
            {label("phase_group", key)}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <ul className="max-h-80 divide-y overflow-y-auto rounded-lg border" aria-label="Trials due">
        {shown.length === 0 && (
          <li className="px-3 py-6 text-center text-xs text-muted-foreground">
            None in this phase among the soonest {formatNumber(data.trials.length)}.
          </li>
        )}
        {shown.map(({ trial, primary_completion, estimated }) => (
          <li key={trial.id} className="flex min-w-0 gap-3 px-3 py-2">
            <div className="w-20 shrink-0 text-xs">
              <div className="font-medium tabular">{formatDate(primary_completion)}</div>
              <div className="text-[0.7rem] text-muted-foreground">
                {estimated ? "Estimated" : "Actual"}
              </div>
            </div>
            <div className="flex min-w-0 flex-col gap-0.5">
              <Link
                to="/trials/$sourceId"
                params={{ sourceId: trial.source_id }}
                className="line-clamp-2 text-xs font-medium decoration-muted-foreground/40 underline-offset-2 hover:underline"
              >
                {trial.title}
              </Link>
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.7rem] text-muted-foreground">
                <span>{trial.phase ? label("phase", trial.phase) : "No phase"}</span>
                <StatusBadge status={trial.status} className="h-4.5 text-[0.65rem]" />
                {trial.enrollment !== null && (
                  <span className="tabular">{formatNumber(trial.enrollment)} enrolled</span>
                )}
                {trial.lead_sponsor && (
                  <span className="max-w-56 truncate" title={trial.lead_sponsor}>
                    {trial.lead_sponsor}
                  </span>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
