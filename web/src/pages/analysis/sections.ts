/**
 * The analysis page's sections, each its own route under `/analysis`. The sidebar and the
 * router use this module, so it stays small: it's in the first chunk.
 */
import {
  ChartScatter,
  ClipboardCheck,
  HeartPulse,
  type LucideIcon,
  Network,
  Pill,
  ScanSearch,
} from "lucide-react";

export type AnalysisSection = {
  to:
    | "/analysis"
    | "/analysis/results"
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
    to: "/analysis/results",
    label: "Results",
    description: "What posted results say: who took part, safety, whether it worked, who finished.",
    icon: ClipboardCheck,
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
    description: "One condition in depth: its trials over time, what goes with it, how they end.",
    icon: HeartPulse,
  },
  {
    to: "/analysis/interventions",
    label: "Interventions",
    description: "One drug, device or other intervention in depth: where and how it's tested.",
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

export type TermSearch = { term?: string };

/** The Conditions and Interventions sections' own search param: the MeSH code (`term`). */
export function parseTermSearch(search: Record<string, unknown>): TermSearch {
  const term = typeof search.term === "string" ? search.term.trim().toUpperCase() : "";
  return term ? { term } : {};
}
