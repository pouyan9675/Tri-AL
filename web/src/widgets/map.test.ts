import { describe, expect, it } from "vitest";
import { decade, step } from "./map";

describe("the map's color classes", () => {
  it("puts counts in decades", () => {
    expect([0, 1, 9, 10, 99, 100, 196216].map(decade)).toEqual([0, 1, 1, 2, 2, 3, 6]);
  });

  it("spreads few classes over the whole ramp", () => {
    expect([1, 2, 3].map((level) => step(level, 3))).toEqual([100, 400, 700]);
    expect([1, 2, 3, 4, 5, 6].map((level) => step(level, 6))).toEqual([
      100, 200, 300, 500, 600, 700,
    ]);
    expect(step(1, 1)).toBe(700);
  });
});
