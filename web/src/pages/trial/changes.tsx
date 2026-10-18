/** A trial's change history: what each update changed, newest first, old value → new. */
import type { UseQueryResult } from "@tanstack/react-query";
import { ArrowRight, History } from "lucide-react";
import type { Change, Changes } from "@/api/client";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate, formatDateTime, formatNumber, humanize } from "@/lib/format";
import { useLabels } from "@/lib/labels";

const CODED: Record<string, string> = {
  status: "status",
  phase: "phase",
  study_type: "study_type",
  lead_sponsor_class: "sponsor_class",
};

function Value({ field, value }: { field: string; value: unknown }) {
  const label = useLabels();
  if (value === null || value === undefined || value === "") {
    return <span className="text-muted-foreground italic">none</span>;
  }
  if (Array.isArray(value)) {
    return <span>{value.length ? value.map(String).join(", ") : "none"}</span>;
  }
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  if (typeof value === "number") return <span className="tabular">{formatNumber(value)}</span>;
  if (typeof value === "string") {
    if (CODED[field]) return <span>{label(CODED[field], value)}</span>;
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return <span>{formatDate(value)}</span>;
    return <span>{value}</span>;
  }
  return <code className="text-xs">{JSON.stringify(value)}</code>;
}

/** For lists, what was added and removed reads better than two whole lists. */
function ListDiff({ old, next }: { old: unknown[]; next: unknown[] }) {
  const before = new Set(old.map(String));
  const after = new Set(next.map(String));
  const added = [...after].filter((item) => !before.has(item));
  const removed = [...before].filter((item) => !after.has(item));
  return (
    <div className="flex flex-wrap gap-1.5 text-xs">
      {added.map((item) => (
        <span key={`+${item}`} className="rounded-md border border-good/30 bg-good/8 px-1.5 py-0.5">
          + {item}
        </span>
      ))}
      {removed.map((item) => (
        <span
          key={`-${item}`}
          className="rounded-md border border-critical/30 bg-critical/8 px-1.5 py-0.5 line-through decoration-critical/60"
        >
          {item}
        </span>
      ))}
      {!added.length && !removed.length && <span className="text-muted-foreground">Reordered</span>}
    </div>
  );
}

function ChangeRow({ change }: { change: Change }) {
  const lists = Array.isArray(change.old) && Array.isArray(change.new);
  return (
    <li className="grid gap-1 py-2.5 sm:grid-cols-[11rem_1fr] sm:gap-4">
      <span className="text-sm font-medium">{humanize(change.field)}</span>
      {lists ? (
        <ListDiff old={change.old as unknown[]} next={change.new as unknown[]} />
      ) : (
        <span className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground line-through decoration-muted-foreground/40">
            <Value field={change.field} value={change.old} />
          </span>
          <ArrowRight className="size-3.5 text-muted-foreground" />
          <Value field={change.field} value={change.new} />
        </span>
      )}
    </li>
  );
}

export function ChangesTab({ query }: { query: UseQueryResult<Changes> }) {
  if (!query.data) return <Skeleton className="h-40 w-full rounded-xl" />;
  const changes = query.data.changes;
  if (changes.length === 0) {
    return (
      <Empty className="border bg-card">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <History />
          </EmptyMedia>
          <EmptyTitle>No changes recorded</EmptyTitle>
          <EmptyDescription>
            Updates record what they change in a trial, such as its status, dates or enrollment.
            This one hasn't changed since it was installed.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }
  const runs = new Map<number, Change[]>();
  for (const change of changes)
    runs.set(change.run_id, [...(runs.get(change.run_id) ?? []), change]);
  return (
    <ol className="relative flex flex-col gap-4 border-l pl-6">
      {[...runs.entries()].map(([run, items]) => (
        <li key={run} className="relative">
          <span className="absolute top-4 -left-[1.95rem] size-3 rounded-full border-2 border-background bg-brand" />
          <div className="rounded-xl border bg-card px-4 py-3 shadow-xs">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-semibold">{formatDateTime(items[0]?.changed_at)}</span>
              <span className="text-xs text-muted-foreground">
                Update {run} · {items.length} field{items.length === 1 ? "" : "s"}
              </span>
            </div>
            <ul className="mt-1 divide-y">
              {items.map((change) => (
                <ChangeRow key={`${change.field}-${change.run_id}`} change={change} />
              ))}
            </ul>
          </div>
        </li>
      ))}
    </ol>
  );
}
