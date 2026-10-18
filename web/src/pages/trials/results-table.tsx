/**
 * The trial list: TanStack Table over pages from `/api/trials`, fetched with its keyset
 * cursor (`next_cursor`) as the list scrolls. Sorting is the server's; the headers that can
 * sort say so.
 */
import type { InfiniteData } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import type { SortKey, TrialPage, TrialSummary } from "@/api/client";
import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDate, formatNumber } from "@/lib/format";
import { useLabels } from "@/lib/labels";
import { cn } from "@/lib/utils";

type ColumnMeta = { sort?: string; className?: string };

function useColumns(): ColumnDef<TrialSummary>[] {
  const label = useLabels();
  return useMemo(
    () => [
      {
        id: "id",
        header: "Trial",
        meta: { sort: "id" } satisfies ColumnMeta,
        cell: ({ row: { original: trial } }) => (
          <div className="min-w-0 py-0.5">
            <Link
              to="/trials/$sourceId"
              params={{ sourceId: trial.source_id }}
              className="line-clamp-2 font-medium text-foreground decoration-muted-foreground/40 underline-offset-2 hover:underline"
            >
              {trial.title}
            </Link>
            <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <span className="font-mono text-[0.7rem] text-foreground/70">{trial.source_id}</span>
              {trial.lead_sponsor && (
                <span className="max-w-64 truncate" title={trial.lead_sponsor}>
                  {trial.lead_sponsor}
                </span>
              )}
            </div>
            {trial.conditions.length > 0 && (
              <div
                className="mt-0.5 hidden truncate text-xs text-muted-foreground/80 sm:block"
                title={trial.conditions.join(", ")}
              >
                {trial.conditions.slice(0, 3).join(" · ")}
                {trial.conditions.length > 3 && ` +${trial.conditions.length - 3} more`}
              </div>
            )}
            <div className="mt-1.5 flex flex-wrap gap-1.5 md:hidden">
              <StatusBadge status={trial.status} />
              {trial.phase && trial.phase !== "NA" && (
                <span className="inline-flex h-6 items-center rounded-full border px-2 text-xs">
                  {label("phase", trial.phase)}
                </span>
              )}
            </div>
          </div>
        ),
      },
      {
        id: "status",
        header: "Status and phase",
        meta: { className: "hidden w-48 md:table-cell" } satisfies ColumnMeta,
        cell: ({ row: { original: trial } }) => (
          <div className="flex flex-col items-start gap-1">
            <StatusBadge status={trial.status} />
            <span className="pl-1 text-xs text-muted-foreground">
              {trial.phase ? label("phase", trial.phase) : "No phase given"}
            </span>
          </div>
        ),
      },
      {
        id: "enrollment",
        header: "Enrollment",
        meta: {
          sort: "enrollment",
          className: "hidden w-24 text-right lg:table-cell",
        } satisfies ColumnMeta,
        cell: ({ row: { original: trial } }) => (
          <span className="tabular">{formatNumber(trial.enrollment)}</span>
        ),
      },
      {
        id: "start_date",
        header: "Start",
        meta: {
          sort: "start_date",
          className: "hidden w-28 whitespace-nowrap 2xl:table-cell",
        } satisfies ColumnMeta,
        cell: ({ row: { original: trial } }) => (
          <span className="tabular text-muted-foreground">{formatDate(trial.start_date)}</span>
        ),
      },
      {
        id: "last_update",
        header: "Updated",
        meta: {
          sort: "last_update",
          className: "hidden w-28 whitespace-nowrap sm:table-cell",
        } satisfies ColumnMeta,
        cell: ({ row: { original: trial } }) => (
          <span className="tabular text-muted-foreground">{formatDate(trial.last_update)}</span>
        ),
      },
    ],
    [label],
  );
}

function SortHeader({
  title,
  field,
  sort,
  onSort,
  align,
}: {
  title: string;
  field: string;
  sort: SortKey;
  onSort: (sort: SortKey) => void;
  align?: "right";
}) {
  const active = sort.replace(/^-/, "") === field;
  const descending = sort.startsWith("-");
  const Icon = !active ? ChevronsUpDown : descending ? ArrowDown : ArrowUp;
  return (
    <button
      type="button"
      className={cn(
        "-mx-1.5 inline-flex items-center gap-1 rounded px-1.5 py-1 transition-colors hover:bg-muted hover:text-foreground",
        active && "text-foreground",
        align === "right" && "flex-row-reverse",
      )}
      aria-label={`Sort by ${title.toLowerCase()}`}
      onClick={() => onSort((active && descending ? field : `-${field}`) as SortKey)}
    >
      {title}
      <Icon className={cn("size-3.5", !active && "opacity-40")} />
    </button>
  );
}

export function ResultsTable({
  data,
  sort,
  onSort,
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
  refreshing,
}: {
  data: InfiniteData<TrialPage, unknown> | undefined;
  sort: SortKey;
  onSort: (sort: SortKey) => void;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => void;
  refreshing: boolean;
}) {
  const columns = useColumns();
  const items = useMemo(() => data?.pages.flatMap((page) => page.items) ?? [], [data]);
  const total = data?.pages[0]?.total ?? null;
  const navigate = useNavigate();
  const table = useReactTable({
    data: items,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (trial) => String(trial.id),
    manualSorting: true,
  });

  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = sentinel.current;
    if (!element || !hasNextPage || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting && !isFetchingNextPage) fetchNextPage();
      },
      { rootMargin: "600px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  return (
    <div className="overflow-hidden rounded-xl border bg-card shadow-xs">
      <Table
        className={cn("table-fixed transition-opacity", refreshing && "opacity-60")}
        data-testid="trials-table"
      >
        <TableHeader>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id} className="hover:bg-transparent">
              {group.headers.map((header) => {
                const meta = header.column.columnDef.meta as ColumnMeta | undefined;
                const title = String(header.column.columnDef.header);
                return (
                  <TableHead
                    key={header.id}
                    className={cn(
                      "h-10 bg-muted/40 text-xs font-medium text-muted-foreground first:pl-4",
                      meta?.className,
                    )}
                  >
                    {meta?.sort ? (
                      <SortHeader
                        title={title}
                        field={meta.sort}
                        sort={sort}
                        onSort={onSort}
                        align={meta.className?.includes("text-right") ? "right" : undefined}
                      />
                    ) : (
                      title
                    )}
                  </TableHead>
                );
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {data === undefined
            ? Array.from({ length: 8 }, (_, index) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: placeholders
                <TableRow key={index}>
                  <TableCell className="pl-4" colSpan={columns.length}>
                    <Skeleton className="mb-2 h-4 w-3/4" />
                    <Skeleton className="h-3 w-1/3" />
                  </TableCell>
                </TableRow>
              ))
            : table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  className="cursor-pointer"
                  onClick={(event) => {
                    if ((event.target as HTMLElement).closest("a, button")) return;
                    if (window.getSelection()?.toString()) return;
                    void navigate({
                      to: "/trials/$sourceId",
                      params: { sourceId: row.original.source_id },
                    });
                  }}
                >
                  {row.getVisibleCells().map((cell) => {
                    const meta = cell.column.columnDef.meta as ColumnMeta | undefined;
                    return (
                      <TableCell
                        key={cell.id}
                        className={cn(
                          "py-2.5 align-top first:pl-4 whitespace-normal",
                          meta?.className,
                        )}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
        </TableBody>
      </Table>
      {data !== undefined && (
        <div className="flex items-center justify-between gap-3 border-t px-4 py-2.5 text-xs text-muted-foreground">
          <span className="tabular">
            {items.length === 0
              ? "No trials"
              : `Showing ${formatNumber(items.length)}${total !== null ? ` of ${formatNumber(total)}` : ""}`}
          </span>
          <div ref={sentinel}>
            {hasNextPage && (
              <Button
                variant="outline"
                size="sm"
                onClick={fetchNextPage}
                disabled={isFetchingNextPage}
              >
                {isFetchingNextPage && <Spinner />}
                Load more
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
