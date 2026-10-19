/**
 * Trials over time (#1): trials started per year, stacked by phase group; or the term's
 * share of every trial started that year; or the lead sponsors new to it. One measure at a
 * time, picked with a toggle, so there's never a second axis. Above it, momentum: the term's
 * share of newly posted trials in the last 3, 6 and 12 months against the year before.
 */
import { useQuery } from "@tanstack/react-query";
import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import type { Momentum, TermKind, TermTimeline } from "@/api/client";
import { termTimelineQuery } from "@/api/terms";
import { type ChartConfig, ChartContainer, ChartTooltip } from "@/components/ui/chart";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { TrialFilter } from "@/lib/filters";
import { formatDate, formatNumber } from "@/lib/format";
import { useLabels } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { axisNumber } from "@/widgets/common";
import { MultiTooltip, SingleTooltip } from "@/widgets/tooltip";
import { formatChance, Meter } from "@/widgets/trends";
import { AnalysisCard, Legend, PHASE_COLORS, PHASE_GROUPS, times } from "./common";

type Measure = "trials" | "share" | "sponsors";

export function TimelineCard({
  kind,
  code,
  filter,
}: {
  kind: TermKind;
  code: string;
  filter: TrialFilter;
}) {
  const query = useQuery(termTimelineQuery(kind, code, filter));
  const [measure, setMeasure] = useState<Measure>("trials");
  return (
    <AnalysisCard
      title="Trials over time"
      description="Trials started each year, and whether new registrations are gaining or losing ground."
      query={query}
      testId="term-timeline"
      height={320}
      action={() => (
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={measure}
          onValueChange={(value) => value && setMeasure(value as Measure)}
          aria-label="Measure"
        >
          <ToggleGroupItem value="trials" className="px-2 text-xs">
            Trials
          </ToggleGroupItem>
          <ToggleGroupItem value="share" className="px-2 text-xs">
            Share
          </ToggleGroupItem>
          <ToggleGroupItem value="sponsors" className="px-2 text-xs">
            New sponsors
          </ToggleGroupItem>
        </ToggleGroup>
      )}
    >
      {(data) => <Timeline data={data} measure={measure} />}
    </AnalysisCard>
  );
}

function Timeline({ data, measure }: { data: TermTimeline; measure: Measure }) {
  const label = useLabels();
  const last = data.years.at(-1);
  const rows = data.years.map((year) => ({
    label: data.partial && year === last ? `${year.year}*` : String(year.year),
    share: year.share * 100,
    sponsors: year.new_sponsors,
    ...Object.fromEntries(PHASE_GROUPS.map((group, i) => [group, year.phases[i] ?? 0])),
  }));
  const stacked = measure === "trials";
  const config: ChartConfig = stacked
    ? Object.fromEntries(
        PHASE_GROUPS.map((group, i) => [
          group,
          { label: label("phase_group", group), color: PHASE_COLORS[i] },
        ]),
      )
    : {
        value: {
          label: measure === "share" ? "Share of trials started" : "New lead sponsors",
          color: "var(--chart-1)",
        },
      };
  const single = rows.map((row) => ({
    label: row.label,
    value: measure === "share" ? row.share : row.sponsors,
  }));

  return (
    <div className="flex flex-col gap-3">
      <MomentumRow momentum={data.momentum} />
      <ChartContainer config={config} className="aspect-auto h-60 w-full">
        <BarChart
          accessibilityLayer
          data={(stacked ? rows : single) as Record<string, string | number>[]}
          margin={{ top: 8, right: 4, bottom: 0, left: 0 }}
          barCategoryGap="18%"
        >
          <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
          <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={8} minTickGap={16} />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={44}
            tickFormatter={(value: number) =>
              measure === "share" ? `${value.toFixed(value < 1 ? 1 : 0)}%` : axisNumber(value)
            }
            allowDecimals={measure === "share"}
          />
          <ChartTooltip
            cursor={{ className: "fill-muted/70" }}
            content={
              stacked ? (
                <MultiTooltip order={(item) => PHASE_GROUPS.indexOf(item.dataKey as never)} />
              ) : measure === "share" ? (
                <ShareTooltip />
              ) : (
                <SingleTooltip />
              )
            }
          />
          {stacked ? (
            PHASE_GROUPS.map((group) => (
              <Bar
                key={group}
                dataKey={group}
                stackId="phases"
                fill={`var(--color-${group})`}
                stroke="var(--card)"
                strokeWidth={1}
                radius={2}
                isAnimationActive={false}
              />
            ))
          ) : (
            <Bar
              dataKey="value"
              fill="var(--color-value)"
              radius={[4, 4, 0, 0]}
              maxBarSize={28}
              isAnimationActive={false}
            />
          )}
        </BarChart>
      </ChartContainer>
      {stacked && (
        <Legend
          items={PHASE_GROUPS.map((group, i) => ({
            label: label("phase_group", group),
            color: PHASE_COLORS[i] ?? "",
          }))}
        />
      )}
      <p className="text-[0.7rem] text-muted-foreground">
        {measure === "share"
          ? "Its trials as a share of every trial started within the filter that year, so a growing registry doesn't look like a growing field."
          : measure === "sponsors"
            ? "Lead sponsors whose first trial of it started that year."
            : "By start date; phase groups put a combined phase with the later one."}
        {data.partial && last ? ` * ${last.year} so far.` : ""}
      </p>
    </div>
  );
}

function ShareTooltip(props: Parameters<typeof SingleTooltip>[0]) {
  const item = props.payload?.[0];
  if (!props.active || !item) return null;
  return (
    <div className="grid min-w-28 gap-0.5 rounded-lg border border-border/60 bg-popover px-2.5 py-1.5 text-xs shadow-lg">
      <span className="text-sm font-semibold tabular text-popover-foreground">
        {Number(item.value).toFixed(2)}%
      </span>
      <span className="text-muted-foreground">of trials started in {String(props.label)}</span>
    </div>
  );
}

const DIRECTION = {
  rising: { icon: TrendingUp, word: "Rising" },
  falling: { icon: TrendingDown, word: "Falling" },
  steady: { icon: Minus, word: "Steady" },
} as const;

/** Its momentum in each window: growth of its share of new trials, and how sure that is. */
function MomentumRow({ momentum }: { momentum: Momentum[] }) {
  return (
    <ul className="grid grid-cols-1 gap-2 @md:grid-cols-3" aria-label="Momentum">
      {momentum.map((window) => {
        const { icon: Icon, word } = DIRECTION[window.direction];
        return (
          <li key={window.months}>
            <Tooltip>
              <TooltipTrigger asChild>
                <div
                  className={cn(
                    "flex cursor-default flex-col gap-0.5 rounded-lg border px-3 py-2",
                    window.confidence === "low" && "opacity-70",
                  )}
                  // biome-ignore lint/a11y/noNoninteractiveTabindex: focus shows the details
                  tabIndex={0}
                >
                  <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                    Last {window.months} months
                    <Meter confidence={window.confidence} />
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Icon className="size-4 text-muted-foreground" />
                    <span className="text-base font-semibold tabular">{times(window.growth)}</span>
                    <span className="truncate text-xs text-muted-foreground">{word}</span>
                  </div>
                </div>
              </TooltipTrigger>
              <TooltipContent className="max-w-72 text-xs">
                {formatNumber(window.trials)} trials first posted {formatDate(window.since)} –{" "}
                {formatDate(window.until)}, against {formatNumber(window.baseline)} in the 12 months
                before: {times(window.growth)} its usual share of new trials (smoothed for small
                counts; {formatNumber(window.expected)} expected at the usual share). Two-sided
                exact test: p = {formatChance(window.p)}.
              </TooltipContent>
            </Tooltip>
          </li>
        );
      })}
    </ul>
  );
}
