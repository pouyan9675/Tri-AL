import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ChartSpec } from "@/api/client";
import { renderWithProviders } from "@/test/render";
import { ForestWidget, formatRatio, scale } from "./forest";

const spec: ChartSpec = {
  id: "signals",
  title: "Adverse events more common than on placebo",
  widget: "forest",
  description: "",
  section: "",
  x: "label",
  y: "ratio",
  series: [
    { key: "trials", label: "Trials", format: null },
    { key: "active", label: "Active arms", format: "percent" },
  ],
  format: "number",
  layout: { width: 4, height: 2, order: 0 },
  page: "analysis",
  plugin: "results",
  precomputed: true,
};

describe("the forest widget", () => {
  it("lists each estimate with its interval and columns", () => {
    const rows = [
      {
        label: "Amyloid related imaging abnormality",
        detail: "Not serious",
        ratio: 5.2,
        low: 3.1,
        high: 8.7,
        trials: 12,
        active: 0.124,
      },
      {
        label: "Headache",
        detail: "Not serious",
        ratio: 1.21,
        low: 1.05,
        high: 1.4,
        trials: 40,
        active: 0.08,
      },
    ];
    renderWithProviders(<ForestWidget spec={spec} rows={rows} height={520} />);

    const lines = screen.getAllByTestId("forest-row");
    expect(lines).toHaveLength(2);
    expect(within(lines[0] as HTMLElement).getByText("5.20")).toBeInTheDocument();
    expect(within(lines[0] as HTMLElement).getByText("(3.10–8.70)")).toBeInTheDocument();
    expect(within(lines[0] as HTMLElement).getByText("12.4%")).toBeInTheDocument();
    expect(within(lines[1] as HTMLElement).getByText("Headache")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Active arms" })).toBeInTheDocument();
  });

  it("places values on a log scale", () => {
    const x = scale(0.1, 10);
    expect(x(1)).toBeCloseTo(50);
    expect(x(10)).toBeCloseTo(100);
    expect(x(1000)).toBe(100);
    expect(formatRatio(1.234)).toBe("1.23");
    expect(formatRatio(23.4)).toBe("23.4");
    expect(formatRatio(234.5)).toBe("235");
  });
});
