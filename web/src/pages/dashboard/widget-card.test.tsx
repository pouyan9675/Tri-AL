import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
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
    series: [],
    format: "number",
    layout: { width: 2, height: 1, order: 0 },
    page: "dashboard",
    plugin: "charts",
    precomputed: true,
    ...overrides,
  };
}

function stats(chartId: string, rows: Record<string, unknown>[]) {
  return { chart_id: chartId, data_version: 1, filtered: false, rows };
}

describe("the widget registry", () => {
  afterEach(() => vi.restoreAllMocks());

  it("has a widget for every type the API declares", () => {
    expect(Object.keys(WIDGETS).sort()).toEqual([
      "area",
      "bar",
      "forest",
      "line",
      "map",
      "pie",
      "scatter",
      "scatter3d",
      "stacked",
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

  it("draws several series with a legend, and a column for each in the table", async () => {
    // Recharts draws nothing at jsdom's size of zero.
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(
      DOMRect.fromRect({ width: 800, height: 260 }),
    );
    mockApi({
      "/api/stats/per_day": stats("per_day", [
        { date: "2026-10-15", new: 210, updated: 1180 },
        { date: "2026-10-16", new: 189, updated: 1593 },
      ]),
    });
    const series = [
      { key: "new", label: "New", format: null },
      { key: "updated", label: "Updated", format: null },
    ];
    renderWithProviders(
      <WidgetCard spec={spec({ id: "per_day", widget: "area", x: "date", series })} filter={{}} />,
    );
    const widget = await screen.findByTestId("widget");
    await waitFor(() => expect(widget).toHaveAttribute("data-state", "ready"));
    const legend = widget.querySelector(".recharts-legend-wrapper");
    expect(legend).toHaveTextContent(/^NewUpdated$/);

    await userEvent.click(screen.getByRole("button", { name: "Show as a table" }));
    const table = screen.getByRole("table");
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent);
    expect(headers).toEqual(["Date", "New", "Updated"]);
    expect(within(table).getByText("1,593")).toBeInTheDocument();
  });

  it("says when a chart fails to load", async () => {
    mockApi({
      "/api/stats/broken": () => Response.json({ detail: "no chart 'broken'" }, { status: 404 }),
    });
    renderWithProviders(<WidgetCard spec={spec({ id: "broken" })} filter={{}} />);
    expect(await screen.findByText("no chart 'broken'")).toBeInTheDocument();
  });

  it("says when there's nothing to show", async () => {
    mockApi({ "/api/stats/empty": stats("empty", []) });
    renderWithProviders(<WidgetCard spec={spec({ id: "empty" })} filter={{}} />);
    expect(await screen.findByTestId("widget-empty")).toHaveTextContent("Nothing to show");
    expect(screen.queryByRole("button", { name: "Show as a table" })).not.toBeInTheDocument();
  });
});

describe("number formats", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reads percent tiles and leaves missing ones blank", async () => {
    mockApi({
      "/api/stats/people": stats("people", [
        { key: "participants", label: "Participants", value: 12737055 },
        { key: "women", label: "Women", value: 0.532, format: "percent" },
        { key: "age", label: "Mean age", value: null },
      ]),
    });
    renderWithProviders(
      <WidgetCard
        spec={spec({ id: "people", widget: "stat", layout: { width: 4, height: 1, order: 0 } })}
        filter={{}}
      />,
    );
    expect(await screen.findByText("12,737,055")).toBeInTheDocument();
    expect(screen.getByText("53.2%")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("draws bars side by side, each series in its format", async () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(
      DOMRect.fromRect({ width: 800, height: 260 }),
    );
    mockApi({
      "/api/stats/race": stats("race", [
        { key: "white", label: "White", participants: 0.61, average: 0.7 },
        { key: "black", label: "Black or African American", participants: 0.217, average: 0.1 },
      ]),
    });
    const series = [
      { key: "participants", label: "Share of participants", format: null },
      { key: "average", label: "In the average trial", format: null },
    ];
    renderWithProviders(
      <WidgetCard spec={spec({ id: "race", format: "percent", series })} filter={{}} />,
    );
    const widget = await screen.findByTestId("widget");
    await waitFor(() => expect(widget).toHaveAttribute("data-state", "ready"));
    expect(widget.querySelector(".recharts-legend-wrapper")).toHaveTextContent(
      /^Share of participantsIn the average trial$/,
    );

    await userEvent.click(screen.getByRole("button", { name: "Show as a table" }));
    const table = screen.getByRole("table");
    expect(within(table).getByText("61%")).toBeInTheDocument();
    expect(within(table).getByText("21.7%")).toBeInTheDocument();
  });

  it("formats a table's number columns by their series", async () => {
    mockApi({
      "/api/stats/events": stats("events", [
        { event: "Pneumonia", organ: "Infections", trials: 1234, rate: 0.0123 },
      ]),
    });
    const series = [
      { key: "trials", label: "Trials", format: null },
      { key: "rate", label: "Share of participants", format: "percent" as const },
    ];
    renderWithProviders(
      <WidgetCard spec={spec({ id: "events", widget: "table", x: "event", series })} filter={{}} />,
    );
    expect(await screen.findByText("1,234")).toBeInTheDocument();
    expect(screen.getByText("1.2%")).toBeInTheDocument();
    expect(screen.getByText("Infections")).toBeInTheDocument();
  });
});
