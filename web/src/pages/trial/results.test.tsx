import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { TrialResults } from "@/api/results";
import { renderWithProviders } from "@/test/render";
import { Results, significance } from "./results";

const value = (text: string, spread: string | null = null) => ({
  value: text,
  spread,
  lower: null,
  upper: null,
  comment: null,
});

const RESULTS: TrialResults = {
  source: "ctgov",
  source_id: "NCT04102579",
  flow: {
    groups: [
      { id: "FG000", title: "Valbenazine", description: null },
      { id: "FG001", title: "Placebo", description: null },
    ],
    periods: [
      {
        title: "Overall Study",
        milestones: [
          { label: "STARTED", counts: { FG000: 64, FG001: 64 } },
          { label: "COMPLETED", counts: { FG000: 57, FG001: 54 } },
        ],
        dropouts: [
          { reason: "Withdrawal by Subject", kind: "withdrawal", counts: { FG000: 3, FG001: 4 } },
        ],
      },
    ],
    recruitment: null,
    pre_assignment: null,
  },
  baseline: {
    groups: [
      { id: "BG000", title: "Valbenazine", description: null },
      { id: "BG001", title: "Placebo", description: null },
      { id: "BG002", title: "Total", description: null },
    ],
    total: "BG002",
    participants: { BG000: 64, BG001: 63, BG002: 127 },
    measures: [
      {
        title: "Age, Continuous",
        param: "MEAN",
        dispersion: "STANDARD_DEVIATION",
        unit: "years",
        classes: [
          {
            title: "",
            categories: [
              {
                title: "",
                values: {
                  BG000: value("54.1", "10.1"),
                  BG001: value("53.6", "11.6"),
                  BG002: value("53.8", "10.8"),
                },
              },
            ],
          },
        ],
        description: null,
        population: null,
      },
      {
        title: "Race (NIH/OMB)",
        param: "COUNT_OF_PARTICIPANTS",
        dispersion: null,
        unit: "Participants",
        classes: [
          {
            title: "",
            categories: [
              {
                title: "White",
                values: { BG000: value("62"), BG001: value("60"), BG002: value("122") },
              },
            ],
          },
        ],
        description: null,
        population: null,
      },
    ],
    population: null,
  },
  outcomes: [
    {
      type: "PRIMARY",
      title: "Change in the UHDRS Total Maximal Chorea Score",
      groups: [
        { id: "OG000", title: "Valbenazine", description: null },
        { id: "OG001", title: "Placebo", description: null },
      ],
      participants: { OG000: 64, OG001: 61 },
      classes: [
        {
          title: "",
          categories: [
            { title: "", values: { OG000: value("-4.6", "0.40"), OG001: value("-1.4", "0.41") } },
          ],
        },
      ],
      analyses: [
        {
          groups: ["OG000", "OG001"],
          method: "MMRM",
          p_value: "<0.0001",
          estimate_type: "LS Mean Difference",
          estimate: "-3.16",
          ci_percent: "95",
          ci_lower: "-4.37",
          ci_upper: "-1.95",
          hypothesis: "OTHER",
          description: null,
        },
      ],
      description: null,
      time_frame: "Week 12",
      population: null,
      param: "LEAST_SQUARES_MEAN",
      dispersion: "Standard Error",
      unit: "score on a scale",
      posted: true,
    },
  ],
  adverse_events: {
    groups: [
      {
        id: "EG000",
        title: "Valbenazine",
        description: null,
        placebo: false,
        total: false,
        serious_affected: 1,
        serious_at_risk: 64,
        other_affected: 35,
        other_at_risk: 64,
        deaths: 0,
        deaths_at_risk: 64,
      },
      {
        id: "EG001",
        title: "Placebo",
        description: null,
        placebo: true,
        total: false,
        serious_affected: 2,
        serious_at_risk: 63,
        other_affected: 17,
        other_at_risk: 63,
        deaths: 1,
        deaths_at_risk: 63,
      },
    ],
    events: [
      {
        term: "Psychotic disorder",
        serious: true,
        counts: {
          EG000: { affected: 0, at_risk: 64, events: null },
          EG001: { affected: 1, at_risk: 63, events: null },
        },
        organ: "Psychiatric disorders",
        organ_key: "psychiatric",
        vocabulary: "MedDRA 24.0",
        systematic: true,
      },
    ],
    threshold: 5,
    time_frame: "Day 1 through Week 14",
    description: null,
  },
  limitations: null,
  agreement: {
    pi_sponsor_employee: false,
    restrictive: true,
    restriction: "LTE60",
    details: null,
  },
};

describe("a trial's results", () => {
  it("shows each module with a column per group", async () => {
    renderWithProviders(<Results results={RESULTS} />);

    const flow = screen.getByText("Participant flow").closest("[data-slot=card]") as HTMLElement;
    expect(within(flow).getByText("Completed")).toBeInTheDocument();
    expect(within(flow).getByText("(89.1%)")).toBeInTheDocument(); // 57 of 64
    expect(within(flow).getByText("Withdrawal by Subject")).toBeInTheDocument();

    const baseline = screen.getByText("Baseline characteristics").closest("[data-slot=card]");
    expect(within(baseline as HTMLElement).getByText("Mean (SD), years")).toBeInTheDocument();
    expect(within(baseline as HTMLElement).getByText("(96.1%)")).toBeInTheDocument(); // 122/127

    // The primary outcome starts open, with its analysis.
    const analysis = screen.getByTestId("analysis");
    expect(analysis).toHaveTextContent("Valbenazine vs Placebo");
    expect(analysis).toHaveTextContent("-3.16(95% CI -4.37 to -1.95)");
    expect(within(analysis).getByText("<0.0001")).toHaveClass("text-good");

    const safety = screen.getByText("Adverse events").closest("[data-slot=card]") as HTMLElement;
    expect(within(safety).getAllByText("Placebo (placebo)").length).toBeGreaterThan(0);
    expect(within(safety).getByText("Psychotic disorder")).toBeInTheDocument();
    expect(within(safety).getByText(/listed when more than 5% of an arm/)).toBeInTheDocument();

    expect(screen.getByText(/review results for up to 60 days/)).toBeInTheDocument();
    expect(screen.queryByText(/point of contact/i)).not.toBeInTheDocument();
  });

  it("folds secondary outcomes until opened", async () => {
    const secondary = { ...RESULTS.outcomes[0], type: "SECONDARY" } as TrialResults["outcomes"][0];
    renderWithProviders(<Results results={{ ...RESULTS, outcomes: [secondary] }} />);

    expect(screen.queryByTestId("analysis")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText(secondary.title));
    expect(screen.getByTestId("analysis")).toBeInTheDocument();
  });
});

describe("significance", () => {
  it("reads p-values as the registry writes them", () => {
    expect(significance("<0.0001")).toBe(true);
    expect(significance("0.032")).toBe(true);
    expect(significance("0.05")).toBe(false);
    expect(significance("≤0.05")).toBe(true);
    expect(significance("0.363")).toBe(false);
    expect(significance("NA")).toBe(false);
    expect(significance(null)).toBe(false);
  });
});
