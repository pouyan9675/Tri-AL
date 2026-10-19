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

function hit(id: number, sourceId: string, idMatch: "exact" | "prefix" | null) {
  return {
    id,
    source: "ctgov",
    source_id: sourceId,
    title: `Study ${sourceId}`,
    status: "COMPLETED",
    phase: "PHASE2",
    score: idMatch ? null : 4.2,
    snippet: [{ text: "A study.", match: false }],
    id_match: idMatch,
  };
}

function byId(q: string, hits: ReturnType<typeof hit>[], candidates = 0) {
  return { data_version: 3, query: q, hits, candidates, capped: false, names: [] };
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

  it("puts a trial found by its ID first and opens it with Enter", async () => {
    mockApi({
      "/api/meta": META,
      "/api/search": () =>
        byId("nct04437511", [hit(1, "NCT04437511", "exact"), hit(2, "NCT06000001", null)], 1),
    });
    renderWithProviders(<CommandPalette open onOpenChange={() => {}} />);
    await userEvent.type(screen.getByRole("combobox"), "nct04437511");

    expect(await screen.findByText("Trial ID")).toBeInTheDocument();
    expect(screen.getByText("Text matches")).toBeInTheDocument();
    expect(screen.getByText("NCT04437511", { selector: "mark" })).toBeInTheDocument();
    expect(screen.getByText("1 by ID · 1 text match")).toBeInTheDocument();
    expect(screen.getByText(/List every trial with/)).toBeInTheDocument();

    await userEvent.keyboard("{Enter}");
    expect(navigate).toHaveBeenCalledWith({
      to: "/trials/$sourceId",
      params: { sourceId: "NCT04437511" },
    });
  });

  it("completes the start of an ID", async () => {
    mockApi({
      "/api/meta": META,
      "/api/search": () =>
        byId("nct0443", [hit(1, "NCT04430010", "prefix"), hit(2, "NCT04437511", "prefix")]),
    });
    renderWithProviders(<CommandPalette open onOpenChange={() => {}} />);
    await userEvent.type(screen.getByRole("combobox"), "nct0443");

    expect(await screen.findByText("Trial IDs starting with nct0443")).toBeInTheDocument();
    expect(screen.getAllByTestId("hit-id").map((id) => id.textContent)).toEqual([
      "NCT04430010",
      "NCT04437511",
    ]);
    expect(screen.getAllByText("NCT0443", { selector: "mark" })).toHaveLength(2);
    expect(screen.getByText("2 by ID")).toBeInTheDocument();
    // The trial list has no use for the start of an ID.
    expect(screen.queryByText(/List every trial with/)).not.toBeInTheDocument();
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
