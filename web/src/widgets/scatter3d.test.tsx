import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChartRow, ChartSpec } from "@/api/client";
import type { TrialFilter } from "@/lib/filters";
import { mockApi } from "@/test/api";
import { renderWithProviders } from "@/test/render";
import Scatter3DWidget, { buildCloud, parseLandscape } from "./scatter3d";
import { type Cloud, FAINT, GHOST, GREY } from "./scatter3d-points";

// jsdom has no WebGL: a scene that records what the widget asks of it.
const scenes = vi.hoisted(() => ({
  made: [] as {
    cloud: Cloud | null;
    highlight: number | null;
    marked: number | null;
    autoRotate: boolean;
    picked: number | null;
    onFrame: () => void;
    resetView: () => void;
  }[],
  fail: false,
}));

vi.mock("./scatter3d-scene", () => {
  class FakeScene {
    cloud: Cloud | null = null;
    highlight: number | null = null;
    marked: number | null = null;
    autoRotate = false;
    picked: number | null = null;
    onFrame = () => {};
    onInteract = () => {};
    resetView = vi.fn();
    constructor() {
      if (scenes.fail) throw new Error("Error creating WebGL context.");
      scenes.made.push(this);
    }
    setCloud(cloud: Cloud) {
      this.cloud = cloud;
    }
    setPalette() {}
    setHighlight(cluster: number | null) {
      this.highlight = cluster;
    }
    setMarked(index: number | null) {
      this.marked = index;
    }
    setAutoRotate(on: boolean) {
      this.autoRotate = on;
    }
    resize() {}
    start() {}
    stop() {}
    pick() {
      return this.picked;
    }
    dispose() {}
  }
  return { LandscapeScene: FakeScene };
});

const SPEC: ChartSpec = {
  id: "research_landscape_3d",
  title: "Research landscape in 3D",
  widget: "scatter3d",
  description: "",
  section: "",
  x: "x",
  y: "y",
  series: [],
  layout: { width: 4, height: 3, order: 100 },
  page: "analysis",
  plugin: "insights",
  precomputed: true,
};

const summary = (overrides: Partial<Record<string, unknown>> = {}): ChartRow => ({
  type: "summary",
  status: "ready",
  windows: [],
  total_trials: 4,
  embedded_trials: 4,
  plotted_trials: 4,
  clusters: 2,
  noise_trials: 1,
  since: "2025-10-16",
  until: "2026-10-16",
  model: "sentence-transformers/all-MiniLM-L6-v2",
  dimensions: 384,
  ...overrides,
});

const point = (source_id: string, cluster: number, x = 0): ChartRow => ({
  type: "point",
  x,
  y: 0,
  z: 0,
  cluster,
  title: `Trial ${source_id}`,
  source_id,
});

const ROWS: ChartRow[] = [
  summary(),
  { type: "cluster", cluster: 4, label: "Alzheimer Disease", size: 2, color: 0 },
  { type: "cluster", cluster: 9, label: "Pain", size: 1, color: null },
  { type: "cluster", cluster: -1, label: "Unclustered", size: 1, color: null },
  point("NCT00000001", 4, 0.1),
  point("NCT00000002", -1, 0.2),
  point("NCT00000003", 9, 0.3),
  point("NCT00000004", 4, 0.4),
];

function show(rows: ChartRow[], filter: TrialFilter = {}) {
  const root = createRootRoute({
    component: () => <Scatter3DWidget spec={SPEC} rows={rows} height={600} filter={filter} />,
  });
  const routeTree = root.addChildren([
    createRoute({ getParentRoute: () => root, path: "/", component: () => null }),
    createRoute({ getParentRoute: () => root, path: "/trials/$sourceId", component: () => null }),
  ]);
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  return renderWithProviders(<RouterProvider router={router} />);
}

const scene = () => {
  const made = scenes.made.at(-1);
  if (!made) throw new Error("no scene");
  return made;
};

beforeEach(() => {
  scenes.made.length = 0;
  scenes.fail = false;
});

describe("the points", () => {
  it("reads the summary, clusters and points", () => {
    const landscape = parseLandscape(ROWS);
    expect(landscape.summary?.status).toBe("ready");
    expect(landscape.clusters.map((c) => c.label)).toEqual([
      "Alzheimer Disease",
      "Pain",
      "Unclustered",
    ]);
    expect(landscape.points).toHaveLength(4);
  });

  it("draws no cluster first, then grey, then the coloured clusters on top", () => {
    const { clusters, points } = parseLandscape(ROWS);
    const drawn = buildCloud(points, clusters);
    expect(Array.from(drawn.cloud.slots)).toEqual([FAINT, GREY, 0, 0]);
    expect(drawn.trials.map((t) => t?.source_id)).toEqual([
      "NCT00000002",
      "NCT00000003",
      "NCT00000001",
      "NCT00000004",
    ]);
    expect(Array.from(drawn.cloud.positions.filter((_, i) => i % 3 === 0))).toEqual(
      [0.2, 0.3, 0.1, 0.4].map(Math.fround),
    );
    expect(drawn.index.get("NCT00000004")).toBe(3);
  });

  it("puts the rest of the map behind, without drawing a trial twice", () => {
    const { clusters, points } = parseLandscape(ROWS);
    const context = parseLandscape([...ROWS, point("NCT00000009", 9)]).points;
    const drawn = buildCloud(points.slice(0, 1), clusters, context);
    expect(Array.from(drawn.cloud.slots)).toEqual([GHOST, GHOST, GHOST, GHOST, 0]);
    expect(drawn.trials.slice(0, 4)).toEqual([null, null, null, null]);
    expect(drawn.trials[4]?.source_id).toBe("NCT00000001");
  });
});

describe("the 3-D landscape", () => {
  it("draws the trials and lists the clusters", async () => {
    show(ROWS);
    const list = await screen.findByRole("list", { name: "Clusters" });
    expect(
      within(list)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Alzheimer Disease2", "Pain1", "In no cluster1"]);
    expect(screen.getByText("384-dimensional vectors")).toBeInTheDocument();
    await waitFor(() => expect(scene().cloud?.slots).toHaveLength(4));
  });

  it("lights up the cluster chosen in the list, and lets go on a second click", async () => {
    const user = userEvent.setup();
    show(ROWS);
    const pain = await screen.findByRole("button", { name: /Pain/ });

    await user.click(pain);
    expect(pain).toHaveAttribute("aria-pressed", "true");
    expect(scene().highlight).toBe(9);

    await user.click(pain);
    expect(scene().highlight).toBeNull();
  });

  it("names the trial under the pointer, and pins it on a click", async () => {
    show(ROWS);
    const canvas = await screen.findByTestId("landscape-3d-canvas");
    await waitFor(() => expect(scene().cloud).not.toBeNull());
    scene().picked = 3; // NCT00000004

    fireEvent.pointerMove(canvas, { clientX: 40, clientY: 30 });
    act(() => scene().onFrame());
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Trial NCT00000004");
    expect(scene().marked).toBe(3);

    fireEvent.pointerDown(canvas, { clientX: 40, clientY: 30 });
    fireEvent.pointerUp(canvas, { clientX: 41, clientY: 30 });
    const pinned = await screen.findByTestId("pinned-trial");
    expect(within(pinned).getByRole("link", { name: /Open NCT00000004/ })).toHaveAttribute(
      "href",
      "/trials/NCT00000004",
    );

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("pinned-trial")).not.toBeInTheDocument());
  });

  it("doesn't pin anything when the press turned the view", async () => {
    show(ROWS);
    const canvas = await screen.findByTestId("landscape-3d-canvas");
    await waitFor(() => expect(scene().cloud).not.toBeNull());
    scene().picked = 3;

    fireEvent.pointerDown(canvas, { clientX: 40, clientY: 30 });
    fireEvent.pointerMove(canvas, { clientX: 90, clientY: 30 });
    fireEvent.pointerUp(canvas, { clientX: 90, clientY: 30 });

    expect(screen.queryByTestId("pinned-trial")).not.toBeInTheDocument();
  });

  it("turns slowly until asked to stop, and resets the view", async () => {
    const user = userEvent.setup();
    show(ROWS);
    await waitFor(() => expect(scene().autoRotate).toBe(true));

    await user.click(screen.getByRole("button", { name: "Stop turning" }));
    expect(scene().autoRotate).toBe(false);
    await user.click(screen.getByRole("button", { name: "Reset the view" }));
    expect(scene().resetView).toHaveBeenCalled();
  });

  it("keeps the whole map behind a filter's trials", async () => {
    mockApi({
      "/api/stats/research_landscape_3d": {
        chart_id: SPEC.id,
        data_version: 1,
        filtered: false,
        rows: [...ROWS, point("NCT00000009", 9)],
      },
    });
    const filtered = [summary(), ROWS[1] as ChartRow, ROWS[4] as ChartRow];
    show(filtered, { countries: ["FR"] });

    await waitFor(() =>
      expect(Array.from(scene().cloud?.slots ?? [])).toEqual([GHOST, GHOST, GHOST, GHOST, 0]),
    );
    expect(screen.getByText("The rest of the map")).toBeInTheDocument();
  });

  it("says what it needs when the map isn't laid out in 3-D yet", async () => {
    show([summary({ status: "missing_layout" })]);
    expect(await screen.findByTestId("landscape-unavailable")).toHaveTextContent(
      "Rebuild the stats to lay out this map",
    );
    expect(scenes.made).toHaveLength(0);
  });

  it("explains when the browser can't draw it", async () => {
    scenes.fail = true;
    show(ROWS);
    expect(await screen.findByText("This browser can't draw the 3D map")).toBeInTheDocument();
  });
});
