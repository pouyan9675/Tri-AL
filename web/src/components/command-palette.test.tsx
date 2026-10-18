import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { META, mockApi } from "@/test/api";
import { renderWithProviders } from "@/test/render";
import CommandPalette from "./command-palette";

const navigate = vi.fn();
vi.mock("@tanstack/react-router", async (original) => ({
  ...(await original<typeof import("@tanstack/react-router")>()),
  useNavigate: () => navigate,
}));

function result(q: string, capped: boolean) {
  return {
    data_version: 3,
    query: q,
    hits: [
      {
        id: 1,
        source: "ctgov",
        source_id: "NCT04437511",
        title: "A Study of Donanemab in Early Alzheimer's Disease",
        status: "ACTIVE_NOT_RECRUITING",
        phase: "PHASE3",
        score: 9.1,
        snippet: [
          { text: "early ", match: false },
          { text: "Alzheimer", match: true },
          { text: "'s disease", match: false },
        ],
      },
    ],
    candidates: capped ? 20000 : 9456,
    capped,
    names: [{ kind: "condition", id: 5, name: "Alzheimer Disease" }],
  };
}

describe("the ⌘K palette", () => {
  beforeEach(() => navigate.mockReset());

  it("searches as you type and opens a hit", async () => {
    const { requests } = mockApi({
      "/api/meta": META,
      "/api/search": (_request: Request, url: URL) =>
        result(url.searchParams.get("q") ?? "", false),
    });
    renderWithProviders(<CommandPalette open onOpenChange={() => {}} />);
    await userEvent.type(screen.getByRole("combobox"), "alzheimer");
    expect(
      await screen.findByText("A Study of Donanemab in Early Alzheimer's Disease"),
    ).toBeInTheDocument();
    expect(screen.getByText("Alzheimer", { selector: "mark" })).toBeInTheDocument();
    expect(screen.queryByTestId("capped-notice")).not.toBeInTheDocument();
    expect(screen.getByText("9,456 matches")).toBeInTheDocument();
    // Debounced: one request for the whole word, not one per letter.
    expect(requests.filter((request) => request.url.includes("/api/search"))).toHaveLength(1);

    await userEvent.click(screen.getByText("A Study of Donanemab in Early Alzheimer's Disease"));
    expect(navigate).toHaveBeenCalledWith({
      to: "/trials/$sourceId",
      params: { sourceId: "NCT04437511" },
    });
  });

  it("says when a broad search ranked only the newest matches", async () => {
    mockApi({
      "/api/meta": META,
      "/api/search": (_request: Request, url: URL) => result(url.searchParams.get("q") ?? "", true),
    });
    renderWithProviders(<CommandPalette open onOpenChange={() => {}} />);
    await userEvent.type(screen.getByRole("combobox"), "study");
    expect(await screen.findByTestId("capped-notice")).toHaveTextContent(
      "the best of the 20,000 most recently registered",
    );
  });

  it("jumps from a name to the filtered trial list", async () => {
    mockApi({
      "/api/meta": META,
      "/api/search": (_request: Request, url: URL) =>
        result(url.searchParams.get("q") ?? "", false),
    });
    renderWithProviders(<CommandPalette open onOpenChange={() => {}} />);
    await userEvent.type(screen.getByRole("combobox"), "alzheimer");
    await userEvent.click(await screen.findByText("Alzheimer Disease"));
    expect(navigate).toHaveBeenCalledWith({
      to: "/trials",
      search: { conditions: ["Alzheimer Disease"] },
    });
  });
});
