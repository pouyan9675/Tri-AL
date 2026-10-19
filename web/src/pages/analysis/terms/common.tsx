/** What the term analyses share: the card frame, links to terms, phase colours, formats. */
import type { UseQueryResult } from "@tanstack/react-query";
import { getRouteApi, Link } from "@tanstack/react-router";
import { CircleAlert, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";
import { ApiError, type TermKind } from "@/api/client";
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
import { parseFilter } from "@/lib/filters";
import { cn } from "@/lib/utils";

/** The analysis page's route; its search holds the filter (and a section's own params). */
export const analysis = getRouteApi("/analysis");

export const KINDS = {
  condition: {
    to: "/analysis/conditions",
    one: "condition",
    many: "conditions",
    Many: "Conditions",
  },
  intervention: {
    to: "/analysis/interventions",
    one: "intervention",
    many: "interventions",
    Many: "Interventions",
  },
} as const satisfies Record<TermKind, { to: string; one: string; many: string; Many: string }>;

export const otherKind = (kind: TermKind): TermKind =>
  kind === "condition" ? "intervention" : "condition";

/** A term's name, linking to its own analysis (in its kind's section), with the filter. */
export function TermLink({
  kind,
  code,
  className,
  children,
}: {
  kind: TermKind;
  code: string;
  className?: string;
  children: ReactNode;
}) {
  const filter = parseFilter(analysis.useSearch());
  return (
    <Link
      to={KINDS[kind].to}
      search={{ ...filter, term: code }}
      className={cn(
        "decoration-muted-foreground/40 underline-offset-2 hover:underline focus-visible:underline",
        className,
      )}
    >
      {children}
    </Link>
  );
}

/** The phase groups term analyses count by (`phase_group` in the meta's labels), in order. */
export const PHASE_GROUPS = ["phase1", "phase2", "phase3", "phase4", "other"] as const;
export const PHASE_COLORS = [
  "var(--phase-1)",
  "var(--phase-2)",
  "var(--phase-3)",
  "var(--phase-4)",
  "var(--phase-other)",
];

export function percent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  const shown = value * 100;
  if (shown > 0 && shown < 1 && digits === 0) return `${shown.toFixed(1)}%`;
  return `${shown.toFixed(digits)}%`;
}

export function months(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value >= 24 ? `${(value / 12).toFixed(1)} yr` : `${Math.round(value)} mo`;
}

export function times(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value >= 10 ? Math.round(value) : value.toFixed(value >= 2 ? 1 : 2)}×`;
}

/** A section of term analyses: a heading and its cards. */
export function TermSectionGroup({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="@container flex flex-col gap-3">
      <div className="flex flex-col gap-0.5">
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      <div className="grid grid-cols-1 gap-4 @4xl:grid-cols-2">{children}</div>
    </section>
  );
}

/**
 * One analysis in a card: its title, then the result, a skeleton while it loads, or what
 * went wrong. A result for another filter stays, faded, while the new one loads.
 */
export function AnalysisCard<T>({
  title,
  description,
  query,
  action,
  wide,
  height = 280,
  testId,
  children,
}: {
  title: string;
  description: ReactNode;
  query: UseQueryResult<T>;
  action?: (data: T) => ReactNode;
  wide?: boolean;
  height?: number;
  testId: string;
  children: (data: T) => ReactNode;
}) {
  const { data } = query;
  return (
    <Card
      className={cn("min-w-0 gap-3 shadow-xs", wide && "@4xl:col-span-2")}
      data-testid={testId}
      data-state={query.isError ? "error" : data === undefined ? "loading" : "ready"}
    >
      <CardHeader className="gap-0.5">
        <CardTitle className="text-[0.95rem]">{title}</CardTitle>
        <CardDescription className="text-xs">{description}</CardDescription>
        {data !== undefined && action && <CardAction>{action(data)}</CardAction>}
      </CardHeader>
      <CardContent
        className={cn(
          "flex min-h-0 flex-1 flex-col transition-opacity",
          query.isPlaceholderData && "opacity-60",
        )}
      >
        {query.isError && data === undefined ? (
          <Failed error={query.error} onRetry={() => void query.refetch()} />
        ) : data === undefined ? (
          <Skeleton className="w-full rounded-lg" style={{ height }} />
        ) : (
          children(data)
        )}
      </CardContent>
    </Card>
  );
}

function Failed({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const busy = error instanceof ApiError && error.status === 503;
  return (
    <div className="flex min-h-32 flex-col items-center justify-center gap-2 text-center text-sm text-muted-foreground">
      {busy ? <LoaderCircle className="size-5" /> : <CircleAlert className="size-5" />}
      <span className="max-w-sm">
        {busy
          ? "The server is still preparing its index of every trial."
          : error instanceof Error
            ? error.message
            : "This analysis didn't load."}
      </span>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

/** A small key: a swatch and a name for each series. */
export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-[3px]" style={{ background: item.color }} />
          {item.label}
        </li>
      ))}
    </ul>
  );
}
