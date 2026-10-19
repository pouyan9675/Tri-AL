import { describe, expect, it } from "vitest";
import { EMPTY_ANNOTATION, marksFor, withEvent } from "./annotations";

describe("annotation events", () => {
  it("fold into one state as they stream", () => {
    const labels = [{ name: "Condition", color: "red" as const }];
    let state = withEvent(EMPTY_ANNOTATION, {
      type: "start",
      model: "tiny",
      length: 40,
      chunks: 2,
      cached: false,
      labels,
    });
    state = withEvent(state, {
      type: "spans",
      chunk: 1,
      spans: [{ start: 30, end: 35, label: "Condition" }],
    });
    expect([state.received, state.seconds]).toEqual([1, null]);
    state = withEvent(state, {
      type: "spans",
      chunk: 0,
      spans: [{ start: 2, end: 9, label: "Condition" }],
    });
    state = withEvent(state, { type: "done", spans: 2, seconds: 1.5 });

    expect(state).toEqual({
      model: "tiny",
      length: 40,
      chunks: 2,
      received: 2,
      cached: false,
      labels,
      spans: [
        { start: 2, end: 9, label: "Condition" },
        { start: 30, end: 35, label: "Condition" },
      ],
      seconds: 1.5,
    });
  });
});

describe("marks", () => {
  // "Mild cognitive\n  impairment and AD" shown as "Mild cognitive impairment and AD"
  const map = [
    { at: 0, src: 0, len: 14 },
    { at: 15, src: 17, len: 17 },
  ];

  it("follow a block's map back to the source", () => {
    expect(marksFor(map, [{ start: 31, end: 33, label: "Condition" }])).toEqual([
      { start: 29, end: 31, label: "Condition" },
    ]);
  });

  it("keep a span over a line break in one piece", () => {
    expect(marksFor(map, [{ start: 0, end: 27, label: "Condition" }])).toEqual([
      { start: 0, end: 25, label: "Condition" },
    ]);
  });

  it("skip spans in other blocks", () => {
    expect(marksFor(map, [{ start: 40, end: 45, label: "Condition" }])).toEqual([]);
    expect(marksFor([], [{ start: 0, end: 5, label: "Condition" }])).toEqual([]);
  });
});
