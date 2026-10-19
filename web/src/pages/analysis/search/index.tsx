/**
 * Advanced search: trials by the words in chosen parts of them (title, conditions,
 * interventions, summary, inclusion or exclusion criteria, primary or secondary outcomes), whom
 * they take, how they're designed and where they run, within the page's filter
 * (`/api/search/advanced`). The search is in the URL beside the filter (`lib/advanced.ts`), so
 * it can be shared; the form edits a draft until Search.
 */
import { getRouteApi, Link } from "@tanstack/react-router";
import { ScanSearch } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  type AdvancedSearch,
  apiQuery,
  hasQuery,
  parseAdvancedSearch,
  withoutAdvanced,
} from "@/lib/advanced";
import { parseFilter, type TrialFilter } from "@/lib/filters";
import { SearchForm } from "./form";
import { Results } from "./results";

const route = getRouteApi("/analysis/search");
const analysis = getRouteApi("/analysis");

/** Searches to start from, each a link that fills in the form. */
const EXAMPLES: { label: string; search: AdvancedSearch & TrialFilter }[] = [
  {
    label: "Alzheimer's trials that exclude anticoagulants",
    search: { condition: "alzheimer", exclusion: "anticoag* OR warfarin" },
  },
  { label: "Amyloid PET to enrol", search: { inclusion: '"amyloid PET"~3' } },
  { label: "ADAS-Cog as a primary outcome", search: { primary_outcome: "ADAS-Cog" } },
  {
    label: "Randomized, double-blind, placebo-controlled",
    search: {
      allocation: ["RANDOMIZED"],
      masking: ["DOUBLE", "TRIPLE", "QUADRUPLE"],
      placebo: true,
    },
  },
  {
    label: "Recruiting near Boston, for a woman of 70",
    search: {
      status: ["RECRUITING"],
      near: "42.3601,-71.0589",
      place: "Boston, Massachusetts, United States",
      within: 50,
      age: "70",
      sex: "FEMALE",
    },
  },
];

export function AdvancedSearchSection() {
  const search = parseAdvancedSearch(route.useSearch());
  const filter = parseFilter(analysis.useSearch());
  const navigate = route.useNavigate();
  const { sort, ...fields } = search;

  const go = (next: AdvancedSearch, replace = false) =>
    void navigate({
      search: (prev) => ({ ...withoutAdvanced(prev), ...next }),
      replace,
      resetScroll: false,
    });

  return (
    <div className="flex flex-col gap-6" data-testid="advanced-search">
      <SearchForm
        key={JSON.stringify(apiQuery({ ...fields, place: undefined }))}
        initial={fields}
        onSubmit={(next) => go(sort ? { ...next, sort } : next)}
        onClear={() => go({})}
      />
      {hasQuery(search) ? (
        <Results
          search={search}
          filter={filter}
          onSort={(next) => go({ ...fields, sort: next }, true)}
        />
      ) : (
        <Intro filter={filter} />
      )}
    </div>
  );
}

function Intro({ filter }: { filter: TrialFilter }) {
  return (
    <Empty className="rounded-xl border border-dashed py-14" data-testid="advanced-intro">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <ScanSearch />
        </EmptyMedia>
        <EmptyTitle>Search by field</EmptyTitle>
        <EmptyDescription>
          Look for words in one part of a trial, such as its exclusion criteria or primary outcomes,
          and for the people, design and places it has. Every field narrows the search, within the
          page's filter. Try one:
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent className="max-w-2xl flex-row flex-wrap justify-center">
        {EXAMPLES.map((example) => (
          <Button key={example.label} asChild variant="outline" size="sm">
            <Link to="/analysis/search" search={{ ...filter, ...example.search }}>
              {example.label}
            </Link>
          </Button>
        ))}
      </EmptyContent>
    </Empty>
  );
}
