import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ChartSpec } from "@/api/client";
import { mockApi } from "@/test/api";
import { renderWithProviders } from "@/test/render";
import { WIDGETS } from "@/widgets/registry";
import { WidgetCard } from "./widget-card";

function spec(overrides: Partial<ChartSpec>): ChartSpec {
  return {
    id: "chart",
    title: "A chart",
    widget: "bar",
    description: "",
    section: "",
    x: "label",
    y: "value",
    layout: { width: 2, height: 1, order: 0 },
    plugin: "charts",
    precomputed: true,
    ...overrides,
  };
}

function stats(chartId: string, rows: Record<string, unknown>[]) {
  return { chart_id: chartId, data_version: 1, filtered: false, rows };
}

describe("the widget registry", () => {
  it("has a widget for every type the API declares", () => {
    expect(Object.keys(WIDGETS).sort()).toEqual([
      "area",
      "bar",
      "line",
      "map",
      "pie",
      "stat",
      "table",
      "trends",
    ]);
  });

  it("shows a placeholder for a widget type it doesn't know, without fetching", async () => {
    const { requests } = mockApi({});
    renderWithProviders(
      <WidgetCard
        spec={spec({ id: "x", widget: "heatmap" as ChartSpec["widget"], plugin: "sample" })}
        filter={{}}
      />,
    );
    expect(screen.getByTestId("widget-placeholder")).toHaveTextContent(
      "No “heatmap” widget in this version",
    );
    expect(screen.getByTestId("widget")).toHaveAttribute("data-state", "unsupported");
    expect(requests).toHaveLength(0);
  });

  it("draws stat tiles from the spec's rows", async () => {
    mockApi({
      "/api/stats/totals": stats("totals", [
        { key: "trials", label: "Trials", value: 607349 },
        { key: "countries", label: "Countries", value: 226 },
      ]),
    });
    renderWithProviders(
      <WidgetCard
        spec={spec({ id: "totals", widget: "stat", layout: { width: 4, height: 1, order: 0 } })}
        filter={{}}
      />,
    );
    expect(await screen.findByText("607,349")).toBeInTheDocument();
    expect(screen.getByText("Countries")).toBeInTheDocument();
    expect(screen.getByTestId("widget")).toHaveAttribute("data-state", "ready");
  });

  it("asks for the chart under the page's filter", async () => {
    const { requests } = mockApi({
      "/api/stats/by_phase": stats("by_phase", [{ label: "Phase 2", value: 5 }]),
    });
    renderWithProviders(
      <WidgetCard
        spec={spec({ id: "by_phase" })}
        filter={{ status: ["RECRUITING"], q: "amyloid" }}
      />,
    );
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(new URL(requests[0]?.url ?? "").search).toBe("?status=RECRUITING&q=amyloid");
  });

  it("offers the rows as a table", async () => {
    mockApi({
      "/api/stats/by_phase": stats("by_phase", [
        { key: "PHASE2", label: "Phase 2", value: 65833 },
        { key: "PHASE3", label: "Phase 3", value: 42410 },
      ]),
    });
    renderWithProviders(
      <WidgetCard spec={spec({ id: "by_phase", title: "Trials by phase" })} filter={{}} />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Show as a table" }));
    const table = screen.getByRole("table");
    expect(within(table).getByText("Phase 3")).toBeInTheDocument();
    expect(within(table).getByText("42,410")).toBeInTheDocument();
  });

  it("says when a chart fails to load", async () => {
    mockApi({
      "/api/stats/broken": () => Response.json({ detail: "no chart 'broken'" }, { status: 404 }),
    });
    renderWithProviders(<WidgetCard spec={spec({ id: "broken" })} filter={{}} />);
    expect(await screen.findByText("no chart 'broken'")).toBeInTheDocument();
  });
});
