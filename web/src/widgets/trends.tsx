/**
 * Trends: ranked lists of what is rising, one column per group (conditions, interventions)
 * for each of a few time windows, picked with a toggle. Each entry shows its trials per
 * month as small bars (the window in the accent color), its trials in the window, its growth
 * (adjusted for small counts) and how sure that is (a three-step meter in light, brand and
 * deep blue, and a word); low confidence is faded. The tooltip has the raw numbers, and a click lists its trials.
 * `tri_al.stats.charts` describes the rows.
 */
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import type { ChartRow } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { parseFilter } from "@/lib/filters";
import { formatDate, formatNumber, formatShortDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { WidgetProps } from "./common";

type Window = {
  window: string;
  label: string;
  since: string;
  until: string;
  baselineSince: string;
  trials: number;
  baselineTrials: number;
};

type Confidence = "high" | "medium" | "low";

type Item = {
  window: string;
  group: string;
  key: string;
  label: string;
  value: number;
  baseline: number;
  expected: number;
  growth: number;
  rawGrowth: number | null;
  p: number;
  q: number;
  confidence: Confidence;
  tested: number;
  isNew: boolean;
  sponsors: number;
  series: number[];
  recent: number;
  filter: Record<string, unknown>;
};

const number = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : 0;
const text = (value: unknown) => (value === null || value === undefined ? "" : String(value));

function windowOf(row: ChartRow): Window {
  return {
    window: text(row.window),
    label: text(row.label),
    since: text(row.since),
    until: text(row.until),
    baselineSince: text(row.baseline_since),
    trials: number(row.trials),
    baselineTrials: number(row.baseline_trials),
  };
}

function itemOf(row: ChartRow): Item {
  const series = Array.isArray(row.series) ? row.series.map(number) : [];
  return {
    window: text(row.window),
    group: text(row.group),
    key: text(row.key) || text(row.label),
    label: text(row.label) || "—",
    value: number(row.value),
    baseline: number(row.baseline),
    expected: number(row.expected),
    growth: number(row.growth),
    rawGrowth: typeof row.raw_growth === "number" ? row.raw_growth : null,
    p: number(row.p),
    q: number(row.q),
    confidence: row.confidence === "high" || row.confidence === "medium" ? row.confidence : "low",
    tested: number(row.tested),
    isNew: row.new === true,
    sponsors: number(row.sponsors),
    series,
    recent: Math.min(number(row.recent), series.length),
    filter:
      row.filter && typeof row.filter === "object" ? (row.filter as Record<string, unknown>) : {},
  };
}

/** Whole months from one `YYYY-MM-DD` date to another. */
function monthsBetween(since: string, until: string): number {
  const [a, b] = [since, until].map((day) => new Date(`${day}T00:00:00Z`));
  if (!a || !b || Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return 0;
  return (b.getUTCFullYear() - a.getUTCFullYear()) * 12 + b.getUTCMonth() - a.getUTCMonth();
}

export function formatGrowth(growth: number): string {
  return `${growth >= 10 ? Math.round(growth) : growth.toFixed(1)}×`;
}

/** A p- or q-value as people read it: "0.0016", "< 0.0001". */
export function formatChance(value: number): string {
  if (value < 0.0001) return "< 0.0001";
  return value.toPrecision(2).replace(/\.?0+$/, "");
}

/**
 * Each level's bars are a step of the blue ramp around the brand blue. On a dark theme the
 * ramp runs the other way, so higher confidence still stands out more from the background.
 */
const CONFIDENCE: Record<Confidence, { label: string; steps: number; color: string }> = {
  high: { label: "High", steps: 3, color: "bg-(--seq-700)" },
  medium: { label: "Medium", steps: 2, color: "bg-chart-1" },
  low: { label: "Low", steps: 1, color: "bg-(--seq-300)" },
};

/** Name, monthly bars (from a medium width), trials, growth and confidence. */
const COLUMNS =
  "grid grid-cols-[minmax(0,1fr)_2.5rem_3rem_4rem] items-center gap-x-3 @md:grid-cols-[minmax(0,1fr)_4.5rem_2.5rem_3rem_4rem]";

export function TrendsWidget({ rows, filter = {} }: WidgetProps) {
  const windows = rows.filter((row) => row.type === "window").map(windowOf);
  const items = rows.filter((row) => row.type === "item").map(itemOf);
  const [chosen, setChosen] = useState<string | undefined>(undefined);
  const current = windows.find((w) => w.window === chosen) ?? windows.at(-1);
  if (!current) {
    return <Empty>No trials to look at yet.</Empty>;
  }
  const groups = [...new Set(items.map((item) => item.group))];
  const baselineMonths = monthsBetween(current.baselineSince, current.since);
  const shown = items.filter((item) => item.window === current.window);

  return (
    <div className="flex min-h-0 flex-col gap-3" data-testid="trends">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground tabular">
            {formatNumber(current.trials)}
          </span>{" "}
          trials first posted {formatShortDate(current.since)} – {formatDate(current.until)},
          against <span className="tabular">{formatNumber(current.baselineTrials)}</span> in the{" "}
          {baselineMonths} months before.
        </p>
        {windows.length > 1 && (
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={current.window}
            onValueChange={(value) => value && setChosen(value)}
            aria-label="Time window"
          >
            {windows.map((w) => (
              <ToggleGroupItem key={w.window} value={w.window} className="px-2.5 text-xs">
                {w.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        )}
      </div>
      {current.baselineTrials === 0 ? (
        <Empty>No trials under this filter in the months before, so nothing to compare.</Empty>
      ) : groups.length === 0 ? (
        <Empty>Nothing is taking a growing share of new trials.</Empty>
      ) : (
        <div className="grid gap-x-8 gap-y-5 @3xl:grid-cols-2">
          {groups.map((group) => (
            <TrendList
              key={group}
              group={group}
              items={shown.filter((item) => item.group === group)}
              window={current}
              baselineMonths={baselineMonths}
              filter={filter}
            />
          ))}
        </div>
      )}
      <p className="mt-auto text-[0.7rem] text-muted-foreground">
        Growth: the share of new trials against the {baselineMonths} months before, adjusted so a
        few trials can't make it jump. Confidence: how unlikely the rise is by chance, corrected for
        every term tested; low is faded. Bars: trials per month, this window in color.
      </p>
    </div>
  );
}

function TrendList({
  group,
  items,
  window,
  baselineMonths,
  filter,
}: {
  group: string;
  items: Item[];
  window: Window;
  baselineMonths: number;
  filter: Record<string, unknown>;
}) {
  return (
    <section aria-label={group} className="@container min-w-0">
      <div
        className={cn(
          COLUMNS,
          "items-end border-b pb-1.5 text-[0.7rem] font-medium text-muted-foreground",
        )}
      >
        <span>{group}</span>
        <span className="hidden @md:block">Per month</span>
        <span className="text-right">Trials</span>
        <span className="text-right">Growth</span>
        <span className="text-right">Confidence</span>
      </div>
      {items.length === 0 ? (
        <p className="py-6 text-center text-xs text-muted-foreground">
          Nothing rising in this window.
        </p>
      ) : (
        <ol>
          {items.map((item, index) => (
            <li key={item.key}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Link
                    to="/trials"
                    search={parseFilter({ ...filter, ...item.filter })}
                    className={cn(
                      COLUMNS,
                      "rounded-md border-b border-border/50 py-1.5 outline-none transition-colors hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring/50",
                      low(item) && "text-muted-foreground",
                    )}
                    data-testid="trend"
                    data-confidence={item.confidence}
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="w-4 shrink-0 text-right text-[0.7rem] text-muted-foreground tabular">
                        {index + 1}
                      </span>
                      <span className={cn("truncate text-sm", !low(item) && "font-medium")}>
                        {item.label}
                      </span>
                      {item.isNew && (
                        <Badge variant="secondary" className="h-4 px-1.5 text-[0.65rem]">
                          New
                        </Badge>
                      )}
                    </span>
                    <span className="hidden @md:block">
                      <Spark series={item.series} recent={item.recent} faded={low(item)} />
                    </span>
                    <span className="text-right text-sm tabular">{formatNumber(item.value)}</span>
                    <span
                      className={cn(
                        "text-right text-sm tabular",
                        !low(item) && "font-semibold text-foreground",
                      )}
                    >
                      {formatGrowth(item.growth)}
                    </span>
                    <Meter confidence={item.confidence} />
                  </Link>
                </TooltipTrigger>
                <TooltipContent side="top" align="start" className="block max-w-sm">
                  <Details item={item} window={window} baselineMonths={baselineMonths} />
                </TooltipContent>
              </Tooltip>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function Details({
  item,
  window,
  baselineMonths,
}: {
  item: Item;
  window: Window;
  baselineMonths: number;
}) {
  const plural = (n: number, word: string) => `${formatNumber(n)} ${word}${n === 1 ? "" : "s"}`;
  return (
    <div className="grid gap-1">
      <p className="font-semibold">{item.label}</p>
      <p>
        {plural(item.value, "trial")} since {formatShortDate(window.since)}, from{" "}
        {plural(item.sponsors, "lead sponsor")}; {formatNumber(item.baseline)} in the{" "}
        {baselineMonths} months before
        {item.expected > 0 ? ` (at the usual share, ${item.expected} now)` : ""}.
      </p>
      <p>
        {item.isNew ? "Its first trial was posted in this window. " : ""}
        {formatGrowth(item.growth)} its usual share of new trials
        {item.rawGrowth === null
          ? ", with none before"
          : item.rawGrowth.toFixed(1) !== item.growth.toFixed(1)
            ? ` (${formatGrowth(item.rawGrowth)} before adjusting for the small count)`
            : ""}
        .
      </p>
      <p>
        {CONFIDENCE[item.confidence].label} confidence. The chance of a rise this large if nothing
        had changed: p = {formatChance(item.p)}; corrected for the {formatNumber(item.tested)}{" "}
        {item.group.toLowerCase()} tested: q = {formatChance(item.q)}.
      </p>
    </div>
  );
}

const low = (item: Item) => item.confidence === "low";

/** Confidence as one to three rising bars and its word. */
export function Meter({ confidence }: { confidence: Confidence }) {
  const { label, steps, color } = CONFIDENCE[confidence];
  return (
    <span className="flex items-center justify-end gap-1.5 text-[0.7rem]">
      <span className="hidden @md:inline">{label}</span>
      <span className="flex items-end gap-0.5" role="img" aria-label={`${label} confidence`}>
        {["h-1.5", "h-2.5", "h-3.5"].map((height, step) => (
          <span
            key={height}
            className={cn(
              "w-1 rounded-[1px]",
              height,
              step < steps ? color : "bg-muted-foreground/25",
            )}
          />
        ))}
      </span>
    </span>
  );
}

const SPARK_WIDTH = 72;
const SPARK_HEIGHT = 20;

/** Trials per month as small bars, the last `recent` (the window) in the accent color. */
function Spark({ series, recent, faded }: { series: number[]; recent: number; faded: boolean }) {
  const max = Math.max(1, ...series);
  const gap = 1;
  const width = series.length ? (SPARK_WIDTH - gap * (series.length - 1)) / series.length : 0;
  return (
    <svg
      width={SPARK_WIDTH}
      height={SPARK_HEIGHT}
      viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`}
      aria-hidden="true"
      className={cn("overflow-visible", faded && "opacity-60")}
    >
      {series.map((count, index) => {
        const height = count > 0 ? Math.max(2, (count / max) * SPARK_HEIGHT) : 1;
        const inWindow = index >= series.length - recent;
        return (
          <rect
            // biome-ignore lint/suspicious/noArrayIndexKey: one bar per month, in order
            key={index}
            x={index * (width + gap)}
            y={SPARK_HEIGHT - height}
            width={width}
            height={height}
            rx={Math.min(1, width / 2)}
            className={inWindow ? "fill-chart-1" : "fill-muted-foreground/35"}
          />
        );
      })}
    </svg>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-32 items-center justify-center rounded-lg border border-dashed bg-muted/30 p-6 text-center text-sm text-muted-foreground">
      {children}
    </div>
  );
}
