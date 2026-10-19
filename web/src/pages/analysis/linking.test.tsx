import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { LinkedTrials, TrialSummary } from "@/api/client";
import { parseFilter } from "@/lib/filters";
import { parseSearch, stringifySearch } from "@/lib/search-params";
import { META, mockApi } from "@/test/api";
import { renderWithProviders } from "@/test/render";
import { LinkingSection } from "./linking";
import { parseLinkingSearch } from "./sections";

function summary(sourceId: string, phase: string | null, title: string): TrialSummary {
  return {
    id: Number(sourceId.slice(3)),
    source: "ctgov",
    source_id: sourceId,
    title,
    status: "COMPLETED",
    phase,
    study_type: "INTERVENTIONAL",
    start_date: "2021-11-16",
    completion_date: null,
    last_update: null,
    enrollment: 148,
    has_results: false,
    num_sites: 1,
    lead_sponsor: "Eli Lilly and Company",
    conditions: ["Alzheimer Disease"],
  };
}

const AD = "D000544";
const DONANEMAB = "C000729112";

function linked(terms: string[] | null): LinkedTrials {
  const on = (code: string) => terms === null || terms.includes(code);
  return {
    data_version: 3,
    trial: summary("NCT05108922", "PHASE3", "Donanemab compared with aducanumab"),
    terms: [
      { code: AD, term: "Alzheimer Disease", kind: "condition", selected: on(AD), trials: 3 },
      {
        code: DONANEMAB,
        term: "donanemab",
        kind: "intervention",
        selected: on(DONANEMAB),
        trials: 3,
      },
    ],
    total: 3,
    phases: [
      {
        phase: "PHASE2",
        total: 1,
        trials: [
          {
            trial: summary("NCT04640077", "PHASE2", "Donanemab follow-on"),
            shared: [AD, DONANEMAB],
          },
        ],
      },
      {
        phase: "PHASE3",
        total: 2,
        trials: [
          { trial: summary("NCT04437511", "PHASE3", "TRAILBLAZER-ALZ 2"), shared: [AD, DONANEMAB] },
        ],
      },
    ],
  };
}

async function show(path: string) {
  const { requests } = mockApi({
    "/api/meta": META,
    "/api/trials/NCT05108922/linked": (_request: Request, url: URL) => {
      const terms = url.searchParams.getAll("terms");
      return linked(terms.length ? terms : null);
    },
    "/api/trials/NCT00000000/linked": () =>
      Response.json({ detail: "no trial NCT00000000" }, { status: 404 }),
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
        path: "linking",
        validateSearch: parseLinkingSearch,
        component: LinkingSection,
      }),
    ]),
    createRoute({ getParentRoute: () => root, path: "/trials/$sourceId", component: () => null }),
  ]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
    parseSearch,
    stringifySearch,
  });
  renderWithProviders(<RouterProvider router={router} />);
  await screen.findByTestId("linking");
  const linkedRequests = () => requests.filter((r) => r.url.includes("/linked"));
  return { router, linkedRequests };
}

describe("trial linking", () => {
  it("links the trial entered, by phase", async () => {
    const { router, linkedRequests } = await show("/analysis/linking?phase=PHASE2&phase=PHASE3");
    expect(screen.getByText("Link a trial")).toBeInTheDocument();

    await userEvent.type(screen.getByRole("textbox", { name: "Trial ID" }), " nct05108922 ");
    await userEvent.click(screen.getByRole("button", { name: "Find linked trials" }));

    expect(await screen.findByText("Donanemab compared with aducanumab")).toBeInTheDocument();
    expect(router.state.location.href).toBe(
      "/analysis/linking?phase=PHASE2&phase=PHASE3&trial=NCT05108922",
    );
    // The page's filter goes along.
    const url = new URL(linkedRequests().at(-1)?.url ?? "");
    expect(url.searchParams.getAll("phase")).toEqual(["PHASE2", "PHASE3"]);
    expect(url.searchParams.getAll("terms")).toEqual([]);

    const phase3 = screen.getByRole("region", { name: "Phase 3" });
    expect(within(phase3).getByText("2 trials")).toBeInTheDocument();
    expect(within(phase3).getByText("TRAILBLAZER-ALZ 2")).toBeInTheDocument();
    expect(within(phase3).getByText("Shares Alzheimer Disease · donanemab")).toBeInTheDocument();
    expect(within(phase3).getByText(/Showing the 1 that share the most terms, of 2/)).toBeVisible();
  });

  it("links by the terms left on", async () => {
    const { router, linkedRequests } = await show("/analysis/linking?trial=NCT05108922");
    const conditions = await screen.findByRole("group", { name: "Conditions" });
    const ad = within(conditions).getByRole("button", { name: /Alzheimer Disease/ });
    expect(ad).toHaveAttribute("aria-pressed", "true");

    await userEvent.click(ad);
    await waitFor(() =>
      expect(router.state.location.href).toBe(
        `/analysis/linking?trial=NCT05108922&terms=${DONANEMAB}`,
      ),
    );
    await waitFor(() =>
      expect(new URL(linkedRequests().at(-1)?.url ?? "").searchParams.getAll("terms")).toEqual([
        DONANEMAB,
      ]),
    );
    expect(await screen.findByText(/no condition is selected/)).toBeInTheDocument();
    // The last term on can't be turned off.
    expect(screen.getByRole("button", { name: /donanemab/ })).toBeDisabled();
  });

  it("says when there's no such trial", async () => {
    await show("/analysis/linking?trial=NCT00000000");
    expect(await screen.findByText("No trial NCT00000000")).toBeInTheDocument();
  });
});

describe("parseLinkingSearch", () => {
  it("keeps a trial and its terms", () => {
    expect(parseLinkingSearch({ trial: " NCT1 ", terms: "D1" })).toEqual({
      trial: "NCT1",
      terms: ["D1"],
    });
    expect(parseLinkingSearch({ trial: "", terms: ["D1", ""] })).toEqual({ terms: ["D1"] });
    expect(parseLinkingSearch({ status: "COMPLETED" })).toEqual({});
  });
});
