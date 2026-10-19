/**
 * The Conditions and Interventions sections: one MeSH term in depth. Pick a term (`?term=`
 * in the URL, beside the page's filter) and ten analyses follow, each its own request
 * (`/api/terms/{kind}/{code}/...`, `tri_al.terms`): activity, relations, outcomes and
 * meaning. Every analysis is within the filter, against the filter's other trials.
 */
import { useQuery } from "@tanstack/react-query";
import { getRouteApi, Link, useNavigate } from "@tanstack/react-router";
import { ArrowRight, SearchX } from "lucide-react";
import { ApiError, type TermKind, type TermOverview } from "@/api/client";
import { termQuery } from "@/api/terms";
import { ErrorState } from "@/components/route-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { activeCount, parseFilter } from "@/lib/filters";
import { formatDate, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AttritionCard } from "./attrition";
import { analysis, KINDS, percent, TermLink, TermSectionGroup } from "./common";
import { DurationsCard } from "./durations";
import { Suggestions, TermPicker } from "./picker";
import { PipelineCard } from "./pipeline";
import { ProfileCard } from "./profile";
import { ReadoutsCard } from "./readouts";
import { NetworkCard, RelatedCard } from "./related";
import { SimilarCard, ThemesCard } from "./semantic";
import { TimelineCard } from "./timeline";

const conditions = getRouteApi("/analysis/conditions");
const interventions = getRouteApi("/analysis/interventions");

export function ConditionsSection() {
  const { term } = conditions.useSearch();
  return <TermSection kind="condition" code={term} />;
}

export function InterventionsSection() {
  const { term } = interventions.useSearch();
  return <TermSection kind="intervention" code={term} />;
}

function TermSection({ kind, code }: { kind: TermKind; code: string | undefined }) {
  const filter = parseFilter(analysis.useSearch());
  const navigate = useNavigate();
  const overview = useQuery({ ...termQuery(kind, code ?? "", filter), enabled: !!code });
  const choose = (next: string) =>
    void navigate({ to: KINDS[kind].to, search: (prev) => ({ ...prev, term: next }) });
  const current = overview.data?.term.code === code ? overview.data?.term : undefined;

  return (
    <div className="flex flex-col gap-6" data-testid="term-section" data-kind={kind}>
      <TermPicker kind={kind} current={current} onChoose={choose} />
      {!code ? (
        <Suggestions kind={kind} onChoose={choose} />
      ) : overview.isError && overview.data === undefined ? (
        overview.error instanceof ApiError && overview.error.status === 404 ? (
          <Empty className="rounded-xl border border-dashed py-16">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <SearchX />
              </EmptyMedia>
              <EmptyTitle>
                No {KINDS[kind].one} <span className="font-mono">{code}</span>
              </EmptyTitle>
              <EmptyDescription>
                No trial is tagged with this MeSH code as a {KINDS[kind].one}. Search for one above.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
        )
      ) : !overview.data ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-36 w-full rounded-xl" />
          <Skeleton className="h-72 w-full rounded-xl" />
        </div>
      ) : (
        <Analyses kind={kind} code={code} data={overview.data} faded={overview.isPlaceholderData} />
      )}
    </div>
  );
}

function Analyses({
  kind,
  code,
  data,
  faded,
}: {
  kind: TermKind;
  code: string;
  data: TermOverview;
  faded: boolean;
}) {
  const filter = parseFilter(analysis.useSearch());
  const props = { kind, code, filter };
  if (data.trials === 0) {
    return (
      <>
        <Header data={data} faded={faded} />
        <Empty className="rounded-xl border border-dashed py-12">
          <EmptyHeader>
            <EmptyTitle>No trials within the filter</EmptyTitle>
            <EmptyDescription>
              {data.term.term} has {formatNumber(data.registry_trials)} trials, none of them within
              the filter. Remove a filter to see them.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      </>
    );
  }
  return (
    <>
      <Header data={data} faded={faded} />
      <TermSectionGroup
        title="Activity"
        description="How much research there is, how it's moving, and what's about to report."
      >
        <TimelineCard {...props} />
        <ReadoutsCard {...props} />
      </TermSectionGroup>
      <TermSectionGroup
        title="Relations"
        description={`What goes with ${data.term.term}: the terms tagged on its trials more than chance, how they group, and the pipeline by phase.`}
      >
        <RelatedCard {...props} />
        <NetworkCard {...props} />
        <PipelineCard {...props} />
      </TermSectionGroup>
      <TermSectionGroup
        title="Outcomes"
        description="How its trials end, how long they take, and how they're designed, each against comparable trials."
      >
        <AttritionCard {...props} />
        <DurationsCard {...props} />
        <ProfileCard {...props} />
      </TermSectionGroup>
      <TermSectionGroup
        title="Meaning"
        description="What its trials are about, from the vectors of their text."
      >
        <ThemesCard {...props} />
        <SimilarCard kind={kind} code={code} />
      </TermSectionGroup>
    </>
  );
}

function Header({ data, faded }: { data: TermOverview; faded: boolean }) {
  const filter = parseFilter(analysis.useSearch());
  const filtered = activeCount(filter) > 0;
  const { term } = data;
  const share = (n: number) => (data.trials ? percent(n / data.trials) : "—");
  const tiles = [
    {
      label: "Trials",
      value: formatNumber(data.trials),
      detail: filtered
        ? `of ${formatNumber(data.registry_trials)} in all`
        : `${percent(data.trials / Math.max(1, data.within), 2)} of all trials`,
    },
    { label: "Active", value: formatNumber(data.active), detail: share(data.active) },
    { label: "Completed", value: formatNumber(data.completed), detail: share(data.completed) },
    { label: "Stopped early", value: formatNumber(data.stopped), detail: share(data.stopped) },
    {
      label: "With results",
      value: formatNumber(data.with_results),
      detail: share(data.with_results),
    },
    {
      label: "Lead sponsors",
      value: formatNumber(data.lead_sponsors),
      detail: `${share(data.industry)} industry trials`,
    },
    { label: "Countries", value: formatNumber(data.countries), detail: "with a site" },
    {
      label: "First trial",
      value: data.first_start ? data.first_start.slice(0, 4) : "—",
      detail: data.first_start ? `started ${formatDate(data.first_start)}` : "no start date",
    },
  ];
  return (
    <section
      aria-label={term.term}
      className={cn(
        "@container flex flex-col gap-4 rounded-xl border bg-card p-4 transition-opacity",
        faded && "opacity-60",
      )}
      data-testid="term-header"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold tracking-tight text-balance">{term.term}</h2>
            <Badge variant="secondary" className="font-mono text-[0.7rem] font-normal">
              MeSH {term.code}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">
            {data.direct === data.trials
              ? `Every trial here is tagged with ${term.term} itself.`
              : `${formatNumber(data.direct)} tagged with ${term.term} itself; the rest through narrower terms.`}{" "}
            Data as of {formatDate(data.as_of)}.
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link to="/trials" search={{ ...filter, mesh: [term.code] }}>
            List these trials
            <ArrowRight />
          </Link>
        </Button>
      </div>
      <dl className="grid grid-cols-2 gap-2 @lg:grid-cols-4 @4xl:grid-cols-8">
        {tiles.map((tile) => (
          <div key={tile.label} className="flex flex-col gap-0.5 rounded-lg bg-muted/50 px-3 py-2">
            <dt className="text-xs text-muted-foreground">{tile.label}</dt>
            <dd className="text-lg font-semibold tabular">{tile.value}</dd>
            <dd className="truncate text-[0.7rem] text-muted-foreground" title={tile.detail}>
              {tile.detail}
            </dd>
          </div>
        ))}
      </dl>
      {data.narrower.length > 0 && (
        <div className="flex flex-col gap-1.5 sm:flex-row sm:items-baseline sm:gap-3">
          <span className="shrink-0 text-xs font-medium text-muted-foreground">Narrower terms</span>
          <ul className="flex flex-wrap gap-1.5">
            {data.narrower.map((narrower) => (
              <li key={narrower.code}>
                <TermLink
                  kind={term.kind}
                  code={narrower.code}
                  className="inline-flex h-6 items-center gap-1.5 rounded-full border px-2.5 text-xs hover:no-underline hover:bg-muted"
                >
                  {narrower.term}
                  <span className="text-muted-foreground tabular">
                    {formatNumber(narrower.trials)}
                  </span>
                </TermLink>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
