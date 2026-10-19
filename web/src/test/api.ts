/** A stand-in for the API: `fetch` answers from a table of paths, and records each request. */
import { vi } from "vitest";
import type { AiSettings, AnnotationEvent, Meta } from "@/api/client";

type Handler = unknown | ((request: Request, url: URL) => unknown | Response);

export function mockApi(routes: Record<string, Handler>) {
  const requests: Request[] = [];
  const fetch = vi.fn(async (input: RequestInfo | URL) => {
    const request = input instanceof Request ? input : new Request(String(input));
    requests.push(request);
    const url = new URL(request.url);
    const handler = routes[`${request.method} ${url.pathname}`] ?? routes[url.pathname];
    if (handler === undefined) {
      return Response.json({ detail: `no mock for ${url.pathname}` }, { status: 404 });
    }
    const body = typeof handler === "function" ? await handler(request, url) : handler;
    return body instanceof Response ? body : Response.json(body);
  });
  vi.stubGlobal("fetch", fetch);
  return { fetch, requests };
}

export const META: Meta = {
  version: "2.0.0",
  installed: true,
  data_version: 3,
  trials: 607349,
  last_run: {
    run_id: 3,
    kind: "update",
    finished_at: "2026-10-17T22:30:15+00:00",
    new: 4,
    updated: 12,
    unchanged: 2590,
  },
  sources: { ctgov: "2026-10-16" },
  schedule: "daily",
  plugins: ["charts", "ctgov"],
  search_candidates: 20000,
  labels: {
    status: {
      RECRUITING: "Recruiting",
      COMPLETED: "Completed",
      ACTIVE_NOT_RECRUITING: "Active, not recruiting",
    },
    phase: { PHASE2: "Phase 2", PHASE3: "Phase 3", NA: "Not applicable" },
    study_type: { INTERVENTIONAL: "Interventional" },
    sponsor_class: { INDUSTRY: "Industry" },
    intervention_type: { DRUG: "Drug" },
  },
};

export const AI_SETTINGS: AiSettings = {
  enabled: true,
  backend: "openai",
  backends: [{ name: "openai", title: "OpenAI-compatible server" }],
  server: "http://127.0.0.1:1234/v1",
  model: "",
  labels: [
    { name: "Condition", description: "Diseases", examples: ["dementia"], color: "red" },
    { name: "Intervention", description: "", examples: [], color: "blue" },
  ],
  colors: ["blue", "orange", "teal", "amber", "pink", "green", "violet", "red"],
  locked: [],
};

/** An annotation stream, as the API sends it. */
export function ndjson(events: AnnotationEvent[]): Response {
  const body = events.map((event) => `${JSON.stringify(event)}\n`).join("");
  return new Response(body, { headers: { "content-type": "application/x-ndjson" } });
}
