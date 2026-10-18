import { describe, expect, it } from "vitest";
import {
  activeCount,
  canonical,
  chips,
  joinRange,
  onlyFilter,
  parseFilter,
  parseTrialsSearch,
  splitRange,
  toggleValue,
} from "./filters";
import { parseSearch, stringifySearch } from "./search-params";

describe("filters in the URL", () => {
  it("reads the API's own query format", () => {
    const search = parseSearch(
      "?status=RECRUITING&status=COMPLETED&q=donepezil&start=2020..2023&has_results=true",
    );
    expect(parseFilter(search)).toEqual({
      status: ["RECRUITING", "COMPLETED"],
      q: "donepezil",
      start: "2020..2023",
      has_results: true,
    });
  });

  it("writes repeated keys, not JSON, and leaves out empty values", () => {
    const text = stringifySearch({
      status: ["RECRUITING", "COMPLETED"],
      conditions: ["Alzheimer Disease"],
      q: undefined,
      phase: [],
    });
    expect(text).toBe("?status=RECRUITING&status=COMPLETED&conditions=Alzheimer+Disease");
    expect(stringifySearch({})).toBe("");
  });

  it("round-trips names with commas", () => {
    const filter = { sponsors: ["Lilly, Eli and Company"], countries: ["US"] };
    expect(parseFilter(parseSearch(stringifySearch(filter)))).toEqual(filter);
  });

  it("drops what isn't a filter", () => {
    expect(
      parseFilter({ start: "2020", has_results: "maybe", status: ["", "  "], other: "x" }),
    ).toEqual({});
  });

  it("keeps a known sort and drops the default", () => {
    expect(parseTrialsSearch({ sort: "-enrollment" }).sort).toBe("-enrollment");
    expect(parseTrialsSearch({ sort: "-last_update" }).sort).toBeUndefined();
    expect(parseTrialsSearch({ sort: "title" }).sort).toBeUndefined();
    expect(onlyFilter({ sort: "-enrollment", phase: ["PHASE3"] })).toEqual({ phase: ["PHASE3"] });
  });

  it("makes equal filters equal keys", () => {
    expect(canonical({ status: ["B", "A"], q: "x" })).toEqual(
      canonical({ q: "x", status: ["A", "B"] }),
    );
  });

  it("toggles values and counts what's active", () => {
    const one = toggleValue({}, "status", "RECRUITING");
    expect(one).toEqual({ status: ["RECRUITING"] });
    expect(toggleValue(one, "status", "RECRUITING").status).toBeUndefined();
    expect(activeCount({ status: ["A", "B"], q: "x", start: "2020..", has_results: false })).toBe(
      5,
    );
  });

  it("gives one removable chip per value", () => {
    const filter = { status: ["A", "B"], enrollment: "100.." };
    const list = chips(filter);
    expect(list.map((chip) => `${chip.field}=${chip.value}`)).toEqual([
      "status=A",
      "status=B",
      "enrollment=100..",
    ]);
    expect(list[0]?.remove).toEqual({ status: ["B"], enrollment: "100.." });
  });

  it("splits and joins open-ended ranges", () => {
    expect(splitRange("2020..")).toEqual(["2020", ""]);
    expect(joinRange("", "2023")).toBe("..2023");
    expect(joinRange(" ", "")).toBeUndefined();
  });
});
