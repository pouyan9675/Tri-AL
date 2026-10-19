/**
 * Query options for advanced search (`/api/search/advanced`), a page of hits at a time, and
 * for the places it can search near (`/api/places`). Data queries, under `["data"]`: a new
 * data version refetches them. The router imports `advancedSearchQuery` for its loader, so
 * this small module is in the first load.
 */
import { infiniteQueryOptions, keepPreviousData, queryOptions } from "@tanstack/react-query";
import { type AdvancedSearch, apiQuery } from "@/lib/advanced";
import { canonical, type TrialFilter } from "@/lib/filters";
import { ApiError, api, unwrap } from "./client";
import { DATA_KEY } from "./queries";

export const ADVANCED_PAGE = 25;

export const advancedSearchQuery = (search: AdvancedSearch, filter: TrialFilter) => {
  const query = apiQuery(search);
  return infiniteQueryOptions({
    queryKey: [...DATA_KEY, "advanced", query, canonical(filter)],
    queryFn: ({ pageParam, signal }) =>
      unwrap(
        api.GET("/api/search/advanced", {
          params: { query: { ...filter, ...query, offset: pageParam, limit: ADVANCED_PAGE } },
          signal,
        }),
      ),
    initialPageParam: 0,
    getNextPageParam: (page) => page.next_offset,
    staleTime: Number.POSITIVE_INFINITY,
    placeholderData: keepPreviousData,
    // The first request after a start waits for the trial index; a 503 says try again.
    retry: (failures, error) => failures < 3 && error instanceof ApiError && error.status === 503,
    retryDelay: 2000,
  });
};

export const placesQuery = (q: string) =>
  queryOptions({
    queryKey: [...DATA_KEY, "places", q.trim().toLowerCase()],
    queryFn: ({ signal }) =>
      unwrap(api.GET("/api/places", { params: { query: { q: q.trim(), limit: 8 } }, signal })),
    staleTime: Number.POSITIVE_INFINITY,
    placeholderData: keepPreviousData,
    enabled: q.trim().length > 0,
  });
