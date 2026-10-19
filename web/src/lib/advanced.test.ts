import { describe, expect, it } from "vitest";
import {
  apiQuery,
  extraFieldCount,
  hasQuery,
  parseAdvancedSearch,
  parseAge,
  withoutAdvanced,
} from "./advanced";

describe("advanced search params", () => {
  it("reads the fields it knows and drops what's malformed", () => {
    expect(
      parseAdvancedSearch({
        exclusion: "  warfarin ",
        title: "",
        masking: ["DOUBLE", "TRIPLE", "DOUBLE", " "],
        allocation: "RANDOMIZED",
        age: " 60 .. 80 ",
        sex: "OTHER",
        healthy_volunteers: "true",
        placebo: "maybe",
        near: "42.36, -71.06",
        within: "100",
        place: "Boston",
        sort: "relevance",
        status: ["RECRUITING"],
      }),
    ).toEqual({
      exclusion: "warfarin",
      masking: ["DOUBLE", "TRIPLE"],
      allocation: ["RANDOMIZED"],
      age: "60..80",
      healthy_volunteers: true,
      near: "42.36,-71.06",
      within: 100,
      place: "Boston",
      sort: "relevance",
    });
  });

  it("keeps a distance and a place's name only with a point", () => {
    expect(parseAdvancedSearch({ near: "Boston", within: "50", place: "Boston" })).toEqual({});
    expect(parseAdvancedSearch({ near: "1,2", within: "-5" })).toEqual({ near: "1,2" });
    expect(parseAdvancedSearch({ sort: "title" })).toEqual({});
  });

  it("reads ages and ranges", () => {
    expect(parseAge("70")).toBe("70");
    expect(parseAge("070")).toBe("70");
    expect(parseAge("..17")).toBe("..17");
    expect(parseAge("65..")).toBe("65..");
    expect(parseAge("80..60")).toBeUndefined();
    expect(parseAge("..")).toBeUndefined();
    expect(parseAge("old")).toBeUndefined();
    expect(parseAge("1000")).toBeUndefined();
    expect(parseAge(undefined)).toBeUndefined();
  });

  it("has a query when a field is set, not a sort or a place's name alone", () => {
    expect(hasQuery({})).toBe(false);
    expect(hasQuery({ sort: "-start_date", place: "Boston" })).toBe(false);
    expect(hasQuery({ placebo: false })).toBe(true);
  });

  it("counts the fields set besides text", () => {
    expect(extraFieldCount({ title: "a", sort: "relevance", within: 50 })).toBe(0);
    expect(extraFieldCount({ age: " ", masking: [] })).toBe(0);
    expect(
      extraFieldCount({
        age: "70",
        healthy_volunteers: false,
        placebo: false,
        masking: ["DOUBLE"],
      }),
    ).toBe(4);
    expect(extraFieldCount({ near: "1,2", sex: "MALE", allocation: ["RANDOMIZED"] })).toBe(3);
  });

  it("sends the API what it reads, in a stable order", () => {
    expect(
      apiQuery({ title: "a", masking: ["TRIPLE", "DOUBLE"], place: "Boston", near: "1,2" }),
    ).toEqual({ masking: ["DOUBLE", "TRIPLE"], near: "1,2", title: "a" });
    expect(Object.keys(apiQuery({ title: "a", age: "70" }))).toEqual(["age", "title"]);
  });

  it("leaves the filter when the search is taken out", () => {
    expect(
      withoutAdvanced({ status: ["RECRUITING"], exclusion: "warfarin", place: "x", q: "tau" }),
    ).toEqual({ status: ["RECRUITING"], q: "tau" });
  });
});
