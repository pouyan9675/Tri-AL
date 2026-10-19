/**
 * The pipeline (#5): first the term's own trials by phase, split by status; then the other
 * kind's terms in its trials (a condition's interventions, an intervention's conditions) by
 * phase, as a heatmap: furthest phase first, or most trials first.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { FunnelRow, PipelineRow, TermKind, TermPipeline } from "@/api/client";
import { termPipelineQuery } from "@/api/terms";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { TrialFilter } from "@/lib/filters";
import { formatDate, formatNumber } from "@/lib/format";
import { useLabels } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { AnalysisCard, KINDS, Legend, TermLink } from "./common";

export function PipelineCard({
  kind,
  code,
  filter,
}: {
  kind: TermKind;
  code: string;
  filter: TrialFilter;
}) {
  const query = useQuery(termPipelineQuery(kind, code, filter));
  const [order, setOrder] = useState<"phase" | "trials">("phase");
  const rows = KINDS[kind === "condition" ? "intervention" : "condition"].many;
  return (
    <AnalysisCard
      title="Pipeline by phase"
      description={
        kind === "condition"
          ? `Its trials by phase and status, then the ${rows} they test, by phase.`
          : `Its trials by phase and status, then the ${rows} they're for, by phase: where it's being developed.`
      }
      query={query}
      testId="term-pipeline"
      height={360}
      action={() => (
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={order}
          onValueChange={(value) => value && setOrder(value as "phase" | "trials")}
          aria-label="Order"
        >
          <ToggleGroupItem value="phase" className="px-2 text-xs">
            Furthest
          </ToggleGroupItem>
          <ToggleGroupItem value="trials" className="px-2 text-xs">
            Most trials
          </ToggleGroupItem>
        </ToggleGroup>
      )}
    >
      {(data) => (
        <div className="flex flex-col gap-4">
          <Funnel rows={data.funnel} />
          <Heatmap data={data} order={order} />
        </div>
      )}
    </AnalysisCard>
  );
}

const STATUSES = [
  { key: "active", label: "Active", color: "var(--chart-1)" },
  { key: "completed", label: "Completed", color: "var(--chart-3)" },
  { key: "stopped", label: "Stopped early", color: "var(--chart-2)" },
  { key: "unknown", label: "Unknown", color: "var(--phase-other)" },
  { key: "other", label: "Other", color: "var(--muted)" },
] as const;

function Funnel({ rows }: { rows: FunnelRow[] }) {
  const label = useLabels();
  const largest = Math.max(1, ...rows.map((row) => row.trials));
  return (
    <div className="flex flex-col gap-1.5" data-testid="pipeline-funnel">
      {rows.map((row) => (
        <div
          key={row.phase ?? "none"}
          className="grid grid-cols-[6.5rem_minmax(0,1fr)_3rem] items-center gap-2 text-xs"
        >
          <span className="truncate text-muted-foreground">
            {row.phase ? label("phase", row.phase) : "No phase"}
          </span>
          <Tooltip>
            <TooltipTrigger asChild>
              <div
                className="flex h-3.5 cursor-default gap-[2px]"
                style={{ width: `${(row.trials / largest) * 100}%` }}
              >
                {STATUSES.map(({ key, color }) =>
                  row[key] > 0 ? (
                    <span
                      key={key}
                      className="h-full rounded-[3px] first:rounded-l-sm"
                      style={{ background: color, flexGrow: row[key], flexBasis: 0 }}
                    />
                  ) : null,
                )}
              </div>
            </TooltipTrigger>
            <TooltipContent className="text-xs">
              {STATUSES.filter(({ key }) => row[key] > 0)
                .map(({ key, label: name }) => `${name} ${formatNumber(row[key])}`)
                .join(" · ")}
            </TooltipContent>
          </Tooltip>
          <span className="text-right tabular">{formatNumber(row.trials)}</span>
        </div>
      ))}
      <Legend items={STATUSES.map(({ label: name, color }) => ({ label: name, color }))} />
    </div>
  );
}

const SHORT: Record<string, string> = {
  EARLY_PHASE1: "Early 1",
  PHASE1: "1",
  PHASE1_PHASE2: "1/2",
  PHASE2: "2",
  PHASE2_PHASE3: "2/3",
  PHASE3: "3",
  PHASE4: "4",
};

/** Cells darken with their count, in the blue ramp's steps (sequential: one hue). */
const STEPS = [
  "var(--seq-100)",
  "var(--seq-200)",
  "var(--seq-300)",
  "var(--seq-400)",
  "var(--seq-500)",
];

function Heatmap({ data, order }: { data: TermPipeline; order: "phase" | "trials" }) {
  const label = useLabels();
  const rank = (row: PipelineRow) => (row.highest ? data.phases.indexOf(row.highest) : -1);
  const rows =
    order === "phase"
      ? data.rows.toSorted((a, b) => rank(b) - rank(a) || b.trials - a.trials)
      : data.rows;
  const largest = Math.max(1, ...data.rows.flatMap((row) => row.phases));
  const step = (count: number) =>
    count === 0
      ? -1
      : Math.min(STEPS.length - 1, Math.floor(Math.sqrt(count / largest) * STEPS.length));

  if (rows.length === 0) {
    return (
      <p className="py-6 text-center text-xs text-muted-foreground">
        Its trials have no MeSH {KINDS[data.kind].many}.
      </p>
    );
  }
  return (
    <div className="max-h-96 overflow-auto rounded-lg border" data-testid="pipeline-heatmap">
      <table className="w-full min-w-max border-collapse text-xs">
        <caption className="sr-only">{KINDS[data.kind].Many} by phase</caption>
        <thead className="sticky top-0 z-10 bg-card">
          <tr>
            <th scope="col" className="px-2 py-1.5 text-left font-medium">
              {KINDS[data.kind].Many}
            </th>
            {data.phases.map((phase) => (
              <th
                key={phase}
                scope="col"
                title={label("phase", phase)}
                className="w-9 px-0.5 py-1.5 text-center font-normal text-muted-foreground"
              >
                {SHORT[phase] ?? phase}
              </th>
            ))}
            <th
              scope="col"
              title="Trials still running or about to"
              className="px-2 py-1.5 text-right font-normal text-muted-foreground"
            >
              Active
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.code} className="border-t">
              <th scope="row" className="max-w-44 truncate px-2 py-1 text-left font-normal">
                <TermLink kind={row.kind} code={row.code}>
                  <span title={row.term}>{row.term}</span>
                </TermLink>
              </th>
              {row.phases.map((count, i) => {
                const level = step(count);
                return (
                  <td
                    // biome-ignore lint/suspicious/noArrayIndexKey: one cell per phase, in order
                    key={i}
                    title={`${row.term}: ${formatNumber(count)} ${label("phase", data.phases[i])} trials`}
                    className="p-0.5"
                  >
                    <span
                      className={cn(
                        "flex h-6 items-center justify-center rounded-[4px] tabular",
                        level >= 3 ? "text-white" : "text-foreground",
                      )}
                      style={{ background: level < 0 ? "transparent" : STEPS[level] }}
                    >
                      {count || ""}
                    </span>
                  </td>
                );
              })}
              <td
                className="px-2 py-1 text-right tabular text-muted-foreground"
                title={row.last_start ? `Latest start ${formatDate(row.last_start)}` : undefined}
              >
                {formatNumber(row.active)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
