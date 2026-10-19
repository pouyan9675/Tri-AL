/**
 * The ⌘K palette: trials by ID (one, a pasted list, or the start of one as it's typed),
 * full-text search over every trial (`/api/search`), names that jump to a filter, and the
 * pages. Loaded on first use. A broad search ranks only the newest matches (the API's
 * `capped`), and the palette says so.
 */
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import {
  Activity,
  ArrowRight,
  Building2,
  Info,
  LayoutDashboard,
  Monitor,
  Moon,
  Orbit,
  Pill,
  Settings2,
  Sun,
  TableProperties,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { NameHit, SearchHit, SearchResult } from "@/api/client";
import { metaQuery, searchQuery } from "@/api/queries";
import { Snippet } from "@/components/snippet";
import { StatusBadge } from "@/components/status-badge";
import {
  Command,
  CommandDialog,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { Kbd } from "@/components/ui/kbd";
import { Spinner } from "@/components/ui/spinner";
import { formatNumber } from "@/lib/format";
import { useLabels } from "@/lib/labels";
import { useTheme } from "@/lib/theme";
import { useDebounced } from "@/lib/use-debounced";

const NAME_FIELD = {
  condition: "conditions",
  intervention: "interventions",
  sponsor: "sponsors",
} as const;
const NAME_ICON = { condition: Activity, intervention: Pill, sponsor: Building2 } as const;
/** What the API strips from the ends of an ID it's given (`trial_id_terms`). */
const ID_EDGES = /^["'`()[\]{}<>.:#]+|["'`()[\]{}<>.:#]+$/g;

export default function CommandPalette({
  open,
  onOpenChange,
  takeTyped,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Keys typed while the palette was opening; asked for once its input has focus. */
  takeTyped?: () => string;
}) {
  const [text, setText] = useState("");
  const input = useRef<HTMLInputElement>(null);
  // Focus the input ourselves (Radix would select its text), taking what was typed while
  // the palette opened, with the caret after it.
  const focusInput = (event: Event) => {
    event.preventDefault();
    const early = takeTyped?.() ?? "";
    if (early) setText((current) => current + early);
    input.current?.focus();
    requestAnimationFrame(() => {
      const element = input.current;
      if (element) element.setSelectionRange(element.value.length, element.value.length);
    });
  };
  const q = useDebounced(text.trim(), 160);
  const search = useQuery(searchQuery(q));
  const meta = useQuery(metaQuery());
  const navigate = useNavigate();
  const { setTheme } = useTheme();
  const result = q && search.data?.query === q ? search.data : q ? search.data : undefined;
  const pending = q !== text.trim() || search.isFetching;
  const byId = result?.hits.filter((hit) => hit.id_match) ?? [];
  const byText = result?.hits.filter((hit) => !hit.id_match) ?? [];
  const exact = byId.filter((hit) => hit.id_match === "exact");
  const started = byId.filter((hit) => hit.id_match === "prefix");
  // The trial list matches whole IDs and words, not the start of an ID.
  const listable = result ? byText.length > 0 || exact.length > 0 || !started.length : false;

  // New results select their first row, so Enter opens the best match.
  const [selected, setSelected] = useState("");
  const first = result?.hits[0]
    ? `trial-${result.hits[0].id}`
    : result?.names[0]
      ? `name-${result.names[0].kind}-${result.names[0].id}`
      : "";
  useEffect(() => setSelected(q ? first : ""), [q, first]);

  const go = (action: () => void) => {
    onOpenChange(false);
    setText("");
    action();
  };
  const openTrial = (hit: SearchHit) =>
    go(() => void navigate({ to: "/trials/$sourceId", params: { sourceId: hit.source_id } }));
  const openName = (name: NameHit) =>
    go(() => void navigate({ to: "/trials", search: { [NAME_FIELD[name.kind]]: [name.name] } }));

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Search"
      description="Search trials, conditions, interventions and sponsors."
      className="top-[12vh] sm:max-w-2xl"
      onOpenAutoFocus={focusInput}
    >
      <Command
        shouldFilter={false}
        loop
        value={selected}
        onValueChange={setSelected}
        className="bg-popover"
      >
        <div className="relative">
          <CommandInput
            ref={input}
            value={text}
            onValueChange={setText}
            placeholder={
              meta.data
                ? `Search ${formatNumber(meta.data.trials)} trials or NCT IDs…`
                : "Search trials or NCT IDs…"
            }
            className="h-10"
          />
          {pending && q && (
            <Spinner className="absolute top-1/2 right-4 size-4 -translate-y-1/2 text-muted-foreground" />
          )}
        </div>
        <CommandList className="max-h-[min(62vh,34rem)] px-1 pb-1" data-testid="palette-results">
          {!q && (
            <>
              <CommandGroup heading="Go to">
                <CommandItem onSelect={() => go(() => void navigate({ to: "/" }))}>
                  <LayoutDashboard /> Dashboard
                </CommandItem>
                <CommandItem onSelect={() => go(() => void navigate({ to: "/analysis" }))}>
                  <Orbit /> Analysis
                </CommandItem>
                <CommandItem onSelect={() => go(() => void navigate({ to: "/trials" }))}>
                  <TableProperties /> Trials
                </CommandItem>
                <CommandItem onSelect={() => go(() => void navigate({ to: "/settings" }))}>
                  <Settings2 /> Settings
                </CommandItem>
              </CommandGroup>
              <CommandSeparator />
              <CommandGroup heading="Theme">
                <CommandItem onSelect={() => go(() => setTheme("light"))}>
                  <Sun /> Light
                </CommandItem>
                <CommandItem onSelect={() => go(() => setTheme("dark"))}>
                  <Moon /> Dark
                </CommandItem>
                <CommandItem onSelect={() => go(() => setTheme("system"))}>
                  <Monitor /> System
                </CommandItem>
              </CommandGroup>
              <p className="px-3 pt-2 pb-3 text-xs text-muted-foreground">
                Type a drug, a condition or a sponsor (every word must match), or one or more NCT
                numbers.
              </p>
            </>
          )}
          {q && result && (
            <>
              {result.capped && (
                <div
                  className="mx-1 mt-1.5 flex items-start gap-2 rounded-lg border border-info/25 bg-info/8 px-3 py-2 text-xs"
                  data-testid="capped-notice"
                >
                  <Info className="mt-px size-3.5 shrink-0 text-info" />
                  <span>
                    <span className="font-medium">Broad search.</span> More trials match than are
                    ranked, so these are the best of the{" "}
                    {formatNumber(result.candidates ?? meta.data?.search_candidates ?? 0)} most
                    recently registered. Add a word to narrow it.
                  </span>
                </div>
              )}
              {exact.length > 0 && (
                <CommandGroup heading={exact.length === 1 ? "Trial ID" : "Trial IDs"}>
                  {exact.map((hit) => (
                    <TrialItem key={hit.id} hit={hit} q={q} onSelect={() => openTrial(hit)} />
                  ))}
                </CommandGroup>
              )}
              {started.length > 0 && (
                <CommandGroup heading={`Trial IDs starting with ${q.replace(ID_EDGES, "")}`}>
                  {started.map((hit) => (
                    <TrialItem key={hit.id} hit={hit} q={q} onSelect={() => openTrial(hit)} />
                  ))}
                </CommandGroup>
              )}
              {byText.length > 0 && (
                <CommandGroup heading={byId.length > 0 ? "Text matches" : "Trials"}>
                  {byText.map((hit) => (
                    <TrialItem key={hit.id} hit={hit} q={q} onSelect={() => openTrial(hit)} />
                  ))}
                </CommandGroup>
              )}
              {result.names.length > 0 && (
                <CommandGroup heading="Filter the trial list by">
                  {result.names.map((name) => {
                    const Icon = NAME_ICON[name.kind];
                    return (
                      <CommandItem
                        key={`${name.kind}-${name.id}`}
                        value={`name-${name.kind}-${name.id}`}
                        onSelect={() => openName(name)}
                      >
                        <Icon className="text-muted-foreground" />
                        <span className="truncate">{name.name}</span>
                        <span className="ml-auto pl-3 text-xs text-muted-foreground capitalize">
                          {name.kind}
                        </span>
                      </CommandItem>
                    );
                  })}
                </CommandGroup>
              )}
              {listable && (
                <CommandGroup>
                  <CommandItem
                    value="all-results"
                    onSelect={() => go(() => void navigate({ to: "/trials", search: { q } }))}
                  >
                    <ArrowRight className="text-muted-foreground" />
                    <span>
                      List every trial with “<span className="font-medium">{q}</span>”
                    </span>
                  </CommandItem>
                </CommandGroup>
              )}
              {result.hits.length === 0 && result.names.length === 0 && !pending && (
                <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                  No trials match “{q}”.
                </p>
              )}
            </>
          )}
          {q && !result && search.isError && (
            <p className="px-3 py-6 text-center text-sm text-destructive">{search.error.message}</p>
          )}
        </CommandList>
        <div className="flex items-center gap-3 border-t px-3 py-2 text-[0.7rem] text-muted-foreground">
          <span className="flex items-center gap-1">
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd> move
          </span>
          <span className="flex items-center gap-1">
            <Kbd>↵</Kbd> open
          </span>
          <span className="flex items-center gap-1">
            <Kbd>esc</Kbd> close
          </span>
          {q && result && <span className="ml-auto tabular">{countLine(result, byId.length)}</span>}
        </div>
      </Command>
    </CommandDialog>
  );
}

/** The footer's counts: the trials found by ID, then the text matches ranked. */
function countLine({ candidates, capped }: SearchResult, byId: number) {
  const parts = byId > 0 ? [`${formatNumber(byId)} by ID`] : [];
  if (candidates !== null && (candidates > 0 || byId === 0)) {
    const kind = byId > 0 ? "text match" : "match";
    parts.push(
      capped
        ? `${formatNumber(candidates)} newest ranked`
        : `${formatNumber(candidates)} ${kind}${candidates === 1 ? "" : "es"}`,
    );
  }
  return parts.join(" · ");
}

/** How much of the hit's ID the query matched: all of it, its start, or none. */
function matchedLength(hit: SearchHit, q: string) {
  if (hit.id_match === "exact") return hit.source_id.length;
  if (hit.id_match !== "prefix") return 0;
  const typed = q.replace(ID_EDGES, "").toUpperCase();
  return hit.source_id.toUpperCase().startsWith(typed) ? typed.length : 0;
}

// No padding, so the ID still reads as one word where the match ends.
const ID_MARK = "rounded-[2px] bg-brand/15 font-medium text-foreground dark:bg-brand/30";

function TrialItem({ hit, q, onSelect }: { hit: SearchHit; q: string; onSelect: () => void }) {
  const label = useLabels();
  const matched = matchedLength(hit, q);
  return (
    <CommandItem value={`trial-${hit.id}`} onSelect={onSelect} className="items-start gap-3 py-2">
      <div className="min-w-0 flex-1 space-y-1">
        <div className="line-clamp-2 font-medium sm:line-clamp-1">{hit.title}</div>
        {hit.snippet.length > 0 && (
          <div className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
            <Snippet parts={hit.snippet} />
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="font-mono text-[0.7rem]" data-testid="hit-id">
            {matched > 0 ? (
              <>
                <mark className={ID_MARK}>{hit.source_id.slice(0, matched)}</mark>
                {hit.source_id.slice(matched)}
              </>
            ) : (
              hit.source_id
            )}
          </span>
          {hit.phase && hit.phase !== "NA" && <span>· {label("phase", hit.phase)}</span>}
        </div>
      </div>
      <StatusBadge status={hit.status} className="mt-0.5 hidden sm:inline-flex" />
    </CommandItem>
  );
}
