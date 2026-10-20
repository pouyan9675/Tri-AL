import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChartRow, ChartSpec } from "@/api/client";
import type { TrialFilter } from "@/lib/filters";
import { parseSearch, stringifySearch } from "@/lib/search-params";
import { renderWithProviders } from "@/test/render";
import { formatChance, formatGrowth, TrendsWidget } from "./trends";

const SPEC: ChartSpec = {
  id: "emerging_trends",
  title: "Emerging research trends",
  widget: "trends",
  description: "",
  section: "Research Intelligence",
  x: "label",
  y: "value",
  series: [],
  format: "number",
  layout: { width: 4, height: 2, order: 200 },
  page: "dashboard",
  plugin: "insights",
  precomputed: true,
};

function windowRow(months: number, since: string, baselineTrials = 46445): ChartRow {
  return {
    type: "window",
    window: `${months}m`,
    label: `${months} months`,
    since,
    until: "2026-10-16",
    baseline_since: since.replace(/^2026/, "2025"),
    trials: 26479,
    baseline_trials: baselineTrials,
  };
}

function item(overrides: Record<string, unknown>): ChartRow {
  return {
    type: "item",
    window: "6m",
    group: "Conditions",
    key: "D002836",
    label: "Hemophilia B",
    value: 11,
    baseline: 3,
    expected: 1.7,
    growth: 2.74,
    raw_growth: 6.43,
    p: 0.0016,
    q: 0.2,
    confidence: "medium",
    tested: 1492,
    new: false,
    sponsors: 9,
    series: [0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 2, 1, 3, 2, 1, 2],
    recent: 6,
    filter: { mesh: ["D002836"], first_posted: "2026-04-17.." },
    ...overrides,
  };
}

const ROWS: ChartRow[] = [
  windowRow(3, "2026-07-17"),
  item({
    window: "3m",
    key: "D010149",
    label: "Pain, Procedural",
    growth: 2.34,
    raw_growth: 2.61,
    confidence: "high",
    q: 0.001,
  }),
  windowRow(6, "2026-04-17"),
  item({}),
  item({
    key: "C000000001",
    label: "Novel Syndrome",
    value: 3,
    baseline: 0,
    growth: 1.8,
    raw_growth: null,
    p: 0.048,
    q: 0.9,
    confidence: "low",
    new: true,
  }),
  item({
    group: "Interventions",
    key: "D065693",
    label: "Palonosetron",
    growth: 3.0,
    raw_growth: 15.79,
    confidence: "low",
  }),
];

async function show(rows: ChartRow[], filter: TrialFilter = {}) {
  const root = createRootRoute({
    component: () => <TrendsWidget spec={SPEC} rows={rows} height={520} filter={filter} />,
  });
  const routeTree = root.addChildren([
    createRoute({ getParentRoute: () => root, path: "/", component: () => null }),
    createRoute({ getParentRoute: () => root, path: "/trials", component: () => null }),
  ]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/"] }),
    parseSearch,
    stringifySearch,
  });
  renderWithProviders(<RouterProvider router={router} />);
  return await screen.findByTestId("trends");
}

describe("the trends widget", () => {
  beforeEach(() => {
    vi.stubGlobal("scrollTo", () => {}); // the router restores scroll; jsdom has none
  });

  it("shows the longest window first, a column per group", async () => {
    const widget = await show(ROWS);

    expect(widget).toHaveTextContent("26,479 trials first posted Apr 17 – Oct 16, 2026");
    expect(widget).toHaveTextContent("46,445 in the 12 months before");
    const conditions = within(widget).getByRole("region", { name: "Conditions" });
    const entries = within(conditions).getAllByTestId("trend");
    expect(entries.map((entry) => entry.textContent)).toEqual([
      expect.stringContaining("Hemophilia B"),
      expect.stringContaining("Novel Syndrome"),
    ]);
    // The adjusted growth, not the raw 6.4×.
    expect(entries[0]).toHaveTextContent("2.7×");
    expect(entries[0]).not.toHaveTextContent("6.4×");
    expect(entries[0]).toHaveAttribute("data-confidence", "medium");
    expect(within(entries[0] as HTMLElement).getByRole("img")).toHaveAccessibleName(
      "Medium confidence",
    );
    expect(entries[1]).toHaveAttribute("data-confidence", "low");
    expect(within(entries[1] as HTMLElement).getByText("New")).toBeInTheDocument();
    expect(entries[1]).toHaveTextContent("1.8×");
    const interventions = within(widget).getByRole("region", { name: "Interventions" });
    expect(interventions).toHaveTextContent("Palonosetron");
    expect(interventions).toHaveTextContent("3.0×");
  });

  it("switches windows", async () => {
    const widget = await show(ROWS);

    await userEvent.click(within(widget).getByRole("radio", { name: "3 months" }));

    expect(widget).toHaveTextContent("trials first posted Jul 17 – Oct 16, 2026");
    const conditions = within(widget).getByRole("region", { name: "Conditions" });
    expect(within(conditions).getAllByTestId("trend")).toHaveLength(1);
    expect(conditions).toHaveTextContent("Pain, Procedural");
    expect(within(widget).getByRole("region", { name: "Interventions" })).toHaveTextContent(
      "Nothing rising in this window.",
    );
  });

  it("links each entry to its trials, under the page's filter", async () => {
    const widget = await show(ROWS, { conditions: ["Alzheimer Disease"], mesh: ["D000544"] });

    const [first] = within(widget).getAllByTestId("trend");
    const url = new URL(first?.getAttribute("href") ?? "", "http://localhost");
    expect(url.pathname).toBe("/trials");
    expect(url.searchParams.getAll("conditions")).toEqual(["Alzheimer Disease"]);
    // The entry's own fields take the place of the page's.
    expect(url.searchParams.getAll("mesh")).toEqual(["D002836"]);
    expect(url.searchParams.get("first_posted")).toBe("2026-04-17..");
  });

  it("explains an entry on hover", async () => {
    const widget = await show(ROWS);

    await userEvent.hover(within(widget).getAllByTestId("trend")[0] as HTMLElement);

    const tip = await screen.findByRole("tooltip");
    expect(tip).toHaveTextContent("11 trials since Apr 17, from 9 lead sponsors");
    expect(tip).toHaveTextContent("3 in the 12 months before (at the usual share, 1.7 now)");
    expect(tip).toHaveTextContent(
      "2.7× its usual share of new trials (6.4× before adjusting for the small count).",
    );
    expect(tip).toHaveTextContent(
      "Medium confidence. The chance of a rise this large if nothing had changed: p = 0.0016; " +
        "corrected for the 1,492 conditions tested: q = 0.2.",
    );
  });

  it("says when there is nothing to compare with", async () => {
    const widget = await show([windowRow(6, "2026-04-17", 0)]);

    expect(widget).toHaveTextContent("No trials under this filter in the months before");
    expect(within(widget).queryAllByTestId("trend")).toHaveLength(0);
  });

  it("says when nothing is rising", async () => {
    const widget = await show([windowRow(3, "2026-07-17"), windowRow(6, "2026-04-17")]);

    expect(widget).toHaveTextContent("Nothing is taking a growing share of new trials.");
  });

  it("formats growth and chances", () => {
    expect(formatGrowth(2.61)).toBe("2.6×");
    expect(formatGrowth(15.79)).toBe("16×");
    expect(formatChance(0.0016)).toBe("0.0016");
    expect(formatChance(0.2)).toBe("0.2");
    expect(formatChance(1)).toBe("1");
    expect(formatChance(0.00001)).toBe("< 0.0001");
  });
});
