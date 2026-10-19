/** Chart specs from `/api/dashboard` in their sections: a heading each, then a grid of cards. */
import type { ChartSpec } from "@/api/client";
import type { TrialFilter } from "@/lib/filters";
import { WidgetCard } from "@/pages/dashboard/widget-card";

export const GRID = "grid grid-cols-1 gap-4 @2xl:grid-cols-2 @5xl:grid-cols-4";

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

export function ChartSections({ charts, filter }: { charts: ChartSpec[]; filter: TrialFilter }) {
  return sections(charts).map((section) => (
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
  ));
}

function SectionHeading({ title }: { title: string }) {
  return (
    <div className="flex items-center gap-3">
      <h2 className="text-base font-semibold tracking-tight">{title}</h2>
      <div className="h-px flex-1 bg-border" />
    </div>
  );
}
