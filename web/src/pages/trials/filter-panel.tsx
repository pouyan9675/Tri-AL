/**
 * The explorer's filters: a text box, one section per facet from `/api/dashboard` with the
 * counts from `/api/facets` (each facet ignores its own field, so picking one status still
 * shows what the others would add), and date and enrollment ranges.
 */
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, SearchIcon, X } from "lucide-react";
import { type FormEvent, useEffect, useId, useMemo, useState } from "react";
import type { FacetValue } from "@/api/client";
import { dashboardQuery, facetsQuery, namesQuery } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  FIELD_TITLES,
  joinRange,
  type ListField,
  type RangeField,
  splitRange,
  type TrialFilter,
  toggleValue,
} from "@/lib/filters";
import { formatNumber } from "@/lib/format";
import { useLabels } from "@/lib/labels";
import { cn } from "@/lib/utils";

const FACET_ORDER = [
  "status",
  "phase",
  "study_type",
  "has_results",
  "intervention_types",
  "sponsor_class",
  "countries",
  "conditions",
  "interventions",
  "sponsors",
];

/** Facets with many values get a search box: by name lookup, or by the list itself. */
const NAME_KINDS: Record<string, "condition" | "intervention" | "sponsor"> = {
  conditions: "condition",
  interventions: "intervention",
  sponsors: "sponsor",
};
const OPEN_BY_DEFAULT = new Set(["status", "phase", "study_type", "has_results"]);

export function FilterPanel({
  filter,
  onChange,
}: {
  filter: TrialFilter;
  onChange: (filter: TrialFilter) => void;
}) {
  const dashboard = useQuery(dashboardQuery());
  const facets = useQuery(facetsQuery(filter));
  const specs = useMemo(
    () =>
      [...(dashboard.data?.facets ?? [])].sort(
        (a, b) =>
          (FACET_ORDER.indexOf(a.field) + 1 || 99) - (FACET_ORDER.indexOf(b.field) + 1 || 99),
      ),
    [dashboard.data],
  );

  return (
    <div className="flex flex-col gap-4" data-testid="filter-panel">
      <TextFilter value={filter.q} onChange={(q) => onChange({ ...filter, q })} />
      <div className={cn("divide-y", facets.isPlaceholderData && "opacity-70 transition-opacity")}>
        {specs.length === 0 &&
          [0, 1, 2, 3].map((index) => <Skeleton key={index} className="my-3 h-24 w-full" />)}
        {specs.map((spec) => (
          <FacetSection
            key={spec.field}
            field={spec.field}
            title={spec.title}
            values={facets.data?.facets[spec.field]}
            filter={filter}
            onChange={onChange}
          />
        ))}
        <RangeSection filter={filter} onChange={onChange} />
      </div>
    </div>
  );
}

function TextFilter({ value, onChange }: { value?: string; onChange: (q?: string) => void }) {
  const [text, setText] = useState(value ?? "");
  useEffect(() => setText(value ?? ""), [value]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onChange(text.trim() || undefined);
  };
  return (
    <form onSubmit={submit} className="relative">
      <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        value={text}
        onChange={(event) => setText(event.target.value)}
        onBlur={() => (text.trim() || undefined) !== value && onChange(text.trim() || undefined)}
        placeholder="Words in the trial…"
        aria-label="Filter by words"
        className="h-9 bg-card pr-8 pl-8"
      />
      {text && (
        <button
          type="button"
          aria-label="Clear the words"
          className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground"
          onClick={() => {
            setText("");
            onChange(undefined);
          }}
        >
          <X className="size-3.5" />
        </button>
      )}
    </form>
  );
}

function Section({
  title,
  count,
  defaultOpen,
  children,
}: {
  title: string;
  count?: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Collapsible defaultOpen={defaultOpen} className="group/section py-2.5">
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-md py-1 text-left text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
        <span className="flex-1">{title}</span>
        {count ? (
          <span className="rounded-full bg-brand px-1.5 text-[0.65rem] leading-4 font-semibold text-brand-foreground">
            {count}
          </span>
        ) : null}
        <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[state=closed]/section:-rotate-90" />
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-1.5">{children}</CollapsibleContent>
    </Collapsible>
  );
}

function FacetSection({
  field,
  title,
  values,
  filter,
  onChange,
}: {
  field: string;
  title: string;
  values: FacetValue[] | undefined;
  filter: TrialFilter;
  onChange: (filter: TrialFilter) => void;
}) {
  const label = useLabels();
  const [more, setMore] = useState(false);
  const [search, setSearch] = useState("");
  const isResults = field === "has_results";
  const listField = field as ListField;
  const selected: string[] = isResults
    ? filter.has_results === undefined
      ? []
      : [String(filter.has_results)]
    : (filter[listField] ?? []);

  const kind = NAME_KINDS[field];
  const searchable = kind !== undefined || field === "countries";
  const expanded = useQuery({
    ...facetsQuery(filter, [field], field === "countries" ? 300 : 50),
    enabled: more || (field === "countries" && search.length > 0),
  });
  const names = useQuery({
    ...namesQuery(search),
    enabled: kind !== undefined && search.trim().length >= 3,
  });

  const options = useMemo(() => {
    let list =
      (more || search) && expanded.data ? (expanded.data.facets[field] ?? []) : (values ?? []);
    if (search && field === "countries") {
      const needle = search.toLowerCase();
      list = list.filter((option) => option.label.toLowerCase().includes(needle));
    } else if (search && kind && names.data) {
      const counts = new Map(list.map((option) => [option.value, option.count]));
      list = names.data
        .filter((name) => name.kind === kind)
        .map((name) => ({
          value: name.name,
          label: name.name,
          count: counts.get(name.name) ?? -1,
        }));
    }
    const shown = new Set(list.map((option) => option.value));
    const missing = selected
      .filter((value) => !shown.has(value))
      .map((value) => ({ value, label: label(field, value), count: -1 }));
    return [...missing, ...list];
  }, [more, search, expanded.data, values, field, kind, names.data, selected, label]);

  const toggle = (value: string) => {
    if (isResults) {
      const next = value === "true";
      onChange({ ...filter, has_results: filter.has_results === next ? undefined : next });
    } else {
      onChange(toggleValue(filter, listField, value));
    }
  };

  return (
    <Section
      title={title}
      count={selected.length}
      defaultOpen={OPEN_BY_DEFAULT.has(field) || selected.length > 0}
    >
      {searchable && (
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={field === "countries" ? "Find a country…" : `Find a ${kind}…`}
          aria-label={`Find a ${title.toLowerCase()}`}
          className="mb-1.5 h-8 bg-card text-xs"
        />
      )}
      {values === undefined && !search ? (
        <div className="space-y-2 py-1">
          {[0, 1, 2].map((index) => (
            <Skeleton key={index} className="h-5 w-full" />
          ))}
        </div>
      ) : (
        <ul className={cn("space-y-px", (more || search) && "max-h-72 overflow-y-auto pr-1")}>
          {options.map((option) => (
            <FacetOption
              key={`${option.value}`}
              field={field}
              option={option}
              checked={option.value !== null && selected.includes(option.value)}
              onToggle={toggle}
            />
          ))}
          {options.length === 0 && (
            <li className="px-1 py-1.5 text-xs text-muted-foreground">
              {search && kind && search.trim().length < 3
                ? "Type three letters or more."
                : "Nothing matches."}
            </li>
          )}
        </ul>
      )}
      {!search && !isResults && (values?.length ?? 0) >= 8 && (
        <button
          type="button"
          className="mt-1 px-1 text-xs font-medium text-muted-foreground hover:text-foreground"
          onClick={() => setMore(!more)}
        >
          {more ? "Show fewer" : "Show more"}
        </button>
      )}
    </Section>
  );
}

function FacetOption({
  field,
  option,
  checked,
  onToggle,
}: {
  field: string;
  option: FacetValue;
  checked: boolean;
  onToggle: (value: string) => void;
}) {
  const id = useId();
  const label = useLabels();
  const value = option.value;
  // Trials without a value ("Not given") can be counted but not filtered on.
  const disabled = value === null;
  const text = field === "countries" && value ? label("countries", value) : option.label;
  return (
    <li>
      <label
        htmlFor={id}
        className={cn(
          "flex min-h-7 items-center gap-2.5 rounded-md px-1 py-1 text-[0.8rem] transition-colors",
          disabled ? "text-muted-foreground/70" : "cursor-pointer hover:bg-muted/70",
        )}
      >
        <Checkbox
          id={id}
          checked={checked}
          disabled={disabled}
          onCheckedChange={() => value !== null && onToggle(value)}
        />
        <span className="min-w-0 flex-1 truncate" title={text}>
          {text}
        </span>
        <span className="text-xs tabular text-muted-foreground">
          {option.count >= 0 ? formatNumber(option.count) : ""}
        </span>
      </label>
    </li>
  );
}

const DATE_FIELDS: RangeField[] = ["start", "completion", "first_posted", "last_update"];
const DATE = /^\d{4}(-\d{2}(-\d{2})?)?$/;

function RangeSection({
  filter,
  onChange,
}: {
  filter: TrialFilter;
  onChange: (filter: TrialFilter) => void;
}) {
  const count = [...DATE_FIELDS, "enrollment" as const].filter((field) => filter[field]).length;
  return (
    <Section title="Dates and size" count={count} defaultOpen={count > 0}>
      <div className="space-y-3 pt-1">
        {DATE_FIELDS.map((field) => (
          <RangeInput
            key={field}
            field={field}
            value={filter[field]}
            placeholder={["2015", "2025"]}
            valid={(text) => DATE.test(text)}
            hint="A year, or YYYY-MM-DD"
            onChange={(value) => onChange({ ...filter, [field]: value })}
          />
        ))}
        <RangeInput
          field="enrollment"
          value={filter.enrollment}
          placeholder={["Min", "Max"]}
          valid={(text) => /^\d+$/.test(text)}
          hint="Whole numbers of participants"
          onChange={(value) => onChange({ ...filter, enrollment: value })}
        />
      </div>
    </Section>
  );
}

function RangeInput({
  field,
  value,
  placeholder,
  valid,
  hint,
  onChange,
}: {
  field: RangeField;
  value?: string;
  placeholder: [string, string];
  valid: (text: string) => boolean;
  hint: string;
  onChange: (value?: string) => void;
}) {
  const [from, to] = splitRange(value);
  const [draft, setDraft] = useState<[string, string]>([from, to]);
  useEffect(() => setDraft([from, to]), [from, to]);
  const bad = draft.some((end) => end.trim() !== "" && !valid(end.trim()));
  const commit = () => {
    if (bad) return;
    const next = joinRange(draft[0], draft[1]);
    if (next !== value) onChange(next);
  };
  const title = FIELD_TITLES[field];
  return (
    <div className="space-y-1">
      <div className="text-xs font-medium text-muted-foreground">{title}</div>
      <div className="flex items-center gap-1.5">
        {([0, 1] as const).map((end) => (
          <Input
            key={end}
            value={draft[end]}
            inputMode={field === "enrollment" ? "numeric" : "text"}
            placeholder={placeholder[end]}
            aria-label={`${title} ${end === 0 ? "from" : "to"}`}
            aria-invalid={bad || undefined}
            className="h-8 bg-card text-xs"
            onChange={(event) =>
              setDraft(end === 0 ? [event.target.value, draft[1]] : [draft[0], event.target.value])
            }
            onBlur={commit}
            onKeyDown={(event) => event.key === "Enter" && commit()}
          />
        ))}
        {value && (
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Clear ${title}`}
            className="shrink-0 text-muted-foreground"
            onClick={() => onChange(undefined)}
          >
            <X />
          </Button>
        )}
      </div>
      {bad && <div className="text-[0.7rem] text-destructive">{hint}</div>}
    </div>
  );
}
