import { describe, expect, it } from "vitest";
import { type Label, layoutNetwork, placeLabels } from "./network-layout";

const nodes = [
  { group: -1, center: true },
  { group: 0, center: false },
  { group: 0, center: false },
  { group: 0, center: false },
  { group: 1, center: false },
  { group: 1, center: false },
  { group: 2, center: false },
];
const edges = [
  { source: 1, target: 2, jaccard: 0.6 },
  { source: 2, target: 3, jaccard: 0.5 },
  { source: 1, target: 3, jaccard: 0.4 },
  { source: 4, target: 5, jaccard: 0.7 },
];

const distance = (a: { x: number; y: number }, b: { x: number; y: number }) =>
  Math.hypot(a.x - b.x, a.y - b.y);

describe("layoutNetwork", () => {
  it("pins the term in the middle and keeps the rest in the unit disk", () => {
    const placed = layoutNetwork(nodes, edges);
    expect(placed[0]).toEqual({ x: 0, y: 0 });
    for (const point of placed) expect(Math.hypot(point.x, point.y)).toBeLessThanOrEqual(1.0001);
    expect(Math.max(...placed.map((p) => Math.hypot(p.x, p.y)))).toBeCloseTo(1, 5);
  });

  it("lands the same way every time", () => {
    expect(layoutNetwork(nodes, edges)).toEqual(layoutNetwork(nodes, edges));
  });

  it("draws terms that share trials together", () => {
    const placed = layoutNetwork(nodes, edges);
    const [, a, b, c, d, e, lone] = placed as { x: number; y: number }[];
    if (!a || !b || !c || !d || !e || !lone) throw new Error("missing nodes");
    const joined = (distance(a, b) + distance(b, c) + distance(d, e)) / 3;
    const apart = (distance(a, d) + distance(c, e) + distance(b, lone)) / 3;
    expect(joined).toBeLessThan(apart);
  });

  it("handles no nodes and a term alone", () => {
    expect(layoutNetwork([], [])).toEqual([]);
    expect(layoutNetwork([{ group: -1, center: true }], [])).toEqual([{ x: 0, y: 0 }]);
  });
});

describe("placeLabels", () => {
  const label = (x: number, y: number, priority: number, prefer: Label["prefer"]): Label => ({
    x,
    y,
    r: 5,
    width: 60,
    height: 12,
    priority,
    prefer,
  });

  it("puts each label on its preferred side when there's room", () => {
    expect(placeLabels([label(0, 0, 1, "right"), label(0, 100, 2, "left")])).toEqual([
      "right",
      "left",
    ]);
  });

  it("moves a label that would collide, or hides it, the most important first", () => {
    // Three nodes in a row. The first's label would cover the middle node on the right, so
    // it goes left; the middle one's fits neither side, and only shows on hover.
    const sides = placeLabels([
      label(0, 0, 3, "right"),
      label(40, 0, 1, "right"),
      label(140, 0, 2, "left"),
    ]);
    expect(sides).toEqual(["left", null, "left"]);
  });
});
