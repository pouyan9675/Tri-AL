import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type {
  Schemas,
  TermAttrition,
  TermDurations,
  TermOverview,
  TermPipeline,
  TermProfile,
  TermReadouts,
  TermRelated,
  TermSimilar,
  TermThemes,
  TermTimeline,
  TrialSummary,
} from "@/api/client";
import { parseFilter } from "@/lib/filters";
import { parseSearch, stringifySearch } from "@/lib/search-params";
import { META, mockApi } from "@/test/api";
import { renderWithProviders } from "@/test/render";
import { parseTermSearch } from "../sections";
import { ConditionsSection, InterventionsSection } from ".";

// jsdom has no canvas: the sub-themes map draws nothing.
vi.mock("@/widgets/scatter-canvas", async (importOriginal) => {
  class FakeCanvas {
    setDots() {}
    setColors() {}
    resize() {}
    pick() {
      return null;
    }
  }
  return { ...(await importOriginal<object>()), LandscapeCanvas: FakeCanvas };
});

const AD = { code: "D000544", term: "Alzheimer Disease", kind: "condition" as const };
const DONANEMAB = { code: "C000729112", term: "donanemab", kind: "intervention" as const };
const LABELS = {
  ...META.labels,
  phase_group: {
    phase1: "Phase 1",
    phase2: "Phase 2",
    phase3: "Phase 3",
    phase4: "Phase 4",
    other: "Other",
  },
};

const trial: TrialSummary = {
  id: 1,
  source: "ctgov",
  source_id: "NCT04437511",
  title: "TRAILBLAZER-ALZ 2",
  status: "ACTIVE_NOT_RECRUITING",
  phase: "PHASE3",
  study_type: "INTERVENTIONAL",
  start_date: "2020-06-19",
  completion_date: "2027-04-01",
  last_update: "2026-09-01",
  enrollment: 1736,
  has_results: false,
  num_sites: 277,
  lead_sponsor: "Eli Lilly and Company",
  conditions: ["Alzheimer Disease"],
};

const overview: TermOverview = {
  data_version: 3,
  term: AD,
  trials: 3869,
  registry_trials: 3869,
  within: 607349,
  direct: 3800,
  narrower: [{ code: "C000001", term: "Familial Alzheimer Disease", trials: 69 }],
  active: 924,
  completed: 2095,
  stopped: 395,
  with_results: 701,
  lead_sponsors: 1305,
  industry: 1261,
  countries: 74,
  first_start: "1981-01-19",
  as_of: "2026-10-16",
};

const timeline: TermTimeline = {
  data_version: 3,
  years: [
    { year: 2025, trials: 257, phases: [40, 50, 20, 10, 137], share: 0.0064, new_sponsors: 85 },
    { year: 2026, trials: 197, phases: [30, 40, 15, 5, 107], share: 0.0058, new_sponsors: 48 },
  ],
  partial: true,
  momentum: [3, 6, 12].map((months) => ({
    months,
    since: "2026-04-16",
    until: "2026-10-16",
    trials: 144,
    baseline: 275,
    expected: 156,
    growth: months === 12 ? 0.9 : 1.02,
    raw_growth: 0.92,
    p: months === 12 ? 0.02 : 0.44,
    confidence: months === 12 ? ("high" as const) : ("low" as const),
    direction: months === 12 ? ("falling" as const) : ("steady" as const),
  })),
};

const readouts: TermReadouts = {
  data_version: 3,
  as_of: "2026-10-16",
  until: "2028-10-16",
  total: 1,
  overdue: 4,
  quarters: [{ quarter: "2027-Q2", start: "2027-04-01", trials: 1, phases: [0, 0, 1, 0, 0] }],
  trials: [{ trial, primary_completion: "2027-04-01", estimated: true }],
};

const related: TermRelated = {
  data_version: 3,
  trials: 3869,
  others: 603480,
  tested: 419,
  conditions: [
    {
      code: "D011595",
      term: "Psychomotor Agitation",
      kind: "condition",
      trials: 103,
      share: 0.027,
      elsewhere: 0.0001,
      lift: 74.2,
      p: 1e-50,
      q: 1e-48,
      confidence: "high",
    },
  ],
  interventions: [
    {
      ...DONANEMAB,
      trials: 15,
      share: 0.004,
      elsewhere: 0,
      lift: 196.9,
      p: 1e-20,
      q: 1e-18,
      confidence: "high",
    },
  ],
  nodes: [
    { ...AD, trials: 3869, lift: null, group: -1, center: true },
    {
      code: "D011595",
      term: "Psychomotor Agitation",
      kind: "condition",
      trials: 103,
      lift: 74.2,
      group: 0,
      center: false,
    },
    { ...DONANEMAB, trials: 15, lift: 196.9, group: 1, center: false },
  ],
  edges: [{ source: 1, target: 2, trials: 2, jaccard: 0.02 }],
};

const pipeline: TermPipeline = {
  data_version: 3,
  kind: "intervention",
  phases: [
    "EARLY_PHASE1",
    "PHASE1",
    "PHASE1_PHASE2",
    "PHASE2",
    "PHASE2_PHASE3",
    "PHASE3",
    "PHASE4",
  ],
  rows: [
    {
      code: "D000077265",
      term: "Donepezil",
      kind: "intervention",
      trials: 123,
      phases: [1, 26, 1, 28, 2, 14, 25],
      active: 9,
      highest: "PHASE4",
      last_start: "2025-05-01",
    },
    {
      ...DONANEMAB,
      trials: 15,
      phases: [0, 4, 0, 5, 0, 6, 0],
      active: 5,
      highest: "PHASE3",
      last_start: "2025-01-01",
    },
  ],
  funnel: [
    {
      phase: "PHASE3",
      trials: 286,
      active: 51,
      completed: 161,
      stopped: 61,
      unknown: 10,
      other: 3,
    },
  ],
};

const attrition: TermAttrition = {
  data_version: 3,
  phases: [
    {
      group: "phase3",
      closed: 265,
      stopped: 72,
      rate: 0.2717,
      baseline_closed: 30000,
      baseline_rate: 0.1602,
      ratio: 1.6964,
      p: 1e-6,
      q: 1e-5,
      confidence: "high",
    },
  ],
  observed: 395,
  expected: 365.7,
  ratio: 1.08,
  p: 0.11,
  confidence: "medium",
  stopped: 395,
  read: 395,
  stated: 338,
  reasons: [
    {
      key: "efficacy",
      label: "Efficacy or futility",
      trials: 32,
      examples: [{ source_id: "NCT01111111", reason: "Futility at the interim analysis" }],
    },
  ],
};

const curve = (group: string, median: number | null) => ({
  group,
  trials: 100,
  events: 60,
  median,
  months: [6, 12, 24],
  values: [0.9, 0.6, 0.3],
});

const durations: TermDurations = {
  data_version: 3,
  completion: ["phase1", "phase2", "phase3", "phase4", "other", "all"].map((g) => curve(g, 40)),
  completion_baseline: ["phase1", "phase2", "phase3", "phase4", "other", "all"].map((g) =>
    curve(g, 30),
  ),
  results: { ...curve("all", null), values: [0.1, 0.2, 0.3] },
  results_baseline: { ...curve("all", null), values: [0.05, 0.15, 0.2] },
  results_at: [
    { months: 12, share: 0.04, baseline: 0.03 },
    { months: 24, share: 0.23, baseline: 0.15 },
    { months: 36, share: 0.3, baseline: 0.2 },
  ],
};

const profile: TermProfile = {
  data_version: 3,
  trials: 3869,
  baseline_trials: 603480,
  rows: [
    {
      key: "min_age",
      label: "Minimum age",
      section: "Population",
      unit: "years",
      value: 50,
      baseline: 18,
      difference: 1.66,
      trials: 3656,
    },
    {
      key: "blinded",
      label: "Double-blind or more",
      section: "Design",
      unit: "share",
      value: 0.456,
      baseline: 0.291,
      difference: 0.35,
      trials: 3031,
    },
  ],
  enrollment: [
    { low: 1, high: 10, share: 0.06, baseline: 0.06 },
    { low: 5001, high: null, share: 0.02, baseline: 0.015 },
  ],
};

const themes: TermThemes = {
  data_version: 3,
  trials: 3869,
  embedded: 3869,
  sampled: 3869,
  silhouette: 0.09,
  themes: [
    {
      cluster: 0,
      label: "caregivers · care · dementia",
      words: ["caregivers", "care", "dementia"],
      terms: [{ code: "D017028", term: "Caregiver Burden", kind: "condition" }],
      size: 570,
      share: 0.15,
      growth: 1.37,
      confidence: "high",
      examples: [{ source_id: "NCT02222222", title: "Supporting dementia caregivers" }],
    },
  ],
  points: [{ x: 0.1, y: -0.2, cluster: 0, source_id: "NCT02222222", title: "Supporting" }],
};

const similar: TermSimilar = {
  data_version: 3,
  embedded: 3869,
  same: [
    {
      code: "D003704",
      term: "Dementia",
      kind: "condition",
      similarity: 0.91,
      trials: 2245,
      shared: 937,
    },
    {
      code: "D060825",
      term: "Cognitive Dysfunction",
      kind: "condition",
      similarity: 0.87,
      trials: 1184,
      shared: 0,
    },
  ],
  other: [{ ...DONANEMAB, similarity: 0.81, trials: 17, shared: 15 }],
};

const found: Schemas["TermsOut"] = {
  data_version: 3,
  kind: "condition",
  terms: [
    { code: AD.code, term: AD.term, trials: 3869 },
    { code: "D003704", term: "Dementia", trials: 5829 },
  ],
};

async function show(path: string) {
  const base = `/api/terms/condition/${AD.code}`;
  const { requests } = mockApi({
    "/api/meta": { ...META, labels: LABELS },
    "/api/terms": found,
    [base]: overview,
    [`${base}/timeline`]: timeline,
    [`${base}/readouts`]: readouts,
    [`${base}/related`]: related,
    [`${base}/pipeline`]: pipeline,
    [`${base}/attrition`]: attrition,
    [`${base}/durations`]: durations,
    [`${base}/profile`]: profile,
    [`${base}/themes`]: themes,
    [`${base}/similar`]: similar,
    "/api/terms/condition/D999999": () =>
      Response.json({ detail: "no condition term 'D999999'" }, { status: 404 }),
  });
  const root = createRootRoute();
  const analysis = createRoute({
    getParentRoute: () => root,
    path: "/analysis",
    validateSearch: parseFilter,
  });
  const routeTree = root.addChildren([
    analysis.addChildren([
      createRoute({
        getParentRoute: () => analysis,
        path: "conditions",
        validateSearch: parseTermSearch,
        component: ConditionsSection,
      }),
      createRoute({
        getParentRoute: () => analysis,
        path: "interventions",
        validateSearch: parseTermSearch,
        component: InterventionsSection,
      }),
    ]),
    createRoute({ getParentRoute: () => root, path: "/trials", component: () => null }),
    createRoute({ getParentRoute: () => root, path: "/trials/$sourceId", component: () => null }),
  ]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
    parseSearch,
    stringifySearch,
  });
  renderWithProviders(<RouterProvider router={router} />);
  await screen.findByTestId("term-section");
  return { router, requests };
}

describe("the conditions section", () => {
  it("starts from the most studied conditions", async () => {
    const { router } = await show("/analysis/conditions?phase=PHASE3");
    const suggestions = await screen.findByTestId("term-suggestions");
    await userEvent.click(await within(suggestions).findByRole("button", { name: /Dementia/ }));
    expect(router.state.location.href).toBe("/analysis/conditions?phase=PHASE3&term=D003704");
  });

  it("shows every analysis of the term, within the filter", async () => {
    const { requests } = await show(`/analysis/conditions?term=${AD.code}&phase=PHASE3`);
    const header = await screen.findByTestId("term-header");
    expect(within(header).getByRole("heading", { name: "Alzheimer Disease" })).toBeVisible();
    expect(within(header).getByText("3,869")).toBeVisible();
    expect(
      within(header).getByRole("link", { name: /Familial Alzheimer Disease/ }),
    ).toHaveAttribute("href", "/analysis/conditions?phase=PHASE3&term=C000001");
    expect(within(header).getByRole("link", { name: /List these trials/ })).toHaveAttribute(
      "href",
      "/trials?phase=PHASE3&mesh=D000544",
    );

    for (const id of [
      "term-timeline",
      "term-readouts",
      "term-related",
      "term-network",
      "term-pipeline",
      "term-attrition",
      "term-durations",
      "term-profile",
      "term-themes",
      "term-similar",
    ]) {
      await waitFor(() => expect(screen.getByTestId(id)).toHaveAttribute("data-state", "ready"));
    }

    // Each analysis asked within the filter, except similar terms, which span the registry.
    const analyses = requests.filter((r) => new URL(r.url).pathname.startsWith("/api/terms/"));
    for (const request of analyses) {
      const url = new URL(request.url);
      const phases = url.searchParams.getAll("phase");
      expect(phases).toEqual(url.pathname.endsWith("/similar") ? [] : ["PHASE3"]);
    }

    expect(within(screen.getByTestId("term-timeline")).getByText("0.90×")).toBeVisible();
    expect(
      within(screen.getByTestId("term-readouts")).getByText("TRAILBLAZER-ALZ 2"),
    ).toBeVisible();
    const relatedCard = screen.getByTestId("term-related");
    expect(within(relatedCard).getByRole("link", { name: "donanemab" })).toHaveAttribute(
      "href",
      "/analysis/interventions?phase=PHASE3&term=C000729112",
    );
    expect(within(relatedCard).getByText("197×")).toBeVisible();
    expect(
      within(screen.getByTestId("term-network")).getByRole("button", { name: /donanemab/ }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("pipeline-heatmap"))
        .getAllByRole("row")
        .map((row) => row.textContent?.slice(0, 9)),
    ).toEqual(["Intervent", "Donepezil", "donanemab"]); // furthest phase first
    expect(within(screen.getByTestId("term-attrition")).getByText("1.08×")).toBeVisible();
    expect(within(screen.getByTestId("term-durations")).getByText(/Median 3\.3 yr/)).toBeVisible();
    expect(within(screen.getByTestId("benchmarks")).getByText("50 yr")).toBeVisible();
    expect(
      within(screen.getByTestId("term-themes")).getByText("caregivers · care · dementia"),
    ).toBeVisible();
    const similarCard = screen.getByTestId("term-similar");
    expect(within(similarCard).getAllByText("Never together")).toHaveLength(1);
  });

  it("opens a stop reason's examples", async () => {
    await show(`/analysis/conditions?term=${AD.code}`);
    const reasons = await screen.findByTestId("stop-reasons");
    await userEvent.click(within(reasons).getByRole("button", { name: /Efficacy or futility/ }));
    expect(within(reasons).getByText(/Futility at the interim analysis/)).toBeVisible();
  });

  it("says when there's no such term", async () => {
    await show("/analysis/conditions?term=d999999");
    expect(await screen.findByText(/No condition/)).toBeVisible();
    expect(screen.getByText("D999999")).toBeVisible();
  });
});
