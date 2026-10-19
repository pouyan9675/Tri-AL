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
import type { Schemas, TrialSummary } from "@/api/client";
import { parseAdvancedSearch } from "@/lib/advanced";
import { parseFilter } from "@/lib/filters";
import { parseSearch, stringifySearch } from "@/lib/search-params";
import { META, mockApi } from "@/test/api";
import { renderWithProviders } from "@/test/render";
import { AdvancedSearchSection } from ".";

type Result = Schemas["AdvancedSearchOut"];

const LABELS = {
  ...META.labels,
  allocation: { RANDOMIZED: "Randomized", NON_RANDOMIZED: "Non-randomized" },
  masking: { NONE: "Open label", DOUBLE: "Double-blind" },
  intervention_model: { PARALLEL: "Parallel assignment" },
  primary_purpose: { TREATMENT: "Treatment" },
};

function summary(id: number, title: string): TrialSummary {
  return {
    id,
    source: "ctgov",
    source_id: `NCT0000000${id}`,
    title,
    status: "RECRUITING",
    phase: "PHASE3",
    study_type: "INTERVENTIONAL",
    start_date: "2023-01-01",
    completion_date: null,
    last_update: null,
    enrollment: 1800,
    has_results: false,
    num_sites: 2,
    lead_sponsor: "Eisai",
    conditions: ["Alzheimer Disease"],
  };
}

function result(url: URL): Result {
  const offset = Number(url.searchParams.get("offset") ?? 0);
  const near = url.searchParams.has("near");
  const page = (id: number, title: string) => ({
    trial: summary(id, title),
    score: near ? null : 12.5,
    snippets: [
      {
        field: "exclusion" as const,
        parts: [
          { text: "Use of ", match: false },
          { text: "warfarin", match: true },
        ],
      },
    ],
    nearest: near
      ? {
          km: 3.2,
          facility: "Mass General",
          city: "Boston",
          state: "Massachusetts",
          country: "US",
          sites: 2,
        }
      : null,
  });
  return {
    data_version: 3,
    total: 2,
    sort: near ? "distance" : "relevance",
    ranked: near ? null : 2,
    sections: { candidates: 4512, checked: 2000 },
    read: [
      { field: "condition", all: [["alzheimer"]], none: [] },
      { field: "exclusion", all: [["warfarin", "anticoag*"]], none: ["aspirin"] },
    ],
    offset,
    next_offset: offset === 0 ? 1 : null,
    items: [offset === 0 ? page(1, "Lecanemab in early AD") : page(2, "Donanemab follow-on")],
  };
}

async function show(path: string) {
  const { requests } = mockApi({
    "/api/meta": { ...META, labels: LABELS },
    "/api/search/advanced": (_request: Request, url: URL) => result(url),
    "/api/places": {
      data_version: 3,
      places: [
        {
          city: "Boston",
          state: "Massachusetts",
          country: "US",
          country_name: "United States",
          lat: 42.3601,
          lon: -71.0589,
          sites: 27487,
        },
      ],
    },
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
        path: "search",
        validateSearch: parseAdvancedSearch,
        component: AdvancedSearchSection,
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
  await screen.findByTestId("advanced-search");
  const searches = () =>
    requests
      .filter((request) => request.url.includes("/api/search/advanced"))
      .map((request) => new URL(request.url).searchParams);
  return { router, searches };
}

describe("advanced search", () => {
  it("starts with examples, and searches what's typed within the filter", async () => {
    const { router, searches } = await show("/analysis/search?status=RECRUITING");
    expect(screen.getByText("Search by field")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "ADAS-Cog as a primary outcome" }).getAttribute("href"),
    ).toBe("/analysis/search?status=RECRUITING&primary_outcome=ADAS-Cog");
    expect(searches()).toEqual([]);

    await userEvent.type(screen.getByRole("textbox", { name: "Anywhere" }), "amyloid PET");
    await userEvent.type(screen.getByRole("textbox", { name: "Age in years" }), "70");
    await userEvent.click(
      within(screen.getByRole("radiogroup", { name: "Sex" })).getByRole("radio", {
        name: "Female",
      }),
    );
    const masking = screen.getByRole("toolbar", { name: "Masking" });
    await userEvent.click(within(masking).getByRole("button", { name: "Double-blind" }));
    expect(within(masking).getByRole("button", { name: "Double-blind" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("Lecanemab in early AD")).toBeInTheDocument();
    expect(router.state.location.href).toBe(
      "/analysis/search?status=RECRUITING&text=amyloid+PET&sex=FEMALE&masking=DOUBLE&age=70",
    );
    const sent = searches().at(-1);
    expect(sent?.getAll("status")).toEqual(["RECRUITING"]);
    expect(sent?.get("text")).toBe("amyloid PET");
    expect(sent?.get("age")).toBe("70");
    expect(sent?.get("sex")).toBe("FEMALE");
    expect(sent?.getAll("masking")).toEqual(["DOUBLE"]);
    expect(sent?.get("offset")).toBe("0");
  });

  it("shows how the words were read, where they are, and more on request", async () => {
    const { searches } = await show(
      "/analysis/search?condition=alzheimer&exclusion=warfarin+OR+anticoag*+-aspirin",
    );
    const results = await screen.findByTestId("advanced-results");
    expect(within(results).getByRole("heading", { name: "2 trials" })).toBeInTheDocument();
    const read = within(results).getByLabelText("How the words were read");
    expect(read).toHaveTextContent(
      "Condition:alzheimerExclusion criteria:warfarinoranticoag*but notaspirin",
    );
    expect(within(results).getByText(/checked in the newest 2,000 of 4,512/)).toBeVisible();
    const marks = within(results)
      .getAllByText("warfarin")
      .filter((element) => element.tagName === "MARK");
    expect(marks).toHaveLength(1);
    // The form shows the search it ran.
    expect(screen.getByRole("textbox", { name: "Exclusion criteria" })).toHaveValue(
      "warfarin OR anticoag* -aspirin",
    );

    await userEvent.click(within(results).getByRole("button", { name: "Show 1 more" }));
    expect(await within(results).findByText("Donanemab follow-on")).toBeInTheDocument();
    expect(searches().at(-1)?.get("offset")).toBe("1");
    expect(within(results).queryByRole("button", { name: /more/ })).not.toBeInTheDocument();
  });

  it("finds a place, and shows each trial's nearest site", async () => {
    const { router } = await show("/analysis/search");
    await userEvent.click(screen.getByRole("combobox", { name: "Place" }));
    await userEvent.type(screen.getByPlaceholderText(/A city/), "bos");
    await userEvent.click(await screen.findByText("Boston, Massachusetts, United States"));
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText(/3 km: Boston, Massachusetts/)).toBeInTheDocument();
    expect(screen.getAllByText(/2 sites within 50 km/)).toHaveLength(1);
    expect(router.state.location.href).toBe(
      "/analysis/search?near=42.3601%2C-71.0589&place=Boston%2C+Massachusetts%2C+United+States&within=50",
    );
  });

  it("won't search an age it can't read", async () => {
    await show("/analysis/search");
    await userEvent.type(screen.getByRole("textbox", { name: "Age in years" }), "old");
    expect(screen.getByText(/An age \(70\) or a range/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Search" })).toBeDisabled();
  });

  it("clears the search but keeps the filter", async () => {
    const { router } = await show("/analysis/search?phase=PHASE3&title=asthma&sort=-start_date");
    await screen.findByTestId("advanced-results");
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(router.state.location.href).toBe("/analysis/search?phase=PHASE3"));
    expect(screen.getByText("Search by field")).toBeInTheDocument();
  });
});
