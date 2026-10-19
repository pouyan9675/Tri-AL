/**
 * Why trials stop (#6): the share of its finished trials that stopped early, phase by phase,
 * against the filter's other trials in the same phase (a dot each, joined), the ratio of
 * stopped trials to what the baseline's rates would give, and the reasons sponsors state,
 * sorted by their words. A reason's examples open below it.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { useState } from "react";
import type { StopRate, TermAttrition, TermKind } from "@/api/client";
import { termAttritionQuery } from "@/api/terms";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { TrialFilter } from "@/lib/filters";
import { formatNumber } from "@/lib/format";
import { useLabels } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { formatChance, Meter } from "@/widgets/trends";
import { AnalysisCard, Legend, percent, times } from "./common";

export function AttritionCard({
  kind,
  code,
  filter,
}: {
  kind: TermKind;
  code: string;
  filter: TrialFilter;
}) {
  const query = useQuery(termAttritionQuery(kind, code, filter));
  return (
    <AnalysisCard
      title="Why trials stop"
      description="Finished trials that stopped early (terminated, withdrawn or suspended), against comparable trials phase by phase, and the reasons given."
      query={query}
      testId="term-attrition"
      height={360}
    >
      {(data) => <Attrition data={data} />}
    </AnalysisCard>
  );
}

const TERM = "var(--chart-1)";
const BASELINE = "var(--muted-foreground)";

function Attrition({ data }: { data: TermAttrition }) {
  const label = useLabels();
  const rows = data.phases.filter((row) => row.closed > 0);
  const largest = Math.max(0.05, ...rows.flatMap((row) => [row.rate ?? 0, row.baseline_rate ?? 0]));
  const ratio = data.ratio;
  return (
    <div className="flex flex-col gap-4">
      {ratio !== null && (
        <p className="text-xs text-muted-foreground">
          <span className="text-base font-semibold text-foreground tabular">{times(ratio)}</span> as
          many stopped as comparable trials would:{" "}
          <span className="tabular">{formatNumber(data.observed)}</span> against{" "}
          <span className="tabular">{formatNumber(Math.round(data.expected))}</span> expected at
          their rates, phase by phase.{" "}
          <span className="inline-flex translate-y-0.5">
            <Meter confidence={data.confidence} />
          </span>
        </p>
      )}
      <div className="flex flex-col gap-1.5" data-testid="stop-rates">
        {rows.map((row) => (
          <RateRow
            key={row.group}
            row={row}
            name={label("phase_group", row.group)}
            largest={largest}
          />
        ))}
        <Legend
          items={[
            { label: "Its trials", color: TERM },
            { label: "Comparable trials", color: BASELINE },
          ]}
        />
      </div>
      <Reasons data={data} />
    </div>
  );
}

function RateRow({ row, name, largest }: { row: StopRate; name: string; largest: number }) {
  const at = (rate: number | null) => `${((rate ?? 0) / largest) * 100}%`;
  const low = Math.min(row.rate ?? 0, row.baseline_rate ?? 0);
  const high = Math.max(row.rate ?? 0, row.baseline_rate ?? 0);
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div
          className={cn(
            "grid cursor-default grid-cols-[5rem_minmax(0,1fr)_auto] items-center gap-3 text-xs",
            row.confidence === "low" && "opacity-70",
          )}
        >
          <span className="text-muted-foreground">{name}</span>
          <div className="relative h-4">
            <div className="absolute inset-x-0 top-1/2 h-px bg-border" />
            <div
              className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-muted-foreground/40"
              style={{ left: at(low), width: `${((high - low) / largest) * 100}%` }}
            />
            {row.baseline_rate !== null && (
              <span
                className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-card"
                style={{ left: at(row.baseline_rate), background: BASELINE }}
              />
            )}
            <span
              className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-card"
              style={{ left: at(row.rate), background: TERM }}
            />
          </div>
          <span className="flex items-center justify-end gap-2 whitespace-nowrap tabular">
            <span className="font-medium">{percent(row.rate)}</span>
            <span className="text-muted-foreground">vs {percent(row.baseline_rate)}</span>
            <Meter confidence={row.confidence} />
          </span>
        </div>
      </TooltipTrigger>
      <TooltipContent className="max-w-72 text-xs">
        {formatNumber(row.stopped)} of {formatNumber(row.closed)} finished trials stopped early,
        against {percent(row.baseline_rate, 1)} of {formatNumber(row.baseline_closed)} comparable
        ones ({times(row.ratio)}). p = {formatChance(row.p)}; corrected for the phases tested, q ={" "}
        {formatChance(row.q)}.
      </TooltipContent>
    </Tooltip>
  );
}

function Reasons({ data }: { data: TermAttrition }) {
  const [open, setOpen] = useState<string | null>(null);
  if (data.stated === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        None of its {formatNumber(data.stopped)} stopped trials states a reason.
      </p>
    );
  }
  const largest = Math.max(1, ...data.reasons.map((reason) => reason.trials));
  return (
    <div className="flex flex-col gap-1.5" data-testid="stop-reasons">
      <div className="text-xs font-medium">Reasons given</div>
      <ul className="flex flex-col">
        {data.reasons.map((reason) => (
          <li key={reason.key}>
            <button
              type="button"
              aria-expanded={open === reason.key}
              onClick={() => setOpen(open === reason.key ? null : reason.key)}
              className="grid w-full grid-cols-[0.75rem_12rem_minmax(0,1fr)_4.5rem] items-center gap-2 rounded-md py-1 text-left text-xs hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
            >
              <ChevronRight
                className={cn(
                  "size-3 text-muted-foreground transition-transform",
                  open === reason.key && "rotate-90",
                )}
              />
              <span className="truncate">{reason.label}</span>
              <span className="h-2.5">
                <span
                  className="block h-full rounded-r-[4px] bg-chart-1"
                  style={{ width: `${(reason.trials / largest) * 100}%` }}
                />
              </span>
              <span className="text-right tabular">
                {formatNumber(reason.trials)}{" "}
                <span className="text-muted-foreground">
                  {percent(reason.trials / data.stated)}
                </span>
              </span>
            </button>
            {open === reason.key && (
              <ul className="mb-2 ml-5 flex flex-col gap-1.5 border-l pl-3">
                {reason.examples.map((example) => (
                  <li key={example.source_id} className="text-xs">
                    <Link
                      to="/trials/$sourceId"
                      params={{ sourceId: example.source_id }}
                      className="font-mono text-[0.7rem] text-muted-foreground hover:underline"
                    >
                      {example.source_id}
                    </Link>{" "}
                    “{example.reason}”
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
      <p className="text-[0.7rem] text-muted-foreground">
        {formatNumber(data.stated)} of {formatNumber(data.read)} stopped trials state a reason
        {data.read < data.stopped ? ` (the latest ${formatNumber(data.read)} read)` : ""}. Each is
        sorted by its words into the first kind it mentions.
      </p>
    </div>
  );
}
