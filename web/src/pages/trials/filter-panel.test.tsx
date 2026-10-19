import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { META, mockApi } from "@/test/api";
import { renderWithProviders } from "@/test/render";
import { FilterPanel } from "./filter-panel";

const DASHBOARD = {
  data_version: 3,
  charts: [],
  facets: [
    { field: "status", title: "Status", plugin: "core" },
    { field: "phase", title: "Phase", plugin: "core" },
    { field: "has_results", title: "Results", plugin: "core" },
  ],
};

const FACETS = {
  data_version: 3,
  total: 64802,
  facets: {
    status: [
      { value: "COMPLETED", label: "Completed", count: 332122 },
      { value: "RECRUITING", label: "Recruiting", count: 64802 },
    ],
    phase: [
      { value: "PHASE2", label: "Phase 2", count: 9000 },
      { value: null, label: "Not given", count: 1200 },
    ],
    has_results: [
      { value: "false", label: "No results", count: 60000 },
      { value: "true", label: "Has results", count: 4802 },
    ],
  },
};

function setup(filter = {}) {
  const onChange = vi.fn();
  const api = mockApi({ "/api/meta": META, "/api/dashboard": DASHBOARD, "/api/facets": FACETS });
  renderWithProviders(<FilterPanel filter={filter} onChange={onChange} />);
  return { onChange, ...api };
}

describe("the filter panel", () => {
  it("lists each facet's options with their counts", async () => {
    setup();
    expect(await screen.findByText("Recruiting")).toBeInTheDocument();
    expect(screen.getByText("332,122")).toBeInTheDocument();
  });

  it("adds an option to the filter", async () => {
    const { onChange } = setup({ status: ["COMPLETED"] });
    await userEvent.click(await screen.findByLabelText(/Recruiting/));
    expect(onChange).toHaveBeenCalledWith({ status: ["COMPLETED", "RECRUITING"] });
  });

  it("asks for counts under the current filter", async () => {
    const { requests } = setup({ phase: ["PHASE2"] });
    await screen.findByText("Recruiting");
    const facets = requests.find((request) => request.url.includes("/api/facets"));
    expect(new URL(facets?.url ?? "").searchParams.getAll("phase")).toEqual(["PHASE2"]);
  });

  it("counts trials without a value but can't filter on them", async () => {
    setup();
    expect(await screen.findByLabelText(/Not given/)).toBeDisabled();
  });

  it("treats results as yes or no", async () => {
    const { onChange } = setup({ has_results: false });
    await userEvent.click(await screen.findByLabelText(/Has results/));
    expect(onChange).toHaveBeenCalledWith({ has_results: true });
  });

  it("filters by words", async () => {
    const { onChange } = setup();
    await userEvent.type(screen.getByLabelText("Filter by words or trial IDs"), "amyloid{Enter}");
    expect(onChange).toHaveBeenCalledWith({ q: "amyloid" });
  });
});
