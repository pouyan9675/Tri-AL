import { describe, expect, it } from "vitest";
import type { Piece } from "@/lib/annotations";
import { blocks } from "./text";

/** Every piece of block text is the source text it came from. */
function expectMapped(source: string, text: string, map: Piece[]) {
  for (const piece of map) {
    expect(text.slice(piece.at, piece.at + piece.len)).toBe(
      source.slice(piece.src, piece.src + piece.len),
    );
  }
  expect(map.reduce((sum, piece) => sum + piece.len, 0) + map.length - 1).toBe(text.length);
}

describe("registry text", () => {
  it("finds headings, bullets and paragraphs", () => {
    const text = [
      "Inclusion Criteria:",
      "",
      "* Age 50 to 85",
      "* MMSE between 20 and",
      "  28 at screening",
      "  * nested detail",
      "",
      "Exclusion Criteria:",
      "",
      "- Prior anti-amyloid therapy",
      "",
      "Participants must have a study partner.",
    ].join("\n");
    const parsed = blocks(text);
    expect(parsed.map((block) => block.kind)).toEqual([
      "heading",
      "list",
      "heading",
      "list",
      "paragraph",
    ]);
    const list = parsed[1];
    expect(list?.kind === "list" && list.items.map((item) => [item.text, item.depth])).toEqual([
      ["Age 50 to 85", 0],
      ["MMSE between 20 and 28 at screening", 0],
      ["nested detail", 1],
    ]);
    expect(parsed[0]).toMatchObject({ kind: "heading", text: "Inclusion Criteria" });
    for (const block of parsed) {
      if (block.kind === "list") {
        for (const item of block.items) expectMapped(text, item.text, item.map);
      } else expectMapped(text, block.text, block.map);
    }
  });

  it("joins a paragraph's lines", () => {
    expect(blocks("One line\r\n  and the next.\n\nAnother.")).toEqual([
      {
        kind: "paragraph",
        text: "One line and the next.",
        map: [
          { at: 0, src: 0, len: 8 },
          { at: 9, src: 11, len: 13 },
        ],
      },
      { kind: "paragraph", text: "Another.", map: [{ at: 0, src: 26, len: 8 }] },
    ]);
  });
});
