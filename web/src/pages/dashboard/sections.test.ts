import { describe, expect, it } from "vitest";
import type { ChartSpec } from "@/api/client";
import { onPage } from "@/api/queries";
import { sections } from "@/components/chart-sections";

function chart(id: string, section: string, page: ChartSpec["page"] = "dashboard"): ChartSpec {
  return {
    id,
    title: id,
    widget: "bar",
    description: "",
    section,
    x: "label",
    y: "value",
    series: [],
    layout: { width: 2, height: 1, order: 0 },
    page,
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

  it("leaves the analysis page's charts off the dashboard", () => {
    const charts = [chart("totals", ""), chart("landscape_3d", "", "analysis")];
    expect(onPage(charts, "dashboard").map((c) => c.id)).toEqual(["totals"]);
    expect(onPage(charts, "analysis").map((c) => c.id)).toEqual(["landscape_3d"]);
    expect(onPage(undefined, "analysis")).toEqual([]);
  });
});
