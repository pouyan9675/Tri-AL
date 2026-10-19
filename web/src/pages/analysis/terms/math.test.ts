import { describe, expect, it } from "vitest";
import { onGrid, phaseGroupOf, stepAt, trackPosition } from "./math";

describe("phaseGroupOf", () => {
  it("groups a combined phase with the later one", () => {
    expect(
      ["EARLY_PHASE1", "PHASE1", "PHASE1_PHASE2", "PHASE2_PHASE3", "PHASE4"].map(phaseGroupOf),
    ).toEqual([0, 0, 1, 2, 3]);
    expect([null, undefined, "", "NA", "PHASE9"].map(phaseGroupOf)).toEqual([4, 4, 4, 4, 4]);
  });
});

describe("Kaplan-Meier curves on a grid", () => {
  const curve = { months: [6, 12, 30], values: [0.8, 0.5, 0.1] };

  it("holds each value until the next step", () => {
    expect(stepAt(curve, 0, 1)).toBe(1);
    expect(stepAt(curve, 6, 1)).toBe(0.8);
    expect(stepAt(curve, 11.9, 1)).toBe(0.8);
    expect(stepAt(curve, 12, 1)).toBe(0.5);
    expect(stepAt(curve, 100, 1)).toBe(0.1);
    expect(stepAt({ months: [], values: [] }, 5, 0)).toBe(0);
  });

  it("puts several curves on one month grid, leaving out empty ones", () => {
    const rows = onGrid({ term: curve, baseline: { months: [], values: [] } }, 12, 1, 6);
    expect(rows).toEqual([
      { month: 0, term: 1 },
      { month: 6, term: 0.8 },
      { month: 12, term: 0.5 },
    ]);
  });
});

describe("trackPosition", () => {
  it("maps -1..1 to 0..1 and clips beyond", () => {
    expect(trackPosition(0)).toBe(0.5);
    expect(trackPosition(0.5)).toBe(0.75);
    expect(trackPosition(-3)).toBe(0);
    expect(trackPosition(3)).toBe(1);
  });
});
