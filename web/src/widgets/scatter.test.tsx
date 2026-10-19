import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChartRow, ChartSpec } from "@/api/client";
import type { TrialFilter } from "@/lib/filters";
import { mockApi } from "@/test/api";
import { renderWithProviders } from "@/test/render";
import { buildDots, legendOf, postedSince, ScatterWidget } from "./scatter";
import { type Dots, frameFor, gridTicks, type Hit, nearestDot } from "./scatter-canvas";
import { FAINT, GHOST, GREY } from "./scatter3d-points";

// jsdom has no canvas: a plot that records what the widget asks of it.
const plots = vi.hoisted(() => ({
  made: [] as { dots: Dots | null; picked: Hit | null }[],
}));

vi.mock("./scatter-canvas", async (importOriginal) => {
  class FakeCanvas {
    dots: Dots | null = null;
    picked: Hit | null = null;
    constructor() {
      plots.made.push(this);
    }
    setDots(dots: Dots) {
      this.dots = dots;
    }
    setColors() {}
    resize() {}
    pick() {
      return this.picked;
    }
  }
  return { ...(await importOriginal<object>()), LandscapeCanvas: FakeCanvas };
});

const plot = () => {
  const made = plots.made.at(-1);
  if (!made) throw new Error("no plot");
  return made;
};

const SPEC: ChartSpec = {
  id: "research_clusters",
  title: "Clinical research landscape",
  widget: "scatter",
  description: "",
  section: "Research Intelligence",
  x: "x",
  y: "y",
  series: [],
  layout: { width: 4, height: 3, order: 210 },
  page: "dashboard",
  plugin: "insights",
  precomputed: true,
};

function show(rows: ChartRow[], filter: TrialFilter = {}) {
  const root = createRootRoute({
    component: () => <ScatterWidget spec={SPEC} rows={rows} height={520} filter={filter} />,
  });
  const routeTree = root.addChildren([
    createRoute({ getParentRoute: () => root, path: "/", component: () => null }),
    createRoute({
      getParentRoute: () => root,
      path: "/trials/$sourceId",
      component: () => null,
    }),
  ]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  return { ...renderWithProviders(<RouterProvider router={router} />), router };
}

const summary: ChartRow = {
  type: "summary",
  status: "ready",
  total_trials: 3,
  embedded_trials: 3,
  plotted_trials: 3,
  clusters: 1,
  noise_trials: 0,
  since: "2025-10-16",
  until: "2026-10-16",
  engine: "sentence-transformers",
  model: "sentence-transformers/all-MiniLM-L6-v2",
  dimensions: 384,
  windows: [
    { months: 3, since: "2026-07-16" },
    { months: 6, since: "2026-04-16" },
    { months: 12, since: "2025-10-16" },
  ],
};

const point = (id: number, cluster: number, label: string, size: number, color: number | null) => ({
  type: "point",
  x: id,
  y: id,
  cluster,
  cluster_label: label,
  cluster_size: size,
  color,
  title: `Trial ${id}`,
  source_id: `NCT0000000${id}`,
});

describe("the research cluster scatterplot", () => {
  beforeEach(() => {
    vi.stubGlobal("scrollTo", () => {}); // the router restores scroll; jsdom has none
    plots.made.length = 0;
  });

  it("explains how to generate missing embeddings", async () => {
    show([{ ...summary, status: "missing_embeddings", embedded_trials: 0 }]);

    expect(await screen.findByText("Embed the trials to build this map")).toBeInTheDocument();
    expect(screen.getByText(/tri-al embeddings generate/)).toBeInTheDocument();
  });

  it("colours only the largest clusters and says what the grey stands for", async () => {
    show([
      summary,
      point(1, 0, "Alzheimer Disease", 3, 0),
      point(2, 0, "Alzheimer Disease", 3, 0),
      point(3, 5, "Pain", 2, null),
      point(4, 6, "Sleep", 4, null),
      point(5, -1, "Unclustered", 7, null),
    ]);

    expect(await screen.findByTestId("landscape")).toHaveTextContent(
      "3 trials first posted Oct 16, 2025 – Oct 16, 2026",
    );
    expect(screen.getByText("384-dimensional vectors")).toBeInTheDocument();
    const legend = screen.getByRole("list", { name: "Cluster legend" });
    expect(legend).toHaveTextContent("Alzheimer Disease3");
    expect(legend).toHaveTextContent("2 smaller clusters · 6");
    expect(legend).toHaveTextContent("In no cluster · 7");
    expect(legend).not.toHaveTextContent("Pain");
    expect(legend).not.toHaveTextContent("Earlier in the year");
    // Trials in no cluster underneath, then the grey clusters, the coloured ones on top.
    expect([...(plot().dots?.slots ?? [])]).toEqual([FAINT, GREY, GREY, 0, 0]);
  });

  it("names the trial under the pointer and opens it on a click", async () => {
    const { router } = show([
      summary,
      point(1, 0, "Alzheimer Disease", 3, 0),
      point(2, -1, "Unclustered", 7, null),
    ]);
    const canvas = await screen.findByTestId("landscape-canvas");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    plot().picked = { index: 1, x: 40, y: 30 }; // drawn after the unclustered trial
    fireEvent.pointerMove(canvas, { clientX: 41, clientY: 30 });
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("Trial 1");
    expect(tooltip).toHaveTextContent("NCT00000001");
    expect(tooltip).toHaveTextContent("Alzheimer Disease3 trials");

    plot().picked = null;
    fireEvent.pointerMove(canvas, { clientX: 200, clientY: 200 });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.click(canvas);
    expect(router.state.location.pathname).toBe("/");

    plot().picked = { index: 1, x: 40, y: 30 };
    fireEvent.click(canvas);
    await waitFor(() => expect(router.state.location.pathname).toBe("/trials/NCT00000001"));
  });

  it("narrows to the last months, with the rest of the year behind", async () => {
    const { requests } = mockApi({
      "/api/stats/research_clusters": {
        chart_id: "research_clusters",
        data_version: 3,
        filtered: true,
        rows: [
          { ...summary, embedded_trials: 1, total_trials: 1 },
          point(2, 0, "Alzheimer Disease", 1, 0),
        ],
      },
    });
    show(
      [summary, point(1, 0, "Alzheimer Disease", 3, 0), point(2, 0, "Alzheimer Disease", 3, 0)],
      {
        conditions: ["Dementia"],
      },
    );
    const landscape = await screen.findByTestId("landscape");
    expect(requests).toHaveLength(0); // the whole map is already here

    await userEvent.click(within(landscape).getByRole("radio", { name: "3 months" }));

    await waitFor(() =>
      expect(landscape).toHaveTextContent("1 trial first posted Jul 16, 2026 – Oct 16, 2026"),
    );
    const url = new URL(requests[0]?.url ?? "");
    expect(url.searchParams.get("first_posted")).toBe("2026-07-16..");
    expect(url.searchParams.getAll("conditions")).toEqual(["Dementia"]);
    expect(screen.getByRole("list", { name: "Cluster legend" })).toHaveTextContent(
      "Earlier in the year",
    );
    // The year behind, faint and not pickable, then the window's trial.
    expect([...(plot().dots?.slots ?? [])]).toEqual([GHOST, GHOST, 0]);
  });
});

describe("the map's dots", () => {
  const at = (x: number, y: number, cluster: number, color: number | null) => ({
    ...point(x, cluster, "", 1, color),
    y,
  });

  it("puts the year behind a window first, and knows which trial each dot is", () => {
    const year = [at(0, 0, 0, 0), at(1, 1, 3, null)];
    const drawn = buildDots([at(1, 1, 3, null)], year);
    expect([...drawn.slots]).toEqual([GHOST, GHOST, GREY]);
    expect(drawn.trials.map((trial) => trial?.source_id ?? null)).toEqual([
      null,
      null,
      "NCT00000001",
    ]);
  });

  it("finds the dot on top under the pointer, or the nearest close by", () => {
    // Three dots on a 100 × 100 plot: two on the same spot, one apart, one behind (a ghost).
    const dots: Dots = {
      xs: Float64Array.from([0, 0, 10, 5]),
      ys: Float64Array.from([0, 0, 10, 5]),
      slots: Uint8Array.from([GREY, 0, 1, GHOST]),
    };
    const frame = frameFor(dots, 100, 100);
    const corner = nearestDot(dots, frame, frame.left, frame.bottom);
    expect(corner?.index).toBe(1); // drawn last of the two
    expect(corner).toMatchObject({ x: frame.left, y: frame.bottom });
    expect(nearestDot(dots, frame, frame.right - 6, frame.top)?.index).toBe(2);
    expect(nearestDot(dots, frame, frame.right - 20, frame.top)).toBeNull();
    // The ghost in the middle isn't a trial to name.
    expect(nearestDot(dots, frame, (frame.left + frame.right) / 2, 50)).toBeNull();
  });

  it("puts the grid where Recharts put it", () => {
    // Recharts' own output for these domains; the first two are the real map's extent.
    const close = (values: number[]) => values.map((value) => Number(value.toFixed(4)));
    expect(close(gridTicks(-11.3734, 22.4614))).toEqual([
      -11.3734, -2.3734, 6.6266, 15.6266, 22.4614,
    ]);
    expect(close(gridTicks(-3.0679, 17.9878))).toEqual([-3.0679, 2.9321, 8.9321, 14.9321, 17.9878]);
    expect(close(gridTicks(0, 0.37))).toEqual([0, 0.095, 0.19, 0.285, 0.37]);
    expect(close(gridTicks(-0.8, 140))).toEqual([-0.8, 39.2, 79.2, 119.2, 140]);
    expect(gridTicks(2, 2)).toEqual([2]);
  });
});

describe("a window's filter", () => {
  it("starts at the later of the window and the page's own range", () => {
    expect(postedSince({}, "2026-07-16")).toEqual({ first_posted: "2026-07-16.." });
    expect(postedSince({ first_posted: "2026-08..2026-09" }, "2026-07-16")).toEqual({
      first_posted: "2026-08..2026-09",
    });
    expect(
      postedSince({ first_posted: "..2026-09-01", status: ["RECRUITING"] }, "2026-07-16"),
    ).toEqual({
      first_posted: "2026-07-16..2026-09-01",
      status: ["RECRUITING"],
    });
  });
});

describe("the map's legend", () => {
  it("lists coloured clusters in colour order", () => {
    const base = { x: 0, y: 0, title: "", source_id: "" };
    const { colored, other, unclustered } = legendOf([
      { ...base, cluster: 4, cluster_label: "B", cluster_size: 10, color: 1 },
      { ...base, cluster: 2, cluster_label: "A", cluster_size: 20, color: 0 },
      { ...base, cluster: 9, cluster_label: "C", cluster_size: 5, color: null },
    ]);
    expect(colored.map((item) => item.label)).toEqual(["A", "B"]);
    expect(other).toEqual({ clusters: 1, trials: 5 });
    expect(unclustered).toBe(0);
  });
});
