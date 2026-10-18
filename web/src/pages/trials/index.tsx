import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { getRouteApi, Link } from "@tanstack/react-router";
import { ChartColumnBig, Check, ListFilter, SearchX } from "lucide-react";
import { useCallback } from "react";
import type { SortKey } from "@/api/client";
import { metaQuery, trialsQuery } from "@/api/queries";
import { FilterChips } from "@/components/filter-chips";
import { Page } from "@/components/page";
import { ErrorState } from "@/components/route-states";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { activeCount, DEFAULT_SORT, onlyFilter, type TrialFilter } from "@/lib/filters";
import { formatNumber } from "@/lib/format";
import { FilterPanel } from "./filter-panel";
import { ResultsTable } from "./results-table";

const route = getRouteApi("/trials");

const SORTS: { value: SortKey; label: string }[] = [
  { value: "-last_update", label: "Recently updated" },
  { value: "-first_posted", label: "Recently posted" },
  { value: "-start_date", label: "Start date, newest" },
  { value: "start_date", label: "Start date, oldest" },
  { value: "-enrollment", label: "Most participants" },
  { value: "enrollment", label: "Fewest participants" },
  { value: "-id", label: "Newest registered" },
  { value: "id", label: "Oldest registered" },
];

export function TrialsPage() {
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const filter = onlyFilter(search);
  const sort = search.sort ?? DEFAULT_SORT;
  const meta = useQuery(metaQuery());
  const trials = useInfiniteQuery(trialsQuery(filter, sort));
  const total = trials.data?.pages[0]?.total ?? null;
  const active = activeCount(filter);

  const setFilter = useCallback(
    (next: TrialFilter) =>
      void navigate({
        search: (prev) => ({ ...next, sort: prev.sort }),
        replace: false,
        resetScroll: false,
      }),
    [navigate],
  );
  const setSort = (next: SortKey) =>
    void navigate({
      search: (prev) => ({ ...prev, sort: next === DEFAULT_SORT ? undefined : next }),
      resetScroll: false,
    });

  const sortLabel = SORTS.find((option) => option.value === sort)?.label ?? sort;

  const description =
    total !== null ? (
      <span>
        <span className="font-medium text-foreground tabular">{formatNumber(total)}</span>
        {active > 0 && meta.data ? ` of ${formatNumber(meta.data.trials)}` : ""} trials
        {active > 0 ? " match" : ""}
      </span>
    ) : (
      <Skeleton className="h-4 w-40" />
    );

  return (
    <Page
      title="Trials"
      description={description}
      actions={
        <>
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="outline" size="sm" className="lg:hidden">
                <ListFilter />
                Filters
                {active > 0 && (
                  <span className="rounded-full bg-brand px-1.5 text-[0.65rem] leading-4 font-semibold text-brand-foreground">
                    {active}
                  </span>
                )}
              </Button>
            </SheetTrigger>
            <SheetContent
              side="left"
              className="w-[88vw] max-w-sm gap-0 overflow-y-auto p-0"
              onOpenAutoFocus={(event) => event.preventDefault()}
            >
              <SheetHeader className="border-b">
                <SheetTitle>Filters</SheetTitle>
                <SheetDescription>Counts update as you choose.</SheetDescription>
              </SheetHeader>
              <div className="p-4">
                <FilterPanel filter={filter} onChange={setFilter} />
              </div>
            </SheetContent>
          </Sheet>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <span className="hidden text-muted-foreground sm:inline">Sort:</span> {sortLabel}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52">
              <DropdownMenuLabel>Sort by</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {SORTS.map((option) => (
                <DropdownMenuItem key={option.value} onSelect={() => setSort(option.value)}>
                  {option.label}
                  {option.value === sort && <Check className="ml-auto" />}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
          <Button asChild variant="outline" size="sm">
            <Link to="/" search={filter}>
              <ChartColumnBig />
              Charts
            </Link>
          </Button>
        </>
      }
    >
      <div className="flex gap-6">
        <aside className="hidden w-72 shrink-0 lg:block">
          <div className="sticky top-20 max-h-[calc(100svh-6rem)] overflow-y-auto pr-2 pb-6">
            <FilterPanel filter={filter} onChange={setFilter} />
          </div>
        </aside>
        <section className="flex min-w-0 flex-1 flex-col gap-3">
          <FilterChips filter={filter} onChange={setFilter} />
          {trials.isError ? (
            <ErrorState error={trials.error} onRetry={() => void trials.refetch()} />
          ) : total === 0 ? (
            <Empty className="border bg-card">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <SearchX />
                </EmptyMedia>
                <EmptyTitle>No trials match</EmptyTitle>
                <EmptyDescription>Remove a filter or two to see more.</EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <Button variant="outline" onClick={() => setFilter({})}>
                  Clear all filters
                </Button>
              </EmptyContent>
            </Empty>
          ) : (
            <ResultsTable
              data={trials.data}
              sort={sort}
              onSort={setSort}
              hasNextPage={trials.hasNextPage}
              isFetchingNextPage={trials.isFetchingNextPage}
              fetchNextPage={() => void trials.fetchNextPage()}
              refreshing={trials.isPlaceholderData}
            />
          )}
        </section>
      </div>
    </Page>
  );
}
