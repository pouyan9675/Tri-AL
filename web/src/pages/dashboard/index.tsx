import { useQuery } from "@tanstack/react-query";
import { getRouteApi, Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import type { ChartSpec } from "@/api/client";
import { dashboardQuery, facetsQuery, metaQuery } from "@/api/queries";
import { FilterChips } from "@/components/filter-chips";
import { Page } from "@/components/page";
import { ErrorState } from "@/components/route-states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { activeCount } from "@/lib/filters";
import { formatDate, formatNumber } from "@/lib/format";
import { ROW_HEIGHT, spanFor, WidgetCard } from "./widget-card";

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
          sections(dashboard.data.charts).map((section) => (
            <section
              key={section.title}
              aria-label={section.title || undefined}
              className="flex flex-col gap-4"
              data-section={section.title}
            >
              {section.title && <SectionHeading title={section.title} />}
              <div className={GRID}>
                {section.charts.map((spec) => (
                  <WidgetCard key={spec.id} spec={spec} filter={filter} />
                ))}
              </div>
            </section>
          ))
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

const GRID = "grid grid-cols-1 gap-4 @2xl:grid-cols-2 @5xl:grid-cols-4";

type Section = { title: string; charts: ChartSpec[] };

/** Charts by section, each section where its first chart is in the layout order. */
export function sections(charts: ChartSpec[]): Section[] {
  const bySection = new Map<string, ChartSpec[]>();
  for (const chart of charts) {
    const list = bySection.get(chart.section);
    if (list) list.push(chart);
    else bySection.set(chart.section, [chart]);
  }
  return [...bySection].map(([title, list]) => ({ title, charts: list }));
}

function SectionHeading({ title }: { title: string }) {
  return (
    <div className="flex items-center gap-3">
      <h2 className="text-base font-semibold tracking-tight">{title}</h2>
      <div className="h-px flex-1 bg-border" />
    </div>
  );
}
