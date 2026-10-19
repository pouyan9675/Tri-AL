/**
 * The analysis page: larger, interactive views of the trials, starting with the research
 * landscape in 3-D. Like the dashboard, it's drawn from chart specs (those whose `page` is
 * "analysis"), so plugins add analyses without front-end code, and it takes the same filter.
 */
import { useQuery } from "@tanstack/react-query";
import { getRouteApi, Link } from "@tanstack/react-router";
import { ArrowRight, Orbit } from "lucide-react";
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
import { activeCount } from "@/lib/filters";
import { formatNumber } from "@/lib/format";
import { ROW_HEIGHT } from "@/pages/dashboard/widget-card";

const route = getRouteApi("/analysis");

export function AnalysisPage() {
  const filter = route.useSearch();
  const navigate = route.useNavigate();
  const dashboard = useQuery(dashboardQuery());
  const meta = useQuery(metaQuery());
  const filtered = activeCount(filter) > 0;
  const matching = useQuery({ ...facetsQuery(filter, ["status"], 1), enabled: filtered });

  if (dashboard.isError) {
    return <ErrorState error={dashboard.error} onRetry={() => void dashboard.refetch()} />;
  }
  const charts = onPage(dashboard.data?.charts, "analysis");

  const description = filtered ? (
    <>
      <span className="font-medium text-foreground tabular">
        {matching.data ? formatNumber(matching.data.total) : "…"}
      </span>{" "}
      {meta.data ? `of ${formatNumber(meta.data.trials)} ` : ""}trials match the filter.
    </>
  ) : (
    "The trials seen through their text: where they sit by what they're about."
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
      {filtered && (
        <FilterChips filter={filter} onChange={(next) => void navigate({ search: next })} />
      )}
      <div className="@container flex flex-col gap-10" data-testid="analysis">
        {!dashboard.data ? (
          <Skeleton className="w-full rounded-xl" style={{ height: 3 * ROW_HEIGHT }} />
        ) : charts.length > 0 ? (
          <ChartSections charts={charts} filter={filter} />
        ) : (
          <NoAnalyses />
        )}
      </div>
    </Page>
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
