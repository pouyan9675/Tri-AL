/**
 * Query options for every endpoint the pages read.
 *
 * Data only changes when the data version does, so data queries (keys under `["data"]`)
 * never go stale by themselves: the live event stream invalidates them all when an update
 * commits (`lib/live.ts`). The browser still revalidates each with its ETag, so a refetch of
 * unchanged data is a 304. Jobs and plugins change without the data version and are fetched
 * fresh.
 */
import { infiniteQueryOptions, keepPreviousData, queryOptions } from "@tanstack/react-query";
import { canonical, type TrialFilter } from "@/lib/filters";
import { api, type ChartSpec, type SortKey, unwrap } from "./client";

export const DATA_KEY = ["data"] as const;
export const JOBS_KEY = ["jobs"] as const;
export const PAGE_SIZE = 50;

export const metaQuery = () =>
  queryOptions({
    queryKey: [...DATA_KEY, "meta"],
    queryFn: ({ signal }) => unwrap(api.GET("/api/meta", { signal })),
    staleTime: Number.POSITIVE_INFINITY,
  });

export const dashboardQuery = () =>
  queryOptions({
    queryKey: [...DATA_KEY, "dashboard"],
    queryFn: ({ signal }) => unwrap(api.GET("/api/dashboard", { signal })),
    staleTime: Number.POSITIVE_INFINITY,
  });

/** The charts a page shows (the dashboard or the analysis page), in layout order. */
export function onPage(charts: ChartSpec[] | undefined, page: ChartSpec["page"]): ChartSpec[] {
  return (charts ?? []).filter((chart) => chart.page === page);
}

export const chartQuery = (chartId: string, filter: TrialFilter) =>
  queryOptions({
    queryKey: [...DATA_KEY, "chart", chartId, canonical(filter)],
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/api/stats/{chart_id}", {
          params: { path: { chart_id: chartId }, query: filter },
          signal,
        }),
      ),
    staleTime: Number.POSITIVE_INFINITY,
    placeholderData: keepPreviousData,
  });

export const facetsQuery = (filter: TrialFilter, fields?: string[], limit = 8) =>
  queryOptions({
    queryKey: [...DATA_KEY, "facets", canonical(filter), fields ?? "all", limit],
    queryFn: ({ signal }) =>
      unwrap(api.GET("/api/facets", { params: { query: { ...filter, fields, limit } }, signal })),
    staleTime: Number.POSITIVE_INFINITY,
    placeholderData: keepPreviousData,
  });

export const trialsQuery = (filter: TrialFilter, sort: SortKey) =>
  infiniteQueryOptions({
    queryKey: [...DATA_KEY, "trials", canonical(filter), sort],
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET("/api/trials", {
          params: {
            query: { ...filter, sort, cursor: pageParam ?? undefined, limit: PAGE_SIZE },
          },
          signal,
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    staleTime: Number.POSITIVE_INFINITY,
    placeholderData: keepPreviousData,
  });

export const trialQuery = (sourceId: string) =>
  queryOptions({
    queryKey: [...DATA_KEY, "trial", sourceId],
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/api/trials/{source_id}", { params: { path: { source_id: sourceId } }, signal }),
      ),
    staleTime: Number.POSITIVE_INFINITY,
  });

export const changesQuery = (sourceId: string) =>
  queryOptions({
    queryKey: [...DATA_KEY, "changes", sourceId],
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/api/trials/{source_id}/changes", {
          params: { path: { source_id: sourceId } },
          signal,
        }),
      ),
    staleTime: Number.POSITIVE_INFINITY,
  });

/** Trials that share a trial's MeSH terms (`terms`; all of them if not given), by phase. */
export const linkedTrialsQuery = (
  sourceId: string,
  terms: string[] | undefined,
  filter: TrialFilter,
) =>
  queryOptions({
    queryKey: [...DATA_KEY, "linked", sourceId, terms ?? "all", canonical(filter)],
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/api/trials/{source_id}/linked", {
          params: { path: { source_id: sourceId }, query: { ...filter, terms } },
          signal,
        }),
      ),
    staleTime: Number.POSITIVE_INFINITY,
    placeholderData: keepPreviousData,
  });

export const searchQuery = (q: string, { limit = 8, names = 6 } = {}) =>
  queryOptions({
    queryKey: [...DATA_KEY, "search", q, limit, names],
    queryFn: ({ signal }) =>
      unwrap(api.GET("/api/search", { params: { query: { q, limit, names } }, signal })),
    staleTime: Number.POSITIVE_INFINITY,
    placeholderData: keepPreviousData,
    enabled: q.trim().length > 0,
  });

/** Matching condition, intervention or sponsor names, for a facet's search box. */
export const namesQuery = (q: string) =>
  queryOptions({
    queryKey: [...DATA_KEY, "names", q],
    queryFn: ({ signal }) =>
      unwrap(api.GET("/api/search", { params: { query: { q, limit: 1, names: 30 } }, signal })),
    staleTime: Number.POSITIVE_INFINITY,
    placeholderData: keepPreviousData,
    enabled: q.trim().length >= 3,
    select: (result) => result.names,
  });

export const JOBS_LIMIT = 20;

export const jobsQuery = () =>
  queryOptions({
    queryKey: JOBS_KEY,
    queryFn: ({ signal }) =>
      unwrap(api.GET("/api/jobs", { params: { query: { limit: JOBS_LIMIT } }, signal })),
  });

export const pluginsQuery = () =>
  queryOptions({
    queryKey: ["plugins"],
    queryFn: ({ signal }) => unwrap(api.GET("/api/plugins", { signal })),
  });
