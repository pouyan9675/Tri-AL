/**
 * Trial linking: a trial's NCT number in, the trials that share its MeSH conditions and
 * interventions out, by phase (`/api/trials/{source_id}/linked`). The trial and the terms it
 * links by are in the URL (`?trial=NCT04437511&terms=D000544`), and the page's filter
 * narrows the linked trials. A first take, likely to change.
 */
import { useQuery } from "@tanstack/react-query";
import { getRouteApi, Link } from "@tanstack/react-router";
import { Network, SearchIcon, SearchX } from "lucide-react";
import { useState } from "react";
import {
  ApiError,
  type LinkedTrials,
  type LinkTerm,
  type PhaseGroup,
  type TrialSummary,
} from "@/api/client";
import { linkedTrialsQuery, metaQuery } from "@/api/queries";
import { ErrorState } from "@/components/route-states";
import { TrialFacts } from "@/components/trial-facts";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Skeleton } from "@/components/ui/skeleton";
import { activeCount } from "@/lib/filters";
import { formatNumber } from "@/lib/format";
import { useLabels } from "@/lib/labels";
import { cn } from "@/lib/utils";

const route = getRouteApi("/analysis/linking");
const analysis = getRouteApi("/analysis");

// Phase 3 trials of donanemab and lecanemab, to try it with.
const EXAMPLES = ["NCT04437511", "NCT03887455"];

export function LinkingSection() {
  const { trial, terms } = route.useSearch();
  const filter = analysis.useSearch();
  const navigate = route.useNavigate();

  return (
    <div className="flex flex-col gap-6" data-testid="linking">
      <TrialForm
        key={trial}
        trial={trial}
        onSubmit={(id) =>
          void navigate({ search: (prev) => ({ ...prev, trial: id, terms: undefined }) })
        }
      />
      {trial ? (
        <Linked
          sourceId={trial}
          terms={terms}
          onTerms={(codes) =>
            void navigate({
              search: (prev) => ({ ...prev, terms: codes }),
              replace: true,
              resetScroll: false,
            })
          }
        />
      ) : (
        <Empty className="rounded-xl border border-dashed py-16">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Network />
            </EmptyMedia>
            <EmptyTitle>Link a trial</EmptyTitle>
            <EmptyDescription>
              Enter a trial's NCT number to see the trials that share its conditions and
              interventions, by phase.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent className="flex-row justify-center">
            {EXAMPLES.map((id) => (
              <Button key={id} asChild variant="outline" size="sm">
                <Link to="/analysis/linking" search={{ ...filter, trial: id }}>
                  <span className="font-mono">{id}</span>
                </Link>
              </Button>
            ))}
          </EmptyContent>
        </Empty>
      )}
    </div>
  );
}

function TrialForm({
  trial,
  onSubmit,
}: {
  trial: string | undefined;
  onSubmit: (sourceId: string) => void;
}) {
  const [value, setValue] = useState(trial ?? "");
  return (
    <form
      className="flex w-full max-w-xl gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        const id = value.trim().toUpperCase();
        if (id) onSubmit(id);
      }}
    >
      <InputGroup>
        <InputGroupAddon>
          <SearchIcon />
        </InputGroupAddon>
        <InputGroupInput
          aria-label="Trial ID"
          placeholder="NCT number, such as NCT04437511"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          className="font-mono placeholder:font-sans"
        />
      </InputGroup>
      <Button type="submit">Find linked trials</Button>
    </form>
  );
}

function Linked({
  sourceId,
  terms,
  onTerms,
}: {
  sourceId: string;
  terms: string[] | undefined;
  onTerms: (codes: string[] | undefined) => void;
}) {
  const filter = analysis.useSearch();
  const linked = useQuery(linkedTrialsQuery(sourceId, terms, filter));

  if (linked.isError) {
    if (linked.error instanceof ApiError && linked.error.status === 404) {
      return (
        <Empty className="rounded-xl border border-dashed py-16">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <SearchX />
            </EmptyMedia>
            <EmptyTitle>No trial {sourceId}</EmptyTitle>
            <EmptyDescription>
              It isn't in the database. Check the number, or update the data in Settings.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      );
    }
    return <ErrorState error={linked.error} onRetry={() => void linked.refetch()} />;
  }
  if (!linked.data) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-16 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }
  const data = linked.data;
  return (
    <div
      className={cn(
        "flex flex-col gap-6 transition-opacity",
        linked.isPlaceholderData && "opacity-60",
      )}
    >
      <Seed trial={data.trial} />
      <TermPicker terms={data.terms} onChange={onTerms} />
      <Results data={data} filtered={activeCount(filter) > 0} />
    </div>
  );
}

function Seed({ trial }: { trial: TrialSummary }) {
  const label = useLabels();
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border bg-card p-4" data-testid="seed">
      <div className="text-xs font-medium text-muted-foreground">Linking from</div>
      <Link
        to="/trials/$sourceId"
        params={{ sourceId: trial.source_id }}
        className="font-medium text-balance decoration-muted-foreground/40 underline-offset-2 hover:underline"
      >
        {trial.title}
      </Link>
      <TrialFacts trial={trial} phase={trial.phase ? label("phase", trial.phase) : "No phase"} />
    </div>
  );
}

const KINDS = [
  { kind: "condition", title: "Conditions" },
  { kind: "intervention", title: "Interventions" },
] as const;

/** The trial's own MeSH terms, each on or off; at least one stays on. */
function TermPicker({
  terms,
  onChange,
}: {
  terms: LinkTerm[];
  onChange: (codes: string[] | undefined) => void;
}) {
  const selected = terms.filter((term) => term.selected).map((term) => term.code);
  const toggle = (code: string) => {
    const next = selected.includes(code)
      ? selected.filter((other) => other !== code)
      : [...selected, code];
    onChange(next.length === terms.length ? undefined : next);
  };
  const by = (kind: string) => terms.some((term) => term.kind === kind && term.selected);
  const rule =
    by("condition") && by("intervention")
      ? "Linked trials share at least one selected condition and one selected intervention."
      : by("condition")
        ? "Linked trials share at least one selected condition; no intervention is selected."
        : "Linked trials share at least one selected intervention; no condition is selected.";

  if (terms.length === 0) return null;
  return (
    <div className="flex flex-col gap-3" data-testid="terms">
      {KINDS.map(({ kind, title }) => {
        const own = terms.filter((term) => term.kind === kind);
        return (
          <div key={kind} className="flex flex-col gap-1.5 sm:flex-row sm:gap-3">
            <div className="w-28 shrink-0 pt-1.5 text-xs font-medium text-muted-foreground">
              {title}
            </div>
            {own.length > 0 ? (
              <fieldset className="flex min-w-0 flex-wrap gap-1.5" aria-label={title}>
                {own.map((term) => (
                  <button
                    key={term.code}
                    type="button"
                    aria-pressed={term.selected}
                    disabled={term.selected && selected.length === 1}
                    onClick={() => toggle(term.code)}
                    title={`MeSH ${term.code}`}
                    className={cn(
                      "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs transition-colors focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none disabled:cursor-not-allowed",
                      term.selected
                        ? "border-brand/40 bg-brand/10 font-medium text-foreground"
                        : "border-dashed text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {term.term}
                    {term.selected && (
                      <span className="font-normal text-muted-foreground tabular">
                        {formatNumber(term.trials)}
                      </span>
                    )}
                  </button>
                ))}
              </fieldset>
            ) : (
              <div className="pt-1.5 text-xs text-muted-foreground">
                None: ClinicalTrials.gov gave this trial no MeSH {kind} terms.
              </div>
            )}
          </div>
        );
      })}
      <p className="text-xs text-muted-foreground">
        {rule} These are the MeSH terms ClinicalTrials.gov assigns; the numbers are the linked
        trials with each.
      </p>
    </div>
  );
}

const NO_PHASE = "none";

function Results({ data, filtered }: { data: LinkedTrials; filtered: boolean }) {
  const label = useLabels();
  const { data: meta } = useQuery(metaQuery());
  const names = new Map(data.terms.map((term) => [term.code, term.term]));

  if (data.terms.length === 0) {
    return (
      <Empty className="rounded-xl border border-dashed py-12">
        <EmptyHeader>
          <EmptyTitle>Nothing to link by</EmptyTitle>
          <EmptyDescription>
            ClinicalTrials.gov gave this trial no MeSH terms for its conditions or interventions.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }
  if (data.total === 0) {
    return (
      <Empty className="rounded-xl border border-dashed py-12">
        <EmptyHeader>
          <EmptyTitle>No linked trials</EmptyTitle>
          <EmptyDescription>
            No other trial{filtered ? " within the filter" : ""} shares the selected terms. Try
            turning some terms off.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  // Every clinical phase, found or not, so the pipeline reads left to right; "Not
  // applicable" and no phase only when there are some.
  const found = new Map(data.phases.map((group) => [group.phase ?? NO_PHASE, group]));
  const phases = [...Object.keys(meta?.labels.phase ?? {}), NO_PHASE].filter(
    (phase) => found.has(phase) || (phase !== "NA" && phase !== NO_PHASE),
  );
  const phaseLabel = (phase: string) => (phase === NO_PHASE ? "No phase" : label("phase", phase));

  return (
    <div className="flex flex-col gap-6" data-testid="linked">
      <div className="flex flex-col gap-2">
        <h2 className="text-base font-semibold tracking-tight">
          <span className="tabular">{formatNumber(data.total)}</span> linked{" "}
          {data.total === 1 ? "trial" : "trials"}
        </h2>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-2">
          {phases.map((phase) => {
            const group = found.get(phase);
            return (
              <button
                key={phase}
                type="button"
                disabled={!group}
                onClick={() =>
                  document
                    .getElementById(`phase-${phase}`)
                    ?.scrollIntoView({ behavior: "smooth", block: "start" })
                }
                className="flex flex-col items-start gap-0.5 rounded-lg border bg-card px-3 py-2 text-left transition-colors hover:bg-muted/60 disabled:bg-transparent disabled:opacity-50"
              >
                <span className="text-xs text-muted-foreground">{phaseLabel(phase)}</span>
                <span className="text-lg font-semibold tabular">
                  {formatNumber(group?.total ?? 0)}
                </span>
              </button>
            );
          })}
        </div>
      </div>
      {data.phases.map((group) => (
        <PhaseList
          key={group.phase ?? NO_PHASE}
          id={`phase-${group.phase ?? NO_PHASE}`}
          title={phaseLabel(group.phase ?? NO_PHASE)}
          group={group}
          names={names}
        />
      ))}
    </div>
  );
}

function PhaseList({
  id,
  title,
  group,
  names,
}: {
  id: string;
  title: string;
  group: PhaseGroup;
  names: Map<string, string>;
}) {
  return (
    <section id={id} aria-label={title} className="flex scroll-mt-20 flex-col gap-3">
      <div className="flex items-center gap-3">
        <h3 className="text-sm font-semibold tracking-tight">{title}</h3>
        <span className="text-xs text-muted-foreground tabular">
          {formatNumber(group.total)} {group.total === 1 ? "trial" : "trials"}
        </span>
        <div className="h-px flex-1 bg-border" />
      </div>
      <ul className="divide-y rounded-xl border bg-card">
        {group.trials.map(({ trial, shared }) => (
          <li key={trial.id} className="flex min-w-0 flex-col gap-1 px-4 py-3">
            <Link
              to="/trials/$sourceId"
              params={{ sourceId: trial.source_id }}
              className="line-clamp-2 text-sm font-medium decoration-muted-foreground/40 underline-offset-2 hover:underline"
            >
              {trial.title}
            </Link>
            <TrialFacts trial={trial} />
            <div className="text-xs text-muted-foreground">
              Shares {shared.map((code) => names.get(code) ?? code).join(" · ")}
            </div>
          </li>
        ))}
      </ul>
      {group.total > group.trials.length && (
        <p className="text-xs text-muted-foreground">
          Showing the {formatNumber(group.trials.length)} that share the most terms, of{" "}
          {formatNumber(group.total)}.
        </p>
      )}
    </section>
  );
}
