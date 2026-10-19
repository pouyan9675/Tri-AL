import { useQuery } from "@tanstack/react-query";
import { getRouteApi, Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import { dashboardQuery, facetsQuery, metaQuery, onPage } from "@/api/queries";
import { ChartSections, GRID } from "@/components/chart-sections";
import { FilterChips } from "@/components/filter-chips";
import { Page } from "@/components/page";
import { ErrorState } from "@/components/route-states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { activeCount } from "@/lib/filters";
import { formatDate, formatNumber } from "@/lib/format";
import { ROW_HEIGHT, spanFor } from "./widget-card";

const route = getRouteApi("/");

export function DashboardPage() {
  const filter = route.useSearch();
  const navigate = route.useNavigate();
  const dashboard = useQuery(dashboardQuery());
  const meta = useQuery(metaQuery());
  const filtered = activeCount(filter) > 0;
  const matching = useQuery({ ...facetsQuery(filter, ["status"], 1), enabled: filtered });
  const through = Object.values(meta.data?.sources ?? {})
    .filter(Boolean)
    .sort()
    .at(-1);

  if (dashboard.isError) {
    return <ErrorState error={dashboard.error} onRetry={() => void dashboard.refetch()} />;
  }

  const description = meta.data ? (
    filtered ? (
      <>
        <span className="font-medium text-foreground tabular">
          {matching.data ? formatNumber(matching.data.total) : "…"}
        </span>{" "}
        of {formatNumber(meta.data.trials)} trials match the filter.
      </>
    ) : (
      <>
        {formatNumber(meta.data.trials)} trials from ClinicalTrials.gov
        {through ? `, through ${formatDate(through)}` : ""}.
      </>
    )
  ) : (
    <Skeleton className="h-4 w-72" />
  );

  return (
    <Page
      title="Dashboard"
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
      <div className="@container flex flex-col gap-10" data-testid="dashboard">
        {dashboard.data ? (
          <ChartSections charts={onPage(dashboard.data.charts, "dashboard")} filter={filter} />
        ) : (
          <div className={GRID}>
            {[4, 4, 2, 2].map((width, index) => (
              <Skeleton
                // biome-ignore lint/suspicious/noArrayIndexKey: placeholders
                key={index}
                className={spanFor(width)}
                style={{ height: index === 0 ? 92 : ROW_HEIGHT + 60 }}
              />
            ))}
          </div>
        )}
      </div>
    </Page>
  );
}
