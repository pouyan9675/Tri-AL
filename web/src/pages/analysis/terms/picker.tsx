/** Choosing a term: a searchable list of MeSH terms of one kind, with their trials. */
import { useQuery } from "@tanstack/react-query";
import { ChevronsUpDown, HeartPulse, Pill, SearchIcon } from "lucide-react";
import { useState } from "react";
import type { TermCount, TermKind } from "@/api/client";
import { findTermsQuery } from "@/api/terms";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { formatNumber } from "@/lib/format";
import { useDebounced } from "@/lib/use-debounced";
import { KINDS } from "./common";

export function TermPicker({
  kind,
  current,
  onChoose,
}: {
  kind: TermKind;
  current: { code: string; term: string } | undefined;
  onChoose: (code: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const typed = useDebounced(q, 150);
  const found = useQuery({ ...findTermsQuery(kind, typed), enabled: open });
  const terms = found.data?.terms ?? [];
  const { one, many } = KINDS[kind];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-label={`Choose a ${one}`}
          className="h-9 w-full max-w-xl justify-between font-normal"
        >
          <span className="flex min-w-0 items-center gap-2">
            <SearchIcon className="text-muted-foreground" />
            {current ? (
              <span className="truncate font-medium">{current.term}</span>
            ) : (
              <span className="text-muted-foreground">Find a {one} by its MeSH name…</span>
            )}
          </span>
          <ChevronsUpDown className="text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-(--radix-popover-trigger-width) p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder={`Search ${many}: Alzheimer, donepezil, D000544…`}
            value={q}
            onValueChange={setQ}
          />
          <CommandList>
            <CommandEmpty>
              {found.isFetching ? "Searching…" : `No ${one} matches “${typed}”.`}
            </CommandEmpty>
            {terms.length > 0 && (
              <CommandGroup heading={typed.trim() ? "Matches" : `Most studied ${many}`}>
                {terms.map((term) => (
                  <CommandItem
                    key={term.code}
                    value={term.code}
                    onSelect={() => {
                      onChoose(term.code);
                      setOpen(false);
                    }}
                    className="flex items-center gap-3"
                  >
                    <span className="min-w-0 flex-1 truncate">{term.term}</span>
                    <span className="font-mono text-[0.7rem] text-muted-foreground">
                      {term.code}
                    </span>
                    <span className="w-14 text-right text-xs text-muted-foreground tabular">
                      {formatNumber(term.trials)}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

/** Before a term is chosen: what this section does, and the most studied terms to start. */
export function Suggestions({
  kind,
  onChoose,
}: {
  kind: TermKind;
  onChoose: (code: string) => void;
}) {
  const top = useQuery(findTermsQuery(kind, ""));
  const { one, many, Many } = KINDS[kind];
  const Icon = kind === "condition" ? HeartPulse : Pill;
  return (
    <Empty className="rounded-xl border border-dashed py-14" data-testid="term-suggestions">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Icon />
        </EmptyMedia>
        <EmptyTitle>Choose a {one}</EmptyTitle>
        <EmptyDescription>
          {Many} are MeSH terms, the names ClinicalTrials.gov normalizes them to. Pick one to see
          its trials over time, the {kind === "condition" ? "interventions" : "conditions"} tied to
          it, how its trials end, and its sub-themes. Start with one of the most studied
          {` ${many}`}:
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent className="max-w-2xl flex-row flex-wrap justify-center">
        {(top.data?.terms ?? []).map((term: TermCount) => (
          <Button
            key={term.code}
            variant="outline"
            size="sm"
            onClick={() => onChoose(term.code)}
            className="gap-1.5"
          >
            {term.term}
            <span className="text-xs text-muted-foreground tabular">
              {formatNumber(term.trials)}
            </span>
          </Button>
        ))}
      </EmptyContent>
    </Empty>
  );
}
