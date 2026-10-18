import { describe, expect, it } from "vitest";
import type { ChartSpec } from "@/api/client";
import { sections } from "./index";

function chart(id: string, section: string): ChartSpec {
  return {
    id,
    title: id,
    widget: "bar",
    description: "",
    section,
    x: "label",
    y: "value",
    layout: { width: 2, height: 1, order: 0 },
    plugin: "charts",
    precomputed: true,
  };
}

describe("dashboard sections", () => {
  it("groups charts by section, each where its first chart is", () => {
    const grouped = sections([
      chart("totals", ""),
      chart("map", ""),
      chart("trends", "Research Intelligence"),
      chart("late", ""),
      chart("more", "Research Intelligence"),
    ]);

    expect(grouped.map((s) => [s.title, s.charts.map((c) => c.id)])).toEqual([
      ["", ["totals", "map", "late"]],
      ["Research Intelligence", ["trends", "more"]],
    ]);
  });
});
