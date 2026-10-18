import type { UseQueryResult } from "@tanstack/react-query";
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Changes } from "@/api/client";
import { META, mockApi } from "@/test/api";
import { renderWithProviders } from "@/test/render";
import { ChangesTab } from "./changes";

const query = (data: Changes) => ({ data }) as UseQueryResult<Changes>;

describe("the changes tab", () => {
  it("shows each update's changes, old value to new", async () => {
    mockApi({ "/api/meta": META });
    renderWithProviders(
      <ChangesTab
        query={query({
          data_version: 3,
          source: "ctgov",
          source_id: "NCT1",
          changes: [
            {
              run_id: 4,
              changed_at: "2026-10-19T06:00:00+00:00",
              field: "status",
              old: "RECRUITING",
              new: "COMPLETED",
            },
            {
              run_id: 4,
              changed_at: "2026-10-19T06:00:00+00:00",
              field: "enrollment",
              old: 120,
              new: 1736,
            },
            {
              run_id: 4,
              changed_at: "2026-10-19T06:00:00+00:00",
              field: "countries",
              old: ["US"],
              new: ["US", "JP"],
            },
          ],
        })}
      />,
    );
    expect(await screen.findByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("Recruiting")).toBeInTheDocument();
    expect(screen.getByText("1,736")).toBeInTheDocument();
    expect(screen.getByText("+ JP")).toBeInTheDocument();
    expect(screen.getByText(/Update 4 · 3 fields/)).toBeInTheDocument();
  });

  it("explains an empty history", () => {
    mockApi({ "/api/meta": META });
    renderWithProviders(
      <ChangesTab
        query={query({ data_version: 3, source: "ctgov", source_id: "NCT1", changes: [] })}
      />,
    );
    expect(screen.getByText("No changes recorded")).toBeInTheDocument();
  });
});
