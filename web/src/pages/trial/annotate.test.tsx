import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { AnnotationEvent } from "@/api/client";
import { AI_SETTINGS, mockApi, ndjson } from "@/test/api";
import { renderWithProviders } from "@/test/render";
import { TRIAL } from "@/test/trial";
import { EligibilityTab } from "./sections";

const CRITERIA =
  "Inclusion Criteria:\n\n* Mild dementia due to\n  Alzheimer's disease\n* Takes donepezil";
const TRIAL_WITH_CRITERIA = { ...TRIAL, eligibility_criteria: CRITERIA };
const ANNOTATE = "POST /api/trials/NCT04437511/annotate";

function at(term: string) {
  const start = CRITERIA.indexOf(term);
  return { start, end: start + term.length };
}

const EVENTS: AnnotationEvent[] = [
  {
    type: "start",
    model: "qwen-tiny",
    length: CRITERIA.length,
    chunks: 2,
    cached: false,
    labels: [
      { name: "Condition", color: "red" },
      { name: "Intervention", color: "blue" },
    ],
  },
  {
    type: "spans",
    chunk: 1,
    spans: [{ ...at("donepezil"), label: "Intervention" }],
  },
  {
    type: "spans",
    chunk: 0,
    spans: [{ ...at("dementia due to\n  Alzheimer's disease"), label: "Condition" }],
  },
  { type: "done", spans: 2, seconds: 0.8 },
];

describe("annotating a trial text", () => {
  it("marks each label's terms, then hides and shows them without asking again", async () => {
    const user = userEvent.setup();
    const { requests } = mockApi({ "/api/ai": AI_SETTINGS, [ANNOTATE]: () => ndjson(EVENTS) });
    renderWithProviders(<EligibilityTab trial={TRIAL_WITH_CRITERIA} />);

    await user.click(await screen.findByRole("button", { name: "Annotate" }));

    const condition = await screen.findByTitle("Condition");
    expect(condition.tagName).toBe("MARK");
    expect(condition).toHaveTextContent("dementia due to Alzheimer's disease");
    expect(screen.getByTitle("Intervention")).toHaveTextContent("donepezil");
    expect(await screen.findByText("qwen-tiny · 0.8 s")).toBeInTheDocument();
    const posted = requests.find((r) => r.method === "POST");
    expect(await posted?.json()).toEqual({ field: "eligibility_criteria" });

    const legend = screen.getByRole("button", { name: /^Condition/ });
    expect(legend).toHaveAttribute("aria-pressed", "true");
    await user.click(legend);
    expect(screen.queryByTitle("Condition")).not.toBeInTheDocument();
    expect(legend).toHaveAttribute("aria-pressed", "false");

    await user.click(screen.getByRole("button", { name: "Hide annotations" }));
    expect(document.querySelectorAll("mark")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Show annotations" }));
    expect(document.querySelectorAll("mark")).toHaveLength(1);
    expect(requests.filter((r) => r.method === "POST")).toHaveLength(1);
  });

  it("offers to try again when the model fails", async () => {
    const user = userEvent.setup();
    let calls = 0;
    mockApi({
      "/api/ai": AI_SETTINGS,
      [ANNOTATE]: () => {
        calls += 1;
        if (calls === 1) {
          return Response.json({ detail: "can't reach the model server" }, { status: 502 });
        }
        return ndjson([...EVENTS.slice(0, 2), { type: "error", message: "the model crashed" }]);
      },
    });
    renderWithProviders(<EligibilityTab trial={TRIAL_WITH_CRITERIA} />);

    await user.click(await screen.findByRole("button", { name: "Annotate" }));
    await user.click(await screen.findByRole("button", { name: "Try again" }));
    await screen.findByRole("button", { name: "Try again" });
    expect(calls).toBe(2);
  });

  it("isn't offered when AI is off, and waits for labels", async () => {
    mockApi({ "/api/ai": { ...AI_SETTINGS, enabled: false } });
    const { unmount } = renderWithProviders(<EligibilityTab trial={TRIAL_WITH_CRITERIA} />);
    await waitFor(() => expect(screen.getByText("Criteria")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Annotate" })).not.toBeInTheDocument();
    unmount();

    mockApi({ "/api/ai": { ...AI_SETTINGS, labels: [] } });
    renderWithProviders(<EligibilityTab trial={TRIAL_WITH_CRITERIA} />);
    expect(await screen.findByRole("button", { name: "Annotate" })).toBeDisabled();
  });
});
