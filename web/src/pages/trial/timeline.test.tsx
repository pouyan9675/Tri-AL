import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Change, TrialDetail } from "@/api/client";
import { META, mockApi } from "@/test/api";
import { renderWithProviders } from "@/test/render";
import { TRIAL } from "@/test/trial";
import { formatSpan, milestones, TrialTimeline } from "./timeline";

const NAMES: Record<string, string> = {
  ACTIVE_NOT_RECRUITING: "Active, not recruiting",
  RECRUITING: "Recruiting",
  UNKNOWN: "Unknown status",
  COMPLETED: "Completed",
};
const label = (_field: string, code: string | null | undefined) => NAMES[code ?? ""] ?? `${code}`;
const TODAY = "2026-10-19";

const steps = (trial: TrialDetail, changes?: Change[]) =>
  milestones(trial, changes, label, TODAY).map((m) => [m.title, m.date, m.state]);

describe("a trial's milestones", () => {
  it("put today's status between what happened and what's planned", () => {
    expect(steps(TRIAL)).toEqual([
      ["Registered", "2020-06-18", "done"],
      ["Started", "2020-06-19", "done"],
      ["Primary completion", "2023-04-14", "done"],
      ["Results posted", "2024-03-01", "done"],
      ["Active, not recruiting", TODAY, "done"],
      ["Study completion", "2028-11-01", "planned"],
    ]);
  });

  it("end where a terminated trial stopped, with why", () => {
    const trial: TrialDetail = {
      ...TRIAL,
      status: "TERMINATED",
      primary_completion_date: "2022-01-10",
      completion_date: "2022-01-10",
      completion_date_type: "ACTUAL",
      results_first_posted: null,
      why_stopped: "Sponsor decision",
    };

    const [last] = milestones(trial, [], label, TODAY).slice(-1);
    expect(last).toMatchObject({ title: "Stopped early", note: "Sponsor decision", state: "done" });
    expect(steps(trial).map(([title]) => title)).not.toContain("Terminated");
  });

  it("mark a withdrawn trial's planned dates as never happening", () => {
    const trial: TrialDetail = {
      ...TRIAL,
      status: "WITHDRAWN",
      start_date: "2027-01-01",
      start_date_type: "ESTIMATED",
      primary_completion_date_type: "ESTIMATED",
      results_first_posted: null,
    };

    expect(steps(trial)).toContainEqual(["Planned start", "2027-01-01", "cancelled"]);
    expect(steps(trial).map(([title]) => title)).not.toContain("Withdrawn");
  });

  it("flag estimated dates that passed without being confirmed", () => {
    const trial: TrialDetail = {
      ...TRIAL,
      status: "UNKNOWN",
      last_known_status: "RECRUITING",
      status_verified: "2020-10-01",
      completion_date: "2021-12-15",
      completion_date_type: "ESTIMATED",
      results_first_posted: null,
    };

    const items = milestones(trial, [], label, TODAY);
    expect(items.find((m) => m.key === "completion")?.state).toBe("overdue");
    expect(items.at(-1)).toMatchObject({
      kind: "now",
      title: "Unknown status",
      note: "last known recruiting · verified Oct 2020",
    });
  });

  it("include the status changes updates saw", () => {
    const changes: Change[] = [
      {
        run_id: 4,
        changed_at: "2026-10-18T06:00:00+00:00",
        field: "status",
        old: "RECRUITING",
        new: "ACTIVE_NOT_RECRUITING",
      },
      { run_id: 4, changed_at: "2026-10-18T06:00:00+00:00", field: "enrollment", old: 1, new: 2 },
    ];

    const change = milestones(TRIAL, changes, label, TODAY).find((m) => m.kind === "change");
    expect(change).toMatchObject({
      title: "Active, not recruiting",
      date: "2026-10-18",
      note: "Was Recruiting",
    });
  });
});

describe("spans between milestones", () => {
  it.each([
    ["2020-06-19", "2023-04-14", "2 yr 10 mo"],
    ["2020-01-01", "2022-01-01", "2 yr"],
    ["2020-01-01", "2020-06-01", "5 mo"],
    ["2020-01-01", "2020-01-20", "2 wk"],
    ["2020-06-18", "2020-06-19", ""],
  ])("%s to %s is %j", (from, to, text) => {
    expect(formatSpan(from, to)).toBe(text);
  });
});

describe("the timeline", () => {
  it("shows each milestone with its date, and what's still estimated", async () => {
    mockApi({ "/api/meta": META });
    renderWithProviders(<TrialTimeline trial={TRIAL} today={TODAY} />);

    await screen.findAllByText("Now: Active, not recruiting");
    const timeline = screen.getByTestId("timeline");
    const across = within(timeline).getAllByRole("list")[0] as HTMLElement;
    const items = within(across).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "RegisteredJun 18, 2020First posted",
      "2 yr 10 moStartedJun 19, 2020",
      "11 moPrimary completionApr 14, 2023Main outcome measured",
      "Results postedMar 1, 2024",
      "Now: Active, not recruitingToday",
      "Study completionNov 1, 2028· Estimated",
    ]);
    expect(timeline.textContent).toContain("Status verified Aug 2026");
  });
});
