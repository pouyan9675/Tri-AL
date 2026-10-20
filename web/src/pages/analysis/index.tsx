/**
 * The analysis page: larger, interactive views of the trials, in sections (`sections.ts`),
 * each its own route under `/analysis`. All take the same filter. The landscape section is
 * drawn from chart specs (those whose `page` is "analysis"), so plugins add analyses to it
 * without front-end code; it starts with the research landscape in 3-D. Trial linking is
 * `linking.tsx`, Advanced search is `search/` (trials by field), and Conditions and
 * Interventions are `terms/` (one MeSH term in depth).
 */
import { useQuery } from "@tanstack/react-query";
import { getRouteApi, Link, Outlet, useRouterState } from "@tanstack/react-router";
import { ArrowRight, ClipboardCheck, Orbit } from "lucide-react";
import type { ReactNode } from "react";
import type { ChartSpec } from "@/api/client";
import { dashboardQuery, facetsQuery, metaQuery, onPage } from "@/api/queries";
import { ChartSections } from "@/components/chart-sections";
import { FilterChips } from "@/components/filter-chips";
import { Page } from "@/components/page";
import { ErrorState } from "@/components/route-states";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { activeCount, parseFilter, type TrialFilter, withoutFilter } from "@/lib/filters";
import { formatNumber } from "@/lib/format";
import { ROW_HEIGHT } from "@/pages/dashboard/widget-card";
import { ANALYSIS_SECTIONS, analysisSection } from "./sections";

const route = getRouteApi("/analysis");

function useSection() {
  return analysisSection(useRouterState({ select: (state) => state.location.pathname }));
}

/** The frame every section shares: the header, the sections, the filter. */
export function AnalysisPage() {
  // The route's search holds the sections' own params too; the frame keeps only the filter.
  const filter = parseFilter(route.useSearch());
  const navigate = route.useNavigate();
  const section = useSection();
  const meta = useQuery(metaQuery());
  const filtered = activeCount(filter) > 0;
  const matching = useQuery({ ...facetsQuery(filter, ["status"], 1), enabled: filtered });

  const description = filtered ? (
    <>
      <span className="font-medium text-foreground tabular">
        {matching.data ? formatNumber(matching.data.total) : "…"}
      </span>{" "}
      {meta.data ? `of ${formatNumber(meta.data.trials)} ` : ""}trials match the filter.
    </>
  ) : (
    section.description
  );

  return (
    <Page
      title="Analysis"
      description={description}
      actions={
        <Button asChild variant="outline" size="sm">
          <Link to="/trials" search={filter}>
            {filtered ? "List these trials" : "Explore trials"}
            <ArrowRight />
          </Link>
        </Button>
      }
    >
      <SectionNav filter={filter} />
      {filtered && (
        <FilterChips
          filter={filter}
          onChange={(next) =>
            void navigate({
              to: section.to,
              search: (prev) => ({ ...withoutFilter(prev), ...next }),
            })
          }
        />
      )}
      <Outlet />
    </Page>
  );
}

/** The sections as tabs; each keeps the filter (but not another section's own params). */
function SectionNav({ filter }: { filter: TrialFilter }) {
  return (
    <nav
      aria-label="Analysis sections"
      className="no-scrollbar -mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0"
    >
      <div className="inline-flex h-8 w-max items-center rounded-lg bg-muted p-[3px] text-muted-foreground">
        {ANALYSIS_SECTIONS.map((section) => (
          <Link
            key={section.to}
            to={section.to}
            search={filter}
            resetScroll={false}
            activeOptions={{ exact: true, includeSearch: false }}
            className="inline-flex h-[calc(100%-1px)] items-center gap-1.5 rounded-md border border-transparent px-2 text-sm font-medium whitespace-nowrap text-foreground/60 transition-all hover:text-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-1 focus-visible:outline-ring data-[status=active]:bg-background data-[status=active]:text-foreground data-[status=active]:shadow-sm dark:text-muted-foreground dark:hover:text-foreground dark:data-[status=active]:border-input dark:data-[status=active]:bg-input/30 dark:data-[status=active]:text-foreground [&_svg]:size-4 [&_svg]:shrink-0"
          >
            <section.icon />
            {section.label}
          </Link>
        ))}
      </div>
    </nav>
  );
}

/** The trials as a whole: the chart specs for the analysis page. */
export function LandscapeSection() {
  return <ChartsOn page="analysis" empty={<NoAnalyses />} />;
}

/** What posted results say: the results plugin's chart specs. */
export function ResultsSection() {
  return <ChartsOn page="results" empty={<NoResults />} />;
}

/** The chart specs for one page, in their sections, under the page's filter. */
function ChartsOn({ page, empty }: { page: ChartSpec["page"]; empty: ReactNode }) {
  const filter = route.useSearch();
  const dashboard = useQuery(dashboardQuery());

  if (dashboard.isError) {
    return <ErrorState error={dashboard.error} onRetry={() => void dashboard.refetch()} />;
  }
  const charts = onPage(dashboard.data?.charts, page);

  return (
    <div className="@container flex flex-col gap-10" data-testid={page}>
      {!dashboard.data ? (
        <Skeleton className="w-full rounded-xl" style={{ height: 3 * ROW_HEIGHT }} />
      ) : charts.length > 0 ? (
        <ChartSections charts={charts} filter={filter} />
      ) : (
        empty
      )}
    </div>
  );
}

function NoResults() {
  return (
    <Empty className="rounded-xl border border-dashed py-16">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <ClipboardCheck />
        </EmptyMedia>
        <EmptyTitle>No results analyses</EmptyTitle>
        <EmptyDescription>
          Turn on the results plugin to analyse the results posted to ClinicalTrials.gov.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button asChild variant="outline" size="sm">
          <Link to="/settings">Open Settings</Link>
        </Button>
      </EmptyContent>
    </Empty>
  );
}

function NoAnalyses() {
  return (
    <Empty className="rounded-xl border border-dashed py-16">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Orbit />
        </EmptyMedia>
        <EmptyTitle>No analyses yet</EmptyTitle>
        <EmptyDescription>
          Analyses come from plugins. Turn on the insights plugin for the 3D map of the research
          landscape.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button asChild variant="outline" size="sm">
          <Link to="/settings">Open Settings</Link>
        </Button>
      </EmptyContent>
    </Empty>
  );
}
