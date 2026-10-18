/**
 * The typed API client. Every type comes from `schema.gen.ts`, which `npm run api` generates
 * from the API's OpenAPI schema; nothing here describes the API by hand.
 */
import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema.gen";

export type Schemas = components["schemas"];
export type Meta = Schemas["MetaOut"];
export type Dashboard = Schemas["DashboardOut"];
export type ChartSpec = Schemas["ChartSpecOut"];
export type Stats = Schemas["StatsOut"];
export type ChartRow = Stats["rows"][number];
export type Facets = Schemas["FacetsOut"];
export type FacetValue = Schemas["FacetValueOut"];
export type TrialPage = Schemas["TrialPageOut"];
export type TrialSummary = Schemas["TrialSummaryOut"];
export type TrialDetail = Schemas["TrialDetailOut"];
export type Changes = Schemas["ChangesOut"];
export type Change = Schemas["ChangeOut"];
export type SearchResult = Schemas["SearchOut"];
export type SearchHit = Schemas["SearchHitOut"];
export type NameHit = Schemas["NameHitOut"];
export type Job = Schemas["JobOut"];
export type Plugin = Schemas["PluginOut"];
export type ListTrialsQuery = NonNullable<paths["/api/trials"]["get"]["parameters"]["query"]>;
export type SortKey = NonNullable<ListTrialsQuery["sort"]>;

/** Requests that change something must send this header (the API's browser protections). */
export const CLIENT_HEADER = "X-Tri-AL";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

const browserProtection: Middleware = {
  onRequest({ request }) {
    if (UNSAFE_METHODS.has(request.method)) request.headers.set(CLIENT_HEADER, "1");
    return request;
  },
};

export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? "",
  // Looked up on each call, so tests can stub `fetch`.
  fetch: (request) => globalThis.fetch(request),
});
api.use(browserProtection);

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function detail(error: unknown, status: number): string {
  if (error && typeof error === "object" && "detail" in error) {
    const value = (error as { detail: unknown }).detail;
    if (typeof value === "string") return value;
    if (Array.isArray(value)) {
      return value
        .map((item) => (item && typeof item === "object" && "msg" in item ? item.msg : item))
        .join("; ");
    }
  }
  return `The server answered ${status}.`;
}

type Result<T> = { data?: T; error?: unknown; response: Response };

/** The response's data, or an `ApiError` with the server's `detail`. */
export async function unwrap<T>(request: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await request;
  if (error !== undefined || data === undefined) {
    throw new ApiError(response.status, detail(error, response.status), error);
  }
  return data;
}
