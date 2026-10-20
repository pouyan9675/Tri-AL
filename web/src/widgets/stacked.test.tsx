import { waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChartSpec } from "@/api/client";
import { renderWithProviders } from "@/test/render";
import { StackedWidget, stack } from "./stacked";

const spec: ChartSpec = {
  id: "reporting",
  title: "How trials report race",
  widget: "stacked",
  description: "",
  section: "",
  x: "year",
  y: "value",
  series: [
    { key: "standard", label: "Standard categories", format: null },
    { key: "none", label: "Not reported", format: null },
  ],
  format: "number",
  layout: { width: 4, height: 1, order: 0 },
  page: "analysis",
  plugin: "results",
  precomputed: true,
};

describe("the stacked widget", () => {
  afterEach(() => vi.restoreAllMocks());

  it("splits each bar into its parts' shares, with a legend", async () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(
      DOMRect.fromRect({ width: 800, height: 260 }),
    );
    const rows = [
      { year: "2016", standard: 25, none: 75 },
      { year: "2025", standard: 99, none: 1 },
    ];
    const { container } = renderWithProviders(
      <StackedWidget spec={spec} rows={rows} height={260} />,
    );
    await waitFor(() =>
      expect(container.querySelector(".recharts-legend-wrapper")).toHaveTextContent(
        /^Standard categoriesNot reported$/,
      ),
    );
  });

  it("turns each row into its parts' shares", () => {
    const { data } = stack(spec, [
      { year: "2016", standard: 25, none: 75 },
      { year: "2017", standard: 0, none: 0 },
    ]);
    expect(data[0]).toMatchObject({ label: "2016", total: 100, part0: 0.25, part1: 0.75 });
    expect(data[1]).toMatchObject({ total: 0, part0: 0, part1: 0 });
  });
});
