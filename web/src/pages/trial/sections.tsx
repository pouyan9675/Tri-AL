import { Link } from "@tanstack/react-router";
import { Clock3 } from "lucide-react";
import { type ReactNode, useState } from "react";
import type { TrialDetail } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatAge, humanize } from "@/lib/format";
import { useLabels } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { AnnotateButton, AnnotationLegend, useAnnotation } from "./annotate";
import { ArmCards, InterventionList, StudyFocus } from "./study";
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
  const summary = useAnnotation(trial, "brief_summary");
  const described = useAnnotation(trial, "description");
  const description = trial.description ?? "";
  const collapsed = !full && !described.shown && description.length > LONG;
  const conditionTerms = trial.mesh_terms.filter((t) => !t.ancestor && t.kind === "condition");
  const interventionTerms = trial.mesh_terms.filter(
    (t) => !t.ancestor && t.kind === "intervention",
  );
  const collaborators = trial.sponsors.filter((sponsor) => sponsor.role !== "lead");
  const lead = trial.sponsors.find((sponsor) => sponsor.role === "lead");
  const observational = trial.study_type === "OBSERVATIONAL";
  const roles = trial.masked_roles.map((role) => label("masked_role", role)).join(", ");

  return (
    <div className="flex flex-col gap-4">
      <StudyFocus trial={trial} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="flex min-w-0 flex-col gap-4">
          <Panel title="Summary" action={<AnnotateButton view={summary} />}>
            <AnnotationLegend view={summary} />
            <TextBlocks text={trial.brief_summary} marks={summary.marks} />
          </Panel>
          {trial.arms.length > 0 && (
            <Panel
              title={observational ? "Groups and cohorts" : "Arms: who gets what"}
              action={<Count value={trial.arms.length} />}
            >
              <ArmCards trial={trial} />
            </Panel>
          )}
          {trial.interventions.length > 0 && (
            <Panel title="Interventions" action={<Count value={trial.interventions.length} />}>
              <InterventionList trial={trial} />
            </Panel>
          )}
          {description.trim() && (
            <Panel
              title="Description"
              action={
                <div className="flex items-center gap-1">
                  <AnnotateButton view={described} />
                  {description.length > LONG && !described.shown && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="-my-1"
                      onClick={() => setFull(!full)}
                    >
                      {full ? "Show less" : "Show all"}
                    </Button>
                  )}
                </div>
              }
            >
              <AnnotationLegend view={described} />
              <div className={cn("relative", collapsed && "max-h-80 overflow-hidden")}>
                <TextBlocks text={description} marks={described.marks} />
                {collapsed && (
                  <div className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-card" />
                )}
              </div>
            </Panel>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          <Panel title="Design">
            <Facts
              items={[
                ["Study type", trial.study_type ? label("study_type", trial.study_type) : null],
                [
                  "Purpose",
                  trial.primary_purpose ? label("primary_purpose", trial.primary_purpose) : null,
                ],
                ...(observational
                  ? ([
                      [
                        "Model",
                        trial.observational_model
                          ? label("observational_model", trial.observational_model)
                          : null,
                      ],
                      [
                        "Time perspective",
                        trial.time_perspective
                          ? label("time_perspective", trial.time_perspective)
                          : null,
                      ],
                    ] as [string, ReactNode][])
                  : ([
                      [
                        "Allocation",
                        trial.allocation ? label("allocation", trial.allocation) : null,
                      ],
                      [
                        "Model",
                        trial.intervention_model
                          ? label("intervention_model", trial.intervention_model)
                          : null,
                      ],
                      [
                        "Masking",
                        trial.masking ? (
                          <>
                            {label("masking", trial.masking)}
                            {roles && (
                              <span className="block text-xs text-muted-foreground">{roles}</span>
                            )}
                          </>
                        ) : null,
                      ],
                    ] as [string, ReactNode][])),
                [observational ? "Groups" : "Arms", trial.arms_count],
                [
                  "Sites",
                  trial.location_scope
                    ? (SCOPES[trial.location_scope] ?? humanize(trial.location_scope))
                    : null,
                ],
              ]}
            />
          </Panel>
          <Panel title="Sponsors">
            <div className="flex flex-col gap-3 text-sm">
              {lead && (
                <div className="space-y-0.5">
                  <Link
                    to="/trials"
                    search={{ sponsors: [lead.name] }}
                    className="font-medium hover:underline"
                  >
                    {lead.name}
                  </Link>
                  <div className="text-xs text-muted-foreground">
                    Lead sponsor
                    {lead.sponsor_class && ` · ${label("sponsor_class", lead.sponsor_class)}`}
                  </div>
                </div>
              )}
              {collaborators.length > 0 && (
                <div className="space-y-1.5 border-t pt-3">
                  <div className="text-xs text-muted-foreground">Collaborators</div>
                  <ul className="space-y-1">
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
                </div>
              )}
              {!lead && collaborators.length === 0 && (
                <span className="text-muted-foreground">None listed.</span>
              )}
            </div>
          </Panel>
          {(conditionTerms.length > 0 || interventionTerms.length > 0) && (
            <Panel title="MeSH terms">
              <div className="flex flex-col gap-3">
                {(
                  [
                    ["Conditions", conditionTerms],
                    ["Interventions", interventionTerms],
                  ] as const
                ).map(
                  ([title, terms]) =>
                    terms.length > 0 && (
                      <div key={title} className="space-y-1.5">
                        <div className="text-xs text-muted-foreground">{title}</div>
                        <Chips>
                          {terms.map((term) => (
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
                      </div>
                    ),
                )}
              </div>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}

function Count({ value }: { value: number }) {
  return (
    <span className="rounded-full bg-muted px-2 text-xs leading-5 font-medium text-muted-foreground tabular">
      {value}
    </span>
  );
}

export function EligibilityTab({ trial }: { trial: TrialDetail }) {
  const criteria = useAnnotation(trial, "eligibility_criteria");
  const min = formatAge(trial.min_age_days);
  const max = formatAge(trial.max_age_days);
  const ages =
    min && max ? `${min} to ${max}` : min ? `${min} and older` : max ? `Up to ${max}` : "Any age";
  const sex = trial.sex
    ? ({ ALL: "All", FEMALE: "Female", MALE: "Male" }[trial.sex] ?? humanize(trial.sex))
    : "—";
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <Panel title="Criteria" className="min-w-0" action={<AnnotateButton view={criteria} />}>
        <AnnotationLegend view={criteria} />
        <TextBlocks
          text={trial.eligibility_criteria}
          className="max-w-3xl"
          marks={criteria.marks}
        />
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
