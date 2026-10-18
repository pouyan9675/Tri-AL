import { useQuery } from "@tanstack/react-query";
import { BarChart3, Blocks, CircleAlert, Table2 } from "lucide-react";
import { Suspense, useState } from "react";
import type { ChartSpec } from "@/api/client";
import { chartQuery } from "@/api/queries";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { activeCount, type TrialFilter } from "@/lib/filters";
import { cn } from "@/lib/utils";
import { widgetFor } from "@/widgets/registry";
import { TableWidget } from "@/widgets/table";

/** Pixels per unit of a chart's layout height. */
export const ROW_HEIGHT = 260;

const SPAN: Record<number, string> = {
  1: "@5xl:col-span-1",
  2: "@5xl:col-span-2",
  3: "@2xl:col-span-2 @5xl:col-span-3",
  4: "@2xl:col-span-2 @5xl:col-span-4",
};

export function spanFor(width: number): string {
  return SPAN[Math.min(4, Math.max(1, Math.round(width)))] ?? "";
}

/** One chart spec from `/api/dashboard`, drawn by the widget its type names. */
export function WidgetCard({ spec, filter }: { spec: ChartSpec; filter: TrialFilter }) {
  const definition = widgetFor(spec.widget);
  const query = useQuery({ ...chartQuery(spec.id, filter), enabled: definition !== undefined });
  const [view, setView] = useState<"chart" | "table">("chart");
  const height = spec.layout.height * ROW_HEIGHT;
  const state = !definition
    ? "unsupported"
    : query.isError
      ? "error"
      : query.isSuccess
        ? "ready"
        : "loading";
  const refreshing = query.isPlaceholderData || (query.isFetching && query.isSuccess);

  const body =
    state === "unsupported" ? (
      <Unsupported spec={spec} />
    ) : state === "error" ? (
      <div className="flex h-full min-h-32 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
        <CircleAlert className="size-5" />
        {query.error instanceof Error ? query.error.message : "This chart didn't load."}
      </div>
    ) : state === "loading" || !query.data ? (
      <Skeleton
        className="w-full rounded-lg"
        style={{ height: spec.widget === "stat" ? 92 : height }}
      />
    ) : view === "table" ? (
      <TableWidget spec={spec} rows={query.data.rows} height={height} />
    ) : (
      <Suspense fallback={<Skeleton className="w-full rounded-lg" style={{ height }} />}>
        {definition && (
          <definition.component
            spec={spec}
            rows={query.data.rows}
            height={height}
            filter={filter}
          />
        )}
      </Suspense>
    );

  const common = {
    "data-testid": "widget",
    "data-chart": spec.id,
    "data-widget": spec.widget,
    "data-state": state,
  };

  if (definition && !definition.card) {
    return (
      <section
        {...common}
        aria-label={spec.title}
        className={cn(
          "@container",
          spanFor(spec.layout.width),
          refreshing && "opacity-60 transition-opacity",
        )}
      >
        {body}
      </section>
    );
  }

  return (
    <Card {...common} className={cn("min-w-0 gap-3 shadow-xs", spanFor(spec.layout.width))}>
      <CardHeader className="gap-0.5">
        <CardTitle className="flex items-center gap-2 text-[0.95rem]">
          {spec.title}
          {query.data?.filtered && activeCount(filter) > 0 && (
            <Badge variant="secondary" className="h-4.5 px-1.5 text-[0.65rem] font-normal">
              Filtered
            </Badge>
          )}
        </CardTitle>
        {spec.description && (
          <CardDescription className="text-xs">{spec.description}</CardDescription>
        )}
        {definition?.table && state === "ready" && (
          <CardAction>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="-mt-1 -mr-1 text-muted-foreground"
                  aria-label={view === "chart" ? "Show as a table" : "Show as a chart"}
                  onClick={() => setView(view === "chart" ? "table" : "chart")}
                >
                  {view === "chart" ? <Table2 /> : <BarChart3 />}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                {view === "chart" ? "Show as a table" : "Show as a chart"}
              </TooltipContent>
            </Tooltip>
          </CardAction>
        )}
      </CardHeader>
      <CardContent
        className={cn(
          "flex min-h-0 flex-1 flex-col transition-opacity",
          refreshing && "opacity-60",
        )}
      >
        {body}
      </CardContent>
    </Card>
  );
}

function Unsupported({ spec }: { spec: ChartSpec }) {
  return (
    <div
      className="flex h-full min-h-40 flex-col items-center justify-center gap-2 rounded-lg border border-dashed bg-muted/30 p-6 text-center"
      data-testid="widget-placeholder"
    >
      <Blocks className="size-5 text-muted-foreground" />
      <p className="text-sm font-medium">No “{spec.widget}” widget in this version</p>
      <p className="max-w-xs text-xs text-muted-foreground">
        The {spec.plugin} plugin sent a chart type the front end doesn't draw yet.
      </p>
    </div>
  );
}
