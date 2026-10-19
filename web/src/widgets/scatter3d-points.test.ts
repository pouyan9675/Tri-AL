import { describe, expect, it } from "vitest";
import {
  type Cloud,
  cssColor,
  FAINT,
  fitDistance,
  GHOST,
  GREY,
  nearestOnScreen,
  type Palette,
  pointSize,
  sizes,
  tints,
} from "./scatter3d-points";

// Clip coordinates are (x, y, ·, -z): a camera at the origin looking down -z.
const LOOKING_DOWN_Z = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, -1, 0, 0, 0, 0];

describe("picking on screen", () => {
  const positions = new Float32Array([0, 0, -1, 0.5, 0, -1, 0.02, 0, -2, 0, 0, 1]);

  it("finds the point nearest the pointer, within the radius", () => {
    // On a 100×100 view: (50, 50), (75, 50), (50.5, 50) and one behind the camera.
    expect(nearestOnScreen(positions, LOOKING_DOWN_Z, 100, 100, 74, 52, 10)).toBe(1);
    expect(nearestOnScreen(positions, LOOKING_DOWN_Z, 100, 100, 62, 50, 10)).toBeNull();
  });

  it("prefers the nearer of two at the same spot, and skips what isn't pickable", () => {
    expect(nearestOnScreen(positions, LOOKING_DOWN_Z, 100, 100, 50, 50, 10)).toBe(0);
    expect(nearestOnScreen(positions, LOOKING_DOWN_Z, 100, 100, 50, 50, 10, (i) => i !== 0)).toBe(
      2,
    );
  });

  it("never picks a point behind the camera", () => {
    const behind = new Float32Array([0, 0, 1]);
    expect(nearestOnScreen(behind, LOOKING_DOWN_Z, 100, 100, 50, 50, 50)).toBeNull();
  });
});

describe("tints", () => {
  const palette: Palette = {
    chart: Array.from({ length: 8 }, (_, i) => [i / 10, 0, 0] as const),
    muted: [0.5, 0.5, 0.5],
    foreground: [1, 1, 1],
  };
  const cloud: Cloud = {
    positions: new Float32Array(15),
    slots: new Uint8Array([GHOST, FAINT, GREY, 0, 3]),
    clusters: new Int32Array([-99, -1, 7, 1, 2]),
  };
  const rows = (values: Float32Array) =>
    Array.from({ length: values.length / 4 }, (_, i) =>
      Array.from(values.slice(i * 4, i * 4 + 4), (v) => Math.round(v * 100) / 100),
    );

  it("colours the coloured clusters and greys the rest, faintest behind", () => {
    expect(rows(tints(cloud, palette, null))).toEqual([
      [0.5, 0.5, 0.5, 0.05],
      [0.5, 0.5, 0.5, 0.5], // over the faint rest of the map, stronger than they'd be alone
      [0.5, 0.5, 0.5, 0.7],
      [0, 0, 0, 0.85],
      [0.3, 0, 0, 0.85],
    ]);
    const alone = { ...cloud, slots: cloud.slots.slice(1), clusters: cloud.clusters.slice(1) };
    expect(rows(tints(alone, palette, null)).map((row) => row[3])).toEqual([0.2, 0.4, 0.85, 0.85]);
  });

  it("lights up one cluster, a grey one in the foreground colour, and fades the others", () => {
    const lit = rows(tints(cloud, palette, 7));
    expect(lit[2]).toEqual([1, 1, 1, 0.95]);
    expect(lit[3]).toEqual([0.5, 0.5, 0.5, 0.05]);
    expect(lit[0]).toEqual([0.5, 0.5, 0.5, 0.05]); // the context behind stays as it was
  });
});

describe("sizes and framing", () => {
  it("draws more points smaller, within bounds", () => {
    expect(pointSize(20_000)).toBeLessThan(pointSize(500));
    expect(pointSize(1)).toBe(0.045);
    expect(pointSize(10_000_000)).toBe(0.012);
  });

  it("sizes a filter's few trials by their own count, not the map's behind them", () => {
    const slots = new Uint8Array([...Array<number>(20_000).fill(GHOST), 0, GREY]);
    const each = sizes({ positions: new Float32Array(), slots, clusters: new Int32Array() });
    expect(each[0]).toBeCloseTo(pointSize(20_000));
    expect(each[20_001]).toBeCloseTo(pointSize(2));
  });

  it("backs the camera off further for a narrow view", () => {
    expect(fitDistance(1, 0.5)).toBeGreaterThan(fitDistance(1, 2));
    expect(fitDistance(1, 2)).toBeCloseTo(1.05 / Math.sin((40 * Math.PI) / 360));
  });

  it("reads hex colours without a canvas", () => {
    expect(cssColor("#ff8000")).toEqual([1, 128 / 255, 0]);
    expect(cssColor("oklch(0.5 0.1 200)")).toEqual([0, 0, 0]); // jsdom has no canvas
  });
});
