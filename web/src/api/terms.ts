/**
 * Query options for the term analyses (`/api/terms`): a MeSH condition or intervention in
 * depth, each analysis its own request so the cards fill in as they arrive. Data queries,
 * under `["data"]`, like the rest: a new data version refetches them. The router imports
 * `termQuery` for its loader, so this small module is in the first load.
 */
import { queryOptions } from "@tanstack/react-query";
import { canonical, type TrialFilter } from "@/lib/filters";
import { ApiError, api, type TermKind, unwrap } from "./client";
import { DATA_KEY } from "./queries";

/** Matching terms of a kind (the most used with no `q`), for the picker. */
export const findTermsQuery = (kind: TermKind, q: string, limit = 12) =>
  queryOptions({
    queryKey: [...DATA_KEY, "terms", kind, q, limit],
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/api/terms", {
          params: { query: { kind, q: q.trim() || undefined, limit } },
          signal,
        }),
      ),
    staleTime: Number.POSITIVE_INFINITY,
    placeholderData: (previous) => previous,
  });

type Analysis =
  | "overview"
  | "timeline"
  | "readouts"
  | "related"
  | "pipeline"
  | "attrition"
  | "durations"
  | "profile"
  | "themes"
  | "similar";

const keyFor = (analysis: Analysis, kind: TermKind, code: string, filter: TrialFilter) =>
  [...DATA_KEY, "term", analysis, kind, code, canonical(filter)] as const;

/** While the filter changes, the term's last result stays (faded); a new term starts empty. */
const keepTerm =
  (code: string) =>
  <T>(previous: T | undefined, query?: { queryKey: readonly unknown[] }) =>
    query?.queryKey[4] === code ? previous : undefined;

function options<T>(
  analysis: Analysis,
  kind: TermKind,
  code: string,
  filter: TrialFilter,
  fetch: (signal: AbortSignal) => Promise<T>,
) {
  return queryOptions({
    queryKey: keyFor(analysis, kind, code, filter),
    queryFn: ({ signal }) => fetch(signal),
    staleTime: Number.POSITIVE_INFINITY,
    placeholderData: keepTerm(code),
    // The first request after a start waits for the trial index; a 503 says try again.
    retry: (failures, error) => failures < 3 && error instanceof ApiError && error.status === 503,
    retryDelay: 2000,
  });
}

const path = (kind: TermKind, code: string) => ({ kind, code });

export const termQuery = (kind: TermKind, code: string, filter: TrialFilter) =>
  options("overview", kind, code, filter, (signal) =>
    unwrap(
      api.GET("/api/terms/{kind}/{code}", {
        params: { path: path(kind, code), query: filter },
        signal,
      }),
    ),
  );

export const termTimelineQuery = (kind: TermKind, code: string, filter: TrialFilter) =>
  options("timeline", kind, code, filter, (signal) =>
    unwrap(
      api.GET("/api/terms/{kind}/{code}/timeline", {
        params: { path: path(kind, code), query: filter },
        signal,
      }),
    ),
  );

export const termReadoutsQuery = (kind: TermKind, code: string, filter: TrialFilter) =>
  options("readouts", kind, code, filter, (signal) =>
    unwrap(
      api.GET("/api/terms/{kind}/{code}/readouts", {
        params: { path: path(kind, code), query: filter },
        signal,
      }),
    ),
  );

export const termRelatedQuery = (kind: TermKind, code: string, filter: TrialFilter) =>
  options("related", kind, code, filter, (signal) =>
    unwrap(
      api.GET("/api/terms/{kind}/{code}/related", {
        params: { path: path(kind, code), query: filter },
        signal,
      }),
    ),
  );

export const termPipelineQuery = (kind: TermKind, code: string, filter: TrialFilter) =>
  options("pipeline", kind, code, filter, (signal) =>
    unwrap(
      api.GET("/api/terms/{kind}/{code}/pipeline", {
        params: { path: path(kind, code), query: filter },
        signal,
      }),
    ),
  );

export const termAttritionQuery = (kind: TermKind, code: string, filter: TrialFilter) =>
  options("attrition", kind, code, filter, (signal) =>
    unwrap(
      api.GET("/api/terms/{kind}/{code}/attrition", {
        params: { path: path(kind, code), query: filter },
        signal,
      }),
    ),
  );

export const termDurationsQuery = (kind: TermKind, code: string, filter: TrialFilter) =>
  options("durations", kind, code, filter, (signal) =>
    unwrap(
      api.GET("/api/terms/{kind}/{code}/durations", {
        params: { path: path(kind, code), query: filter },
        signal,
      }),
    ),
  );

export const termProfileQuery = (kind: TermKind, code: string, filter: TrialFilter) =>
  options("profile", kind, code, filter, (signal) =>
    unwrap(
      api.GET("/api/terms/{kind}/{code}/profile", {
        params: { path: path(kind, code), query: filter },
        signal,
      }),
    ),
  );

export const termThemesQuery = (kind: TermKind, code: string, filter: TrialFilter) =>
  options("themes", kind, code, filter, (signal) =>
    unwrap(
      api.GET("/api/terms/{kind}/{code}/themes", {
        params: { path: path(kind, code), query: filter },
        signal,
      }),
    ),
  );

/** Similar terms span the registry: the filter doesn't apply. */
export const termSimilarQuery = (kind: TermKind, code: string) =>
  options("similar", kind, code, {}, (signal) =>
    unwrap(
      api.GET("/api/terms/{kind}/{code}/similar", { params: { path: path(kind, code) }, signal }),
    ),
  );
