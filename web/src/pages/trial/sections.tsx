import { Link } from "@tanstack/react-router";
import { Clock3 } from "lucide-react";
import { type ReactNode, useState } from "react";
import type { TrialDetail } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatAge, humanize } from "@/lib/format";
import { useLabels } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { TextBlocks } from "./text";

export function Panel({
  title,
  children,
  className,
  action,
}: {
  title: string;
  children: ReactNode;
  className?: string;
  action?: ReactNode;
}) {
  return (
    <Card className={cn("gap-3 shadow-xs", className)}>
      <CardHeader className="flex items-center justify-between gap-2">
        <CardTitle className="text-[0.95rem]">{title}</CardTitle>
        {action}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function Chips({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap gap-1.5">{children}</div>;
}

const chip =
  "inline-flex max-w-full items-center rounded-md border bg-muted/40 px-2 py-0.5 text-xs transition-colors hover:border-foreground/20 hover:bg-muted";

function Facts({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid gap-x-4 gap-y-2.5 text-sm">
      {items.map(([term, value]) => (
        <div key={term} className="grid grid-cols-[9rem_1fr] gap-3">
          <dt className="text-muted-foreground">{term}</dt>
          <dd className="min-w-0">{value ?? <span className="text-muted-foreground">—</span>}</dd>
        </div>
      ))}
    </dl>
  );
}

const LONG = 1400;
const SCOPES: Record<string, string> = {
  US: "US only",
  NON_US: "Outside the US",
  BOTH: "US and elsewhere",
};

export function OverviewTab({ trial }: { trial: TrialDetail }) {
  const label = useLabels();
  const [full, setFull] = useState(false);
  const description = trial.description ?? "";
  const meshTerms = trial.mesh_terms.filter((term) => !term.ancestor);
  const collaborators = trial.sponsors.filter((sponsor) => sponsor.role !== "lead");
  const lead = trial.sponsors.find((sponsor) => sponsor.role === "lead");

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="flex min-w-0 flex-col gap-4">
        <Panel title="Summary">
          <TextBlocks text={trial.brief_summary} />
        </Panel>
        {description.trim() && (
          <Panel
            title="Description"
            action={
              description.length > LONG && (
                <Button variant="ghost" size="sm" className="-my-1" onClick={() => setFull(!full)}>
                  {full ? "Show less" : "Show all"}
                </Button>
              )
            }
          >
            <div
              className={cn(
                "relative",
                !full && description.length > LONG && "max-h-80 overflow-hidden",
              )}
            >
              <TextBlocks text={description} />
              {!full && description.length > LONG && (
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-card" />
              )}
            </div>
          </Panel>
        )}
        <Panel title="Interventions">
          {trial.interventions.length === 0 ? (
            <p className="text-sm text-muted-foreground">None listed.</p>
          ) : (
            <ul className="divide-y">
              {trial.interventions.map((intervention) => (
                <li
                  key={intervention.name}
                  className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2 first:pt-0 last:pb-0"
                >
                  <Link
                    to="/trials"
                    search={{ interventions: [intervention.name] }}
                    className="font-medium hover:underline"
                  >
                    {intervention.name}
                  </Link>
                  {intervention.type && (
                    <span className="text-xs text-muted-foreground">
                      {label("intervention_type", intervention.type)}
                    </span>
                  )}
                  {intervention.other_names.length > 0 && (
                    <span className="basis-full text-xs text-muted-foreground">
                      Also: {intervention.other_names.join(", ")}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
      <div className="flex min-w-0 flex-col gap-4">
        <Panel title="Conditions">
          <Chips>
            {trial.conditions.map((condition) => (
              <Link
                key={condition}
                to="/trials"
                search={{ conditions: [condition] }}
                className={chip}
              >
                <span className="truncate">{condition}</span>
              </Link>
            ))}
            {trial.conditions.length === 0 && (
              <span className="text-sm text-muted-foreground">None listed.</span>
            )}
          </Chips>
        </Panel>
        {meshTerms.length > 0 && (
          <Panel title="MeSH terms">
            <Chips>
              {meshTerms.map((term) => (
                <Link
                  key={`${term.kind}-${term.code}`}
                  to="/trials"
                  search={{ mesh: [term.code] }}
                  className={chip}
                  title={`${term.code} (${term.kind})`}
                >
                  <span className="truncate">{term.term}</span>
                </Link>
              ))}
            </Chips>
          </Panel>
        )}
        <Panel title="Design">
          <Facts
            items={[
              ["Study type", trial.study_type ? label("study_type", trial.study_type) : null],
              ["Primary purpose", trial.primary_purpose ? humanize(trial.primary_purpose) : null],
              ["Arms", trial.arms_count],
              ["Lead sponsor", lead ? `${lead.name}` : null],
              [
                "Sponsor type",
                lead?.sponsor_class ? label("sponsor_class", lead.sponsor_class) : null,
              ],
              [
                "Sites",
                trial.location_scope
                  ? (SCOPES[trial.location_scope] ?? humanize(trial.location_scope))
                  : null,
              ],
            ]}
          />
        </Panel>
        {collaborators.length > 0 && (
          <Panel title="Collaborators">
            <ul className="space-y-1.5 text-sm">
              {collaborators.map((sponsor) => (
                <li key={sponsor.name}>
                  <Link
                    to="/trials"
                    search={{ sponsors: [sponsor.name] }}
                    className="hover:underline"
                  >
                    {sponsor.name}
                  </Link>
                </li>
              ))}
            </ul>
          </Panel>
        )}
      </div>
    </div>
  );
}

export function EligibilityTab({ trial }: { trial: TrialDetail }) {
  const min = formatAge(trial.min_age_days);
  const max = formatAge(trial.max_age_days);
  const ages =
    min && max ? `${min} to ${max}` : min ? `${min} and older` : max ? `Up to ${max}` : "Any age";
  const sex = trial.sex
    ? ({ ALL: "All", FEMALE: "Female", MALE: "Male" }[trial.sex] ?? humanize(trial.sex))
    : "—";
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <Panel title="Criteria" className="min-w-0">
        <TextBlocks text={trial.eligibility_criteria} className="max-w-3xl" />
      </Panel>
      <Panel title="Who can take part" className="h-fit">
        <Facts
          items={[
            ["Ages", ages],
            ["Sex", sex],
            [
              "Healthy volunteers",
              trial.healthy_volunteers === null
                ? null
                : trial.healthy_volunteers
                  ? "Accepted"
                  : "Not accepted",
            ],
          ]}
        />
      </Panel>
    </div>
  );
}

const OUTCOME_ORDER = ["primary", "secondary", "other"];

export function OutcomesTab({ trial }: { trial: TrialDetail }) {
  if (trial.outcomes.length === 0) {
    return (
      <Panel title="Outcomes">
        <p className="text-sm text-muted-foreground">No outcome measures listed.</p>
      </Panel>
    );
  }
  const kinds = [...new Set(trial.outcomes.map((outcome) => outcome.kind))].sort(
    (a, b) => (OUTCOME_ORDER.indexOf(a) + 1 || 9) - (OUTCOME_ORDER.indexOf(b) + 1 || 9),
  );
  return (
    <div className="flex flex-col gap-4">
      {kinds.map((kind) => {
        const outcomes = trial.outcomes.filter((outcome) => outcome.kind === kind);
        return (
          <Panel key={kind} title={`${humanize(kind)} outcomes · ${outcomes.length}`}>
            <ol className="divide-y">
              {outcomes
                .map((outcome, index) => ({ outcome, number: index + 1 }))
                .map(({ outcome, number }) => (
                  <li key={number} className="flex gap-3 py-3 first:pt-0 last:pb-0">
                    <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-[0.65rem] font-semibold tabular text-muted-foreground">
                      {number}
                    </span>
                    <div className="min-w-0 space-y-1">
                      <p className="text-sm font-medium">{outcome.measure}</p>
                      {outcome.time_frame && (
                        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
                          <Clock3 className="mt-px size-3.5 shrink-0" />
                          {outcome.time_frame}
                        </p>
                      )}
                      {outcome.description && (
                        <p className="max-w-3xl text-sm leading-relaxed text-foreground/80">
                          {outcome.description}
                        </p>
                      )}
                    </div>
                  </li>
                ))}
            </ol>
          </Panel>
        );
      })}
    </div>
  );
}
