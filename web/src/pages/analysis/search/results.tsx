/**
 * What an advanced search found: how many, how each field was read, then the trials, each with
 * where its words are and, with a place, its nearest site. Pages load as the list grows.
 */
import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { MapPin, SearchX } from "lucide-react";
import type { ReactNode } from "react";
import { ADVANCED_PAGE, advancedSearchQuery } from "@/api/advanced";
import type { Schemas } from "@/api/client";
import { ErrorState } from "@/components/route-states";
import { Snippet } from "@/components/snippet";
import { TrialFacts } from "@/components/trial-facts";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { type AdvancedSearch, type AdvancedSort, FIELDS } from "@/lib/advanced";
import type { TrialFilter } from "@/lib/filters";
import { formatNumber } from "@/lib/format";
import { useLabels } from "@/lib/labels";
import { cn } from "@/lib/utils";

type Hit = Schemas["AdvancedHitOut"];
type FieldRead = Schemas["FieldReadOut"];
type Nearest = Schemas["NearestSiteOut"];

const SORTS: { value: AdvancedSort; label: string }[] = [
  { value: "relevance", label: "Best match" },
  { value: "distance", label: "Nearest first" },
  { value: "-last_update", label: "Recently updated" },
  { value: "-first_posted", label: "Recently posted" },
  { value: "-start_date", label: "Start date, newest" },
  { value: "start_date", label: "Start date, oldest" },
  { value: "-enrollment", label: "Most participants" },
  { value: "-id", label: "Newest registered" },
];

export function Results({
  search,
  filter,
  onSort,
}: {
  search: AdvancedSearch;
  filter: TrialFilter;
  onSort: (sort: AdvancedSort | undefined) => void;
}) {
  const query = useInfiniteQuery(advancedSearchQuery(search, filter));

  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (!query.data) {
    return (
      <div className="flex flex-col gap-3" aria-busy="true">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }
  const first = query.data.pages[0];
  if (!first) return null;
  const hits = query.data.pages.flatMap((page) => page.items);
  const words = first.read.some((field) => field.all.length > 0);
  const sorts = SORTS.filter(
    ({ value }) => (value !== "relevance" || words) && (value !== "distance" || !!search.near),
  );
  const capped = first.ranked !== null && first.ranked < first.total;

  return (
    <section
      aria-label="Results"
      className={cn(
        "flex flex-col gap-4 transition-opacity",
        query.isPlaceholderData && "opacity-60",
      )}
      data-testid="advanced-results"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold tracking-tight">
          <span className="tabular">{formatNumber(first.total)}</span>{" "}
          {first.total === 1 ? "trial" : "trials"}
        </h2>
        {first.total > 1 && (
          <Select
            value={first.sort}
            onValueChange={(value) =>
              onSort(value === defaultSort(search, words) ? undefined : (value as AdvancedSort))
            }
          >
            <SelectTrigger className="w-48" aria-label="Sort">
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end">
              {sorts.map((sort) => (
                <SelectItem key={sort.value} value={sort.value}>
                  {sort.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>
      {first.read.length > 0 && <HowRead read={first.read} />}
      {first.sections && first.sections.checked < first.sections.candidates && (
        <Note>
          Inclusion, exclusion and outcome kinds were checked in the newest{" "}
          {formatNumber(first.sections.checked)} of {formatNumber(first.sections.candidates)} trials
          that match the rest. Narrow the search or the filter to check them all.
        </Note>
      )}
      {capped && first.sort === "relevance" && (
        <Note>
          Ranked by relevance among the newest {formatNumber(first.ranked ?? 0)} matches; the rest
          follow, newest first.
        </Note>
      )}
      {first.total === 0 ? (
        <Empty className="rounded-xl border border-dashed py-12">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <SearchX />
            </EmptyMedia>
            <EmptyTitle>No trials match</EmptyTitle>
            <EmptyDescription>
              Every field must match. Try fewer words, OR between alternatives, or a wider distance.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <ul className="divide-y rounded-xl border bg-card">
          {hits.map((hit) => (
            <HitRow key={hit.trial.id} hit={hit} within={search.within} />
          ))}
        </ul>
      )}
      {query.hasNextPage && (
        <Button
          variant="outline"
          className="self-center"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {query.isFetchingNextPage && <Spinner />}
          Show {formatNumber(Math.min(ADVANCED_PAGE, first.total - hits.length))} more
        </Button>
      )}
    </section>
  );
}

function defaultSort(search: AdvancedSearch, words: boolean): AdvancedSort {
  return words ? "relevance" : search.near ? "distance" : "-last_update";
}

function Note({ children }: { children: ReactNode }) {
  return <p className="text-xs text-muted-foreground">{children}</p>;
}

/** How each field's words were read: what must match, and what mustn't. */
function HowRead({ read }: { read: FieldRead[] }) {
  return (
    <dl className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs" aria-label="How the words were read">
      {read.map((field) => (
        <div key={field.field} className="flex min-w-0 flex-wrap items-center gap-1">
          <dt className="text-muted-foreground">{FIELDS[field.field].label}:</dt>
          {field.all.map((group, index) => (
            <dd key={group.join("|")} className="flex items-center gap-1">
              {index > 0 && <span className="text-muted-foreground">and</span>}
              {group.map((term, at) => (
                <span key={term} className="flex items-center gap-1">
                  {at > 0 && <span className="text-muted-foreground">or</span>}
                  <Term>{term}</Term>
                </span>
              ))}
            </dd>
          ))}
          {field.none.length > 0 && (
            <dd className="flex items-center gap-1">
              <span className="text-muted-foreground">{field.all.length ? "but not" : "not"}</span>
              {field.none.map((term) => (
                <Term key={term} struck>
                  {term}
                </Term>
              ))}
            </dd>
          )}
        </div>
      ))}
    </dl>
  );
}

function Term({ children, struck = false }: { children: string; struck?: boolean }) {
  return (
    <span
      className={cn(
        "rounded-md border bg-muted/50 px-1.5 py-0.5 font-mono text-[0.7rem]",
        struck && "text-muted-foreground line-through",
      )}
    >
      {children}
    </span>
  );
}

function HitRow({ hit, within }: { hit: Hit; within?: number }) {
  const label = useLabels();
  const phase = hit.trial.phase ? label("phase", hit.trial.phase) : undefined;
  return (
    <li className="flex min-w-0 flex-col gap-1.5 px-4 py-3">
      <Link
        to="/trials/$sourceId"
        params={{ sourceId: hit.trial.source_id }}
        className="line-clamp-2 text-sm font-medium decoration-muted-foreground/40 underline-offset-2 hover:underline"
      >
        {hit.trial.title}
      </Link>
      <TrialFacts trial={hit.trial} phase={phase} />
      {hit.trial.conditions.length > 0 && (
        <div className="truncate text-xs text-muted-foreground">
          {hit.trial.conditions.join(" · ")}
        </div>
      )}
      {hit.snippets.map((snippet) => (
        <div key={snippet.field} className="line-clamp-2 text-xs leading-relaxed">
          <span className="font-medium text-foreground/80">{FIELDS[snippet.field].label}: </span>
          <Snippet parts={snippet.parts} />
        </div>
      ))}
      {hit.nearest && <NearestSite site={hit.nearest} within={within} label={label} />}
    </li>
  );
}

function NearestSite({
  site,
  within,
  label,
}: {
  site: Nearest;
  within?: number;
  label: (field: string, code: string | null | undefined) => string;
}) {
  const place = [site.city, site.state, site.country && label("countries", site.country)]
    .filter(Boolean)
    .join(", ");
  const where = site.km < 1 ? `In ${place}` : `${formatNumber(Math.round(site.km))} km: ${place}`;
  return (
    <div className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
      <MapPin className="size-3.5 shrink-0" />
      <span className="truncate">
        {where}
        {site.facility && <span className="text-foreground/80"> · {site.facility}</span>}
        {site.sites > 1 && (
          <span>
            {" "}
            · {formatNumber(site.sites)} sites within {within ?? 50} km
          </span>
        )}
      </span>
    </div>
  );
}
