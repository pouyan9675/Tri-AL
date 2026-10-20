/**
 * A trial's posted results (the results plugin's `/api/x/results/trials/{id}`): who started and
 * finished, who took part, each outcome measure with its analyses, adverse events by arm, and
 * the limitations and publication agreements. Every table has a column per group, as the
 * registry reports them; each module names its own groups.
 */
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Clock3 } from "lucide-react";
import { type ReactNode, useState } from "react";
import {
  type AdverseEvent,
  type AdverseEvents,
  type Analysis,
  type Baseline,
  type Flow,
  type MeasureClass,
  type MeasuredValue,
  type OutcomeResult,
  type ResultsGroup,
  type TrialResults,
  trialResultsQuery,
} from "@/api/results";
import { ErrorState } from "@/components/route-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import { formatNumber, formatPercent, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Panel } from "./sections";

export function ResultsTab({ sourceId }: { sourceId: string }) {
  const query = useQuery(trialResultsQuery(sourceId));
  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (!query.data) return <Skeleton className="h-80 w-full rounded-xl" />;
  return <Results results={query.data} />;
}

export function Results({ results }: { results: TrialResults }) {
  return (
    <div className="flex flex-col gap-4" data-testid="results">
      {results.flow && <FlowPanel flow={results.flow} />}
      {results.baseline && <BaselinePanel baseline={results.baseline} />}
      {results.outcomes.length > 0 && <OutcomesPanel outcomes={results.outcomes} />}
      {results.adverse_events && <AdverseEventsPanel events={results.adverse_events} />}
      {(results.limitations || results.agreement) && <MorePanel results={results} />}
    </div>
  );
}

// --- a table with a column per group --------------------------------------------------------

type Row = { key: string; label: ReactNode; cells: ReactNode[]; heading?: boolean };

function GroupTable({
  groups,
  rows,
  first = "",
}: {
  groups: ResultsGroup[];
  rows: Row[];
  first?: string;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-max border-collapse text-sm">
        <thead className="bg-muted/40 text-xs text-muted-foreground">
          <tr>
            <th className="sticky left-0 bg-muted/40 px-3 py-2 text-left font-medium">{first}</th>
            {groups.map((group) => (
              <th
                key={group.id}
                className="max-w-56 px-3 py-2 text-right font-medium"
                title={group.description ?? undefined}
              >
                <span className="line-clamp-2">{group.title}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className={cn("border-t", row.heading && "bg-muted/20")}>
              <th
                scope="row"
                className={cn(
                  "sticky left-0 max-w-80 bg-card px-3 py-1.5 text-left align-top font-normal",
                  row.heading ? "bg-muted/20 font-medium" : "text-foreground/90",
                )}
                colSpan={row.heading ? groups.length + 1 : 1}
              >
                {row.label}
              </th>
              {!row.heading &&
                row.cells.map((cell, i) => (
                  <td
                    key={groups[i]?.id ?? i}
                    className="px-3 py-1.5 text-right align-top whitespace-nowrap tabular"
                  >
                    {cell ?? <span className="text-muted-foreground">—</span>}
                  </td>
                ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Note({ children }: { children: ReactNode }) {
  return <p className="max-w-3xl text-xs leading-relaxed text-muted-foreground">{children}</p>;
}

/** `n (x%)`, with the share of `of` when it's known. */
function countOf(n: number | null | undefined, of: number | null | undefined): ReactNode {
  if (n === null || n === undefined) return null;
  return (
    <>
      {formatNumber(n)}
      {of ? <span className="ml-1 text-muted-foreground">({formatPercent(n / of)})</span> : null}
    </>
  );
}

// --- participant flow -----------------------------------------------------------------------

const MILESTONES: Record<string, string> = {
  STARTED: "Started",
  COMPLETED: "Completed",
  "NOT COMPLETED": "Did not complete",
};

function FlowPanel({ flow }: { flow: Flow }) {
  const several = flow.periods.length > 1;
  return (
    <Panel title="Participant flow">
      <div className="flex flex-col gap-4">
        {flow.periods.map((period) => {
          const started = period.milestones.find((m) => m.label === "STARTED")?.counts ?? {};
          const rows: Row[] = [
            ...period.milestones.map((milestone, i) => ({
              key: `m${i}`,
              label: MILESTONES[milestone.label] ?? milestone.label,
              cells: flow.groups.map((group) =>
                milestone.label === "STARTED"
                  ? countOf(milestone.counts[group.id], null)
                  : countOf(milestone.counts[group.id], started[group.id]),
              ),
            })),
          ];
          if (period.dropouts.length > 0) {
            rows.push({ key: "why", label: "Why they left", cells: [], heading: true });
            period.dropouts.forEach((dropout, i) => {
              rows.push({
                key: `d${i}`,
                label: <span className="pl-3">{dropout.reason}</span>,
                cells: flow.groups.map((group) => countOf(dropout.counts[group.id], null)),
              });
            });
          }
          return (
            <div key={period.title} className="flex flex-col gap-2">
              {several && <h3 className="text-sm font-medium">{period.title}</h3>}
              <GroupTable groups={flow.groups} rows={rows} first="Participants" />
            </div>
          );
        })}
        {flow.recruitment && <Note>{flow.recruitment}</Note>}
        {flow.pre_assignment && <Note>{flow.pre_assignment}</Note>}
      </div>
    </Panel>
  );
}

// --- baseline -------------------------------------------------------------------------------

const PARAMS: Record<string, string> = {
  MEAN: "Mean",
  MEDIAN: "Median",
  NUMBER: "Number",
  COUNT_OF_PARTICIPANTS: "Participants",
  COUNT_OF_UNITS: "Units",
  LEAST_SQUARES_MEAN: "Least squares mean",
  GEOMETRIC_MEAN: "Geometric mean",
  GEOMETRIC_LEAST_SQUARES_MEAN: "Geometric least squares mean",
  LOG_MEAN: "Log mean",
};

const DISPERSIONS: Record<string, string> = {
  STANDARD_DEVIATION: "SD",
  STANDARD_ERROR: "SE",
  INTER_QUARTILE_RANGE: "IQR",
  FULL_RANGE: "range",
  CONFIDENCE_95: "95% CI",
  CONFIDENCE_90: "90% CI",
  GEOMETRIC_COEFFICIENT: "geometric CV",
};

/** "Mean (SD), years": how a measure's numbers read. */
function describe(param: string | null, dispersion: string | null, unit: string | null): string {
  const name = param ? (PARAMS[param] ?? humanize(param)) : "";
  const spread = dispersion
    ? (DISPERSIONS[dispersion] ??
      DISPERSIONS[dispersion.toUpperCase().replace(/\W+/g, "_")] ??
      dispersion)
    : "";
  return [name + (spread ? ` (${spread})` : ""), unit].filter(Boolean).join(", ");
}

function measured(
  value: MeasuredValue | undefined,
  param: string | null,
  of: number | undefined,
): ReactNode {
  if (!value || value.value === null) return null;
  if (param === "COUNT_OF_PARTICIPANTS") {
    const n = Number(value.value);
    if (Number.isFinite(n)) return countOf(n, of);
  }
  const extra =
    value.spread !== null
      ? `(${value.spread})`
      : value.lower !== null || value.upper !== null
        ? `(${value.lower ?? "?"} to ${value.upper ?? "?"})`
        : null;
  return (
    <span title={value.comment ?? undefined}>
      {value.value}
      {extra && <span className="ml-1 text-muted-foreground">{extra}</span>}
    </span>
  );
}

function measureRows(
  key: string,
  classes: MeasureClass[],
  groups: ResultsGroup[],
  param: string | null,
  participants: Record<string, number>,
): Row[] {
  const rows: Row[] = [];
  classes.forEach((cls, c) => {
    const titled = cls.title && cls.categories.some((category) => category.title);
    if (titled) rows.push({ key: `${key}-c${c}`, label: cls.title, cells: [], heading: false });
    cls.categories.forEach((category, i) => {
      rows.push({
        key: `${key}-${c}-${i}`,
        label: (
          <span className={cn(titled && "pl-3")}>{category.title || cls.title || "Value"}</span>
        ),
        cells: groups.map((group) =>
          measured(category.values[group.id], param, participants[group.id]),
        ),
      });
    });
    if (titled) {
      const header = rows.find((row) => row.key === `${key}-c${c}`);
      if (header) header.cells = groups.map(() => "");
    }
  });
  return rows;
}

function BaselinePanel({ baseline }: { baseline: Baseline }) {
  const rows: Row[] = [
    {
      key: "n",
      label: "Participants analysed",
      cells: baseline.groups.map((group) => countOf(baseline.participants[group.id], null)),
    },
  ];
  baseline.measures.forEach((measure, m) => {
    const how = describe(measure.param, measure.dispersion, measure.unit);
    rows.push({
      key: `h${m}`,
      label: (
        <>
          {measure.title}
          {how && <span className="ml-2 text-xs font-normal text-muted-foreground">{how}</span>}
        </>
      ),
      cells: [],
      heading: true,
    });
    rows.push(
      ...measureRows(
        `m${m}`,
        measure.classes,
        baseline.groups,
        measure.param,
        baseline.participants,
      ),
    );
  });
  return (
    <Panel title="Baseline characteristics">
      <div className="flex flex-col gap-2">
        <GroupTable groups={baseline.groups} rows={rows} />
        {baseline.population && <Note>{baseline.population}</Note>}
      </div>
    </Panel>
  );
}

// --- outcome measures -----------------------------------------------------------------------

const OUTCOME_TYPES: Record<string, string> = {
  PRIMARY: "Primary",
  SECONDARY: "Secondary",
  OTHER_PRE_SPECIFIED: "Other pre-specified",
  POST_HOC: "Post hoc",
};

function OutcomesPanel({ outcomes }: { outcomes: OutcomeResult[] }) {
  return (
    <Panel title={`Outcome measures · ${outcomes.length}`}>
      <div className="flex flex-col divide-y">
        {outcomes.map((outcome, i) => (
          <OutcomeItem
            // biome-ignore lint/suspicious/noArrayIndexKey: outcomes have no id; titles repeat
            key={i}
            outcome={outcome}
            open={outcome.type === "PRIMARY" && i < 3}
          />
        ))}
      </div>
    </Panel>
  );
}

function OutcomeItem({ outcome, open }: { outcome: OutcomeResult; open: boolean }) {
  const [expanded, setExpanded] = useState(open);
  const how = describe(outcome.param, outcome.dispersion, outcome.unit);
  const rows: Row[] = [
    {
      key: "n",
      label: "Participants analysed",
      cells: outcome.groups.map((group) => countOf(outcome.participants[group.id], null)),
    },
    ...measureRows("v", outcome.classes, outcome.groups, outcome.param, outcome.participants),
  ];
  return (
    <Collapsible open={expanded} onOpenChange={setExpanded} className="py-3 first:pt-0 last:pb-0">
      <CollapsibleTrigger className="group flex w-full items-start gap-2 text-left">
        <ChevronRight className="mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-90" />
        <span className="min-w-0 flex-1 space-y-1">
          <span className="flex flex-wrap items-center gap-2">
            <Badge variant={outcome.type === "PRIMARY" ? "default" : "outline"} className="h-5">
              {OUTCOME_TYPES[outcome.type] ?? humanize(outcome.type)}
            </Badge>
            {outcome.analyses.length > 0 && (
              <span className="text-xs text-muted-foreground">
                {outcome.analyses.length} analys{outcome.analyses.length === 1 ? "is" : "es"}
              </span>
            )}
          </span>
          <span className="block text-sm font-medium">{outcome.title}</span>
          {outcome.time_frame && (
            <span className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <Clock3 className="mt-px size-3.5 shrink-0" />
              {outcome.time_frame}
            </span>
          )}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent className="flex flex-col gap-3 pt-3 pl-6">
        {outcome.description && <Note>{outcome.description}</Note>}
        {!outcome.posted ? (
          <Note>The trial says these data will be posted later.</Note>
        ) : (
          <>
            {how && <p className="text-xs font-medium text-muted-foreground">{how}</p>}
            <GroupTable groups={outcome.groups} rows={rows} />
          </>
        )}
        {outcome.population && <Note>{outcome.population}</Note>}
        {outcome.analyses.map((analysis, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: analyses have no id
          <AnalysisLine key={i} analysis={analysis} groups={outcome.groups} />
        ))}
      </CollapsibleContent>
    </Collapsible>
  );
}

const HYPOTHESES: Record<string, string> = {
  NON_INFERIORITY: "Non-inferiority",
  EQUIVALENCE: "Equivalence",
  NON_INFERIORITY_OR_EQUIVALENCE: "Non-inferiority or equivalence",
  SUPERIORITY: "Superiority",
};

function AnalysisLine({ analysis, groups }: { analysis: Analysis; groups: ResultsGroup[] }) {
  const names = analysis.groups.map((id) => groups.find((group) => group.id === id)?.title ?? id);
  const significant = significance(analysis.p_value);
  const facts: [string, ReactNode][] = [];
  if (analysis.estimate_type || analysis.estimate) {
    facts.push([
      analysis.estimate_type ?? "Estimate",
      <span key="estimate">
        <span className="font-semibold">{analysis.estimate ?? "—"}</span>
        {(analysis.ci_lower || analysis.ci_upper) && (
          <span className="ml-1 text-muted-foreground">
            ({analysis.ci_percent ?? "95"}% CI {analysis.ci_lower ?? "?"} to{" "}
            {analysis.ci_upper ?? "?"})
          </span>
        )}
      </span>,
    ]);
  }
  if (analysis.p_value) {
    facts.push([
      "p-value",
      <span key="p" className={cn("font-semibold", significant && "text-good")}>
        {analysis.p_value}
      </span>,
    ]);
  }
  if (analysis.method) facts.push(["Method", analysis.method]);
  if (analysis.hypothesis && HYPOTHESES[analysis.hypothesis]) {
    facts.push(["Hypothesis", HYPOTHESES[analysis.hypothesis]]);
  }
  return (
    <div className="rounded-lg border bg-muted/20 px-3 py-2 text-sm" data-testid="analysis">
      <p className="mb-1.5 text-xs text-muted-foreground">
        {names.length > 1 ? `${names.join(" vs ")}` : names[0]}
      </p>
      <dl className="flex flex-wrap gap-x-5 gap-y-1">
        {facts.map(([term, value]) => (
          <div key={term} className="flex gap-1.5">
            <dt className="text-muted-foreground">{term}</dt>
            <dd className="tabular">{value}</dd>
          </div>
        ))}
      </dl>
      {analysis.description && (
        <p className="mt-1.5 text-xs text-muted-foreground">{analysis.description}</p>
      )}
    </div>
  );
}

/** Whether a p-value as the registry writes it ("<0.001", "0.032", "=0.05") is under 0.05. */
export function significance(text: string | null): boolean {
  if (!text) return false;
  const match = text.replace(/\s/g, "").match(/^([<≤=]?)(\d*\.?\d+(?:e-?\d+)?)/i);
  if (!match) return false;
  const value = Number(match[2]);
  return match[1] === "<" || match[1] === "≤" ? value <= 0.05 : value < 0.05;
}

// --- adverse events -------------------------------------------------------------------------

const SHOWN = 15;

function AdverseEventsPanel({ events }: { events: AdverseEvents }) {
  const groups = events.groups;
  const summary: Row[] = [
    {
      key: "serious",
      label: "Serious adverse events",
      cells: groups.map((g) => countOf(g.serious_affected, g.serious_at_risk)),
    },
    {
      key: "other",
      label: "Other adverse events",
      cells: groups.map((g) => countOf(g.other_affected, g.other_at_risk)),
    },
    {
      key: "deaths",
      label: "Deaths (all causes)",
      cells: groups.map((g) => countOf(g.deaths, g.deaths_at_risk)),
    },
    {
      key: "risk",
      label: "At risk",
      cells: groups.map((g) => countOf(g.serious_at_risk, null)),
    },
  ];
  const tableGroups = groups.map((group) => ({
    id: group.id,
    title: group.placebo ? `${group.title} (placebo)` : group.title,
    description: group.description,
  }));
  const serious = events.events.filter((event) => event.serious);
  const other = events.events.filter((event) => !event.serious);
  return (
    <Panel title="Adverse events">
      <div className="flex flex-col gap-4">
        <GroupTable groups={tableGroups} rows={summary} first="Participants affected" />
        {serious.length > 0 && (
          <EventTable title="Serious adverse events" groups={tableGroups} events={serious} />
        )}
        {other.length > 0 && (
          <EventTable title="Other adverse events" groups={tableGroups} events={other} />
        )}
        <div className="flex flex-col gap-1">
          {events.time_frame && <Note>Collected: {events.time_frame}</Note>}
          {events.threshold !== null && events.threshold > 0 && (
            <Note>
              Other (not serious) adverse events are listed when more than {events.threshold}% of an
              arm had them.
            </Note>
          )}
          {events.description && <Note>{events.description}</Note>}
        </div>
      </div>
    </Panel>
  );
}

function EventTable({
  title,
  groups,
  events,
}: {
  title: string;
  groups: ResultsGroup[];
  events: AdverseEvent[];
}) {
  const [all, setAll] = useState(false);
  const affected = (event: AdverseEvent) =>
    Object.values(event.counts).reduce((sum, count) => sum + (count.affected ?? 0), 0);
  const sorted = [...events].sort((a, b) => affected(b) - affected(a));
  const shown = all ? sorted : sorted.slice(0, SHOWN);
  const rows: Row[] = shown.map((event, i) => ({
    key: `${i}`,
    label: (
      <span className="flex flex-col">
        <span>{event.term}</span>
        {event.organ && <span className="text-xs text-muted-foreground">{event.organ}</span>}
      </span>
    ),
    cells: groups.map((group) => {
      const count = event.counts[group.id];
      return count ? countOf(count.affected, count.at_risk) : null;
    }),
  }));
  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-sm font-medium">
        {title} <span className="font-normal text-muted-foreground">· {events.length}</span>
      </h3>
      <GroupTable groups={groups} rows={rows} first="Event" />
      {sorted.length > SHOWN && (
        <Button variant="ghost" size="sm" className="self-start" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${sorted.length}`}
        </Button>
      )}
    </div>
  );
}

// --- limitations and agreements -------------------------------------------------------------

const RESTRICTIONS: Record<string, string> = {
  LTE60: "The sponsor can review results for up to 60 days before investigators publish them.",
  GT60: "The sponsor can review results for more than 60 days before investigators publish them.",
};

function MorePanel({ results }: { results: TrialResults }) {
  const agreement = results.agreement;
  return (
    <Panel title="Limitations and agreements">
      <div className="flex flex-col gap-3 text-sm">
        {results.limitations && (
          <div className="space-y-1">
            <h3 className="font-medium">Limitations and caveats</h3>
            <p className="max-w-3xl leading-relaxed text-foreground/80">{results.limitations}</p>
          </div>
        )}
        {agreement && (
          <div className="space-y-1">
            <h3 className="font-medium">Publication</h3>
            <ul className="max-w-3xl list-disc space-y-1 pl-5 text-foreground/80">
              {agreement.pi_sponsor_employee !== null && (
                <li>
                  {agreement.pi_sponsor_employee
                    ? "The principal investigators are employed by the sponsor."
                    : "The principal investigators aren't employed by the sponsor."}
                </li>
              )}
              {agreement.restrictive === false && (
                <li>No agreement restricts what the investigators may publish.</li>
              )}
              {agreement.restrictive && (
                <li>
                  {(agreement.restriction && RESTRICTIONS[agreement.restriction]) ??
                    "An agreement restricts what the investigators may publish."}
                  {agreement.details && (
                    <span className="mt-1 block text-xs text-muted-foreground">
                      {agreement.details}
                    </span>
                  )}
                </li>
              )}
            </ul>
          </div>
        )}
      </div>
    </Panel>
  );
}
