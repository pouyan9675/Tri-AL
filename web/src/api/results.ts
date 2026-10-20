/**
 * The results plugin's API (`/api/x/results/`): a trial's posted results. Its types come from
 * `results.gen.ts`, which `npm run api` generates from the plugin's own OpenAPI schema, so
 * nothing here describes the API by hand. The trial page asks only when the trial has results
 * and the plugin is on (`meta.plugins`).
 */
import { queryOptions } from "@tanstack/react-query";
import createClient from "openapi-fetch";
import { unwrap } from "./client";
import { DATA_KEY } from "./queries";
import type { components, paths } from "./results.gen";

type Schemas = components["schemas"];
export type TrialResults = Schemas["TrialResultsOut"];
export type ResultsGroup = Schemas["GroupOut"];
export type Flow = Schemas["FlowOut"];
export type Baseline = Schemas["BaselineOut"];
export type Measure = Schemas["MeasureOut"];
export type MeasureClass = Schemas["ClassOut"];
export type MeasuredValue = Schemas["ValueOut"];
export type OutcomeResult = Schemas["OutcomeResultOut"];
export type Analysis = Schemas["AnalysisOut"];
export type AdverseEvents = Schemas["AdverseEventsOut"];
export type EventGroup = Schemas["EventGroupOut"];
export type AdverseEvent = Schemas["EventOut"];

export const RESULTS_PLUGIN = "results";

const results = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? "",
  // Looked up on each call, so tests can stub `fetch`.
  fetch: (request) => globalThis.fetch(request),
});

export const trialResultsQuery = (sourceId: string) =>
  queryOptions({
    queryKey: [...DATA_KEY, "results", sourceId],
    queryFn: ({ signal }) =>
      unwrap(
        results.GET("/api/x/results/trials/{source_id}", {
          params: { path: { source_id: sourceId } },
          signal,
        }),
      ),
    staleTime: Number.POSITIVE_INFINITY,
  });
