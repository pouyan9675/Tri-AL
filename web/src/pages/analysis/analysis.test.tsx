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
import { parseFilter } from "@/lib/filters";
import { parseSearch, stringifySearch } from "@/lib/search-params";
import { META, mockApi } from "@/test/api";
import { renderWithProviders } from "@/test/render";
import { AnalysisPage, LandscapeSection, ResultsSection } from ".";
import { ANALYSIS_SECTIONS, analysisSection } from "./sections";

async function show(path: string) {
  mockApi({
    "/api/meta": META,
    "/api/dashboard": { charts: [] },
    "/api/facets": { data_version: 3, total: 1234, facets: {} },
  });
  const root = createRootRoute();
  const analysis = createRoute({
    getParentRoute: () => root,
    path: "/analysis",
    validateSearch: parseFilter,
    component: AnalysisPage,
  });
  // The other sections have tests of their own; here they're stand-ins.
  const empty = ["linking", "search", "conditions", "interventions"].map((name) =>
    createRoute({
      getParentRoute: () => analysis,
      path: name,
      component: () => <p>The {name} section</p>,
    }),
  );
  const routeTree = root.addChildren([
    analysis.addChildren([
      createRoute({ getParentRoute: () => analysis, path: "/", component: LandscapeSection }),
      createRoute({ getParentRoute: () => analysis, path: "results", component: ResultsSection }),
      ...empty,
    ]),
    createRoute({ getParentRoute: () => root, path: "/trials", component: () => null }),
    createRoute({ getParentRoute: () => root, path: "/settings", component: () => null }),
  ]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
    parseSearch,
    stringifySearch,
  });
  renderWithProviders(<RouterProvider router={router} />);
  const nav = await screen.findByRole("navigation", { name: "Analysis sections" });
  return { router, nav };
}

describe("the analysis page", () => {
  it("opens on the landscape, with every section a tab", async () => {
    const { nav } = await show("/analysis");
    expect(
      within(nav)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual([
      "Landscape",
      "Results",
      "Trial linking",
      "Advanced search",
      "Conditions",
      "Interventions",
    ]);
    expect(within(nav).getByRole("link", { name: "Landscape" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByText(ANALYSIS_SECTIONS[0]?.description ?? "")).toBeInTheDocument();
    expect(await screen.findByText("No analyses yet")).toBeInTheDocument();
  });

  it("has a Results section for the results plugin's charts", async () => {
    const { nav } = await show("/analysis/results");
    expect(within(nav).getByRole("link", { name: "Results" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(await screen.findByText("No results analyses")).toBeInTheDocument();
  });

  it("keeps the filter from section to section", async () => {
    const { router, nav } = await show("/analysis?status=RECRUITING");
    expect(within(nav).getByRole("link", { name: "Conditions" })).toHaveAttribute(
      "href",
      "/analysis/conditions?status=RECRUITING",
    );
    await userEvent.click(within(nav).getByRole("link", { name: "Conditions" }));
    await screen.findByText("The conditions section");
    expect(router.state.location.href).toBe("/analysis/conditions?status=RECRUITING");
    expect(within(nav).getByRole("link", { name: "Conditions" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Landscape" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(await screen.findByText("1,234")).toBeInTheDocument();
  });

  it("carries only the filter, not a section's own params", async () => {
    const { nav } = await show("/analysis/search?status=RECRUITING&exclusion=warfarin&term=D1");
    expect(within(nav).getByRole("link", { name: "Conditions" })).toHaveAttribute(
      "href",
      "/analysis/conditions?status=RECRUITING",
    );
    expect(screen.getByRole("link", { name: /List these trials/ })).toHaveAttribute(
      "href",
      "/trials?status=RECRUITING",
    );
  });

  it("stays in its section when a filter chip is removed", async () => {
    const { router } = await show("/analysis/interventions?status=RECRUITING&phase=PHASE3");
    await userEvent.click(await screen.findByRole("button", { name: "Remove Status RECRUITING" }));
    await waitFor(() =>
      expect(router.state.location.href).toBe("/analysis/interventions?phase=PHASE3"),
    );
  });
});

describe("analysisSection", () => {
  it("finds the section at a path", () => {
    expect(analysisSection("/analysis").label).toBe("Landscape");
    expect(analysisSection("/analysis/").label).toBe("Landscape");
    expect(analysisSection("/analysis/linking").label).toBe("Trial linking");
    expect(analysisSection("/analysis/nowhere").label).toBe("Landscape");
  });
});
