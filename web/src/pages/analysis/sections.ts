/**
 * The analysis page's sections, each its own route under `/analysis`. The sidebar and the
 * router use this module, so it stays small: it's in the first chunk.
 */
import { ChartScatter, HeartPulse, type LucideIcon, Network, Pill, ScanSearch } from "lucide-react";

export type AnalysisSection = {
  to:
    | "/analysis"
    | "/analysis/linking"
    | "/analysis/search"
    | "/analysis/conditions"
    | "/analysis/interventions";
  label: string;
  description: string;
  icon: LucideIcon;
};

export const ANALYSIS_SECTIONS: readonly AnalysisSection[] = [
  {
    to: "/analysis",
    label: "Landscape",
    description: "The trials seen through their text: where they sit by what they're about.",
    icon: ChartScatter,
  },
  {
    to: "/analysis/linking",
    label: "Trial linking",
    description: "How trials relate to one another.",
    icon: Network,
  },
  {
    to: "/analysis/search",
    label: "Advanced search",
    description: "Finding trials by more than keywords and filters.",
    icon: ScanSearch,
  },
  {
    to: "/analysis/conditions",
    label: "Conditions",
    description: "The conditions trials study, across the registry.",
    icon: HeartPulse,
  },
  {
    to: "/analysis/interventions",
    label: "Interventions",
    description: "The drugs, devices and other interventions trials test.",
    icon: Pill,
  },
];

/** The section at a path (`/analysis` itself is the landscape). */
export function analysisSection(pathname: string): AnalysisSection {
  const path = pathname.replace(/\/+$/, "");
  return (
    ANALYSIS_SECTIONS.find((section) => section.to === path) ??
    (ANALYSIS_SECTIONS[0] as AnalysisSection)
  );
}

export type LinkingSearch = { trial?: string; terms?: string[] };

/** Trial linking's own search params: the trial (`trial`) and the terms to link by (`terms`). */
export function parseLinkingSearch(search: Record<string, unknown>): LinkingSearch {
  const trial = typeof search.trial === "string" ? search.trial.trim() : "";
  const values = Array.isArray(search.terms) ? search.terms : [search.terms];
  const terms = values.filter((code): code is string => typeof code === "string" && !!code);
  return { ...(trial && { trial }), ...(terms.length > 0 && { terms }) };
}
