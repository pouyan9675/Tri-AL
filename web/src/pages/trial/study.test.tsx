import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TrialDetail } from "@/api/client";
import { parseSearch, stringifySearch } from "@/lib/search-params";
import { META, mockApi } from "@/test/api";
import { renderWithProviders } from "@/test/render";
import { TRIAL } from "@/test/trial";
import { OverviewTab } from "./sections";

const LABELS = {
  ...META.labels,
  arm_type: {
    EXPERIMENTAL: "Experimental",
    PLACEBO_COMPARATOR: "Placebo comparator",
    NO_INTERVENTION: "No intervention",
  },
  allocation: { RANDOMIZED: "Randomized" },
  intervention_model: { PARALLEL: "Parallel assignment" },
  masking: { QUADRUPLE: "Quadruple-blind" },
  masked_role: { PARTICIPANT: "Participant", INVESTIGATOR: "Investigator" },
  primary_purpose: { TREATMENT: "Treatment" },
};

async function show(trial: TrialDetail) {
  mockApi({ "/api/meta": { ...META, labels: LABELS } });
  const root = createRootRoute({ component: () => <OverviewTab trial={trial} /> });
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
  await screen.findByText("Tested with");
}

describe("the overview", () => {
  it("starts with what's studied: conditions, interventions and design", async () => {
    await show(TRIAL);

    const [condition] = screen.getAllByRole("link", { name: "Alzheimer Disease" });
    expect(condition?.getAttribute("href")).toBe("/trials?conditions=Alzheimer+Disease");
    expect(screen.getAllByRole("link", { name: "Donanemab" })[0]?.getAttribute("href")).toBe(
      "/trials?interventions=Donanemab",
    );
    expect(screen.getByText("amyloid · tau")).toBeTruthy();
    expect(await screen.findAllByText("Randomized")).not.toHaveLength(0);
    expect(
      screen.getAllByText("Quadruple-blind")[0]?.closest("[title]")?.getAttribute("title"),
    ).toBe("Masked: Participant, Investigator");
  });

  it("shows who gets what, experimental arms first", async () => {
    await show(TRIAL);

    const arms = screen.getAllByTestId("arm");
    expect(arms.map((arm) => within(arm).getByRole("heading").textContent)).toEqual([
      "Donanemab",
      "Placebo",
      "Follow-up",
    ]);
    const [first, second, third] = arms;
    expect(within(first as HTMLElement).getByText("Experimental")).toBeTruthy();
    expect(within(first as HTMLElement).getByRole("link", { name: "Donanemab" })).toBeTruthy();
    expect(within(second as HTMLElement).getByRole("link", { name: "Placebo" })).toBeTruthy();
    expect(within(third as HTMLElement).queryAllByRole("link")).toHaveLength(0);
  });

  it("lists each intervention with its description and arms", async () => {
    await show(TRIAL);

    expect(screen.getByText("Administered IV every 4 weeks")).toBeTruthy();
    expect(screen.getByText("Also known as LY3002813")).toBeTruthy();
    expect(screen.getAllByText("Donanemab", { selector: "span" })).not.toHaveLength(0);
    expect(screen.getAllByText(/Given in:/).map((line) => line.textContent)).toEqual([
      "Given in: Donanemab",
      "Given in: Placebo",
    ]);
  });

  it("has no arms section for a trial without arms", async () => {
    await show({ ...TRIAL, arms: [], allocation: null, masking: null, masked_roles: [] });

    expect(screen.queryByText("Arms: who gets what")).toBeNull();
    expect(screen.queryAllByTestId("arm")).toHaveLength(0);
    expect(screen.getByText("Interventions")).toBeTruthy();
  });
});
