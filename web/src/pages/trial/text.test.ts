import { describe, expect, it } from "vitest";
import { blocks } from "./text";

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
    expect(parsed[0]).toEqual({ kind: "heading", text: "Inclusion Criteria" });
  });

  it("joins a paragraph's lines", () => {
    expect(blocks("One line\nand the next.\n\nAnother.")).toEqual([
      { kind: "paragraph", text: "One line and the next." },
      { kind: "paragraph", text: "Another." },
    ]);
  });
});
