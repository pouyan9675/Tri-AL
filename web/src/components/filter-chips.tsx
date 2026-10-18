import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { type Chip, chips, FIELD_TITLES, splitRange, type TrialFilter } from "@/lib/filters";
import { formatNumber } from "@/lib/format";
import { useLabels } from "@/lib/labels";

const CODED = new Set([
  "status",
  "phase",
  "study_type",
  "sponsor_class",
  "intervention_types",
  "countries",
]);

function describe(chip: Chip, label: (field: string, code: string) => string): string {
  const { field, value } = chip;
  if (field === "q") return `“${value}”`;
  if (field === "has_results") return value === "true" ? "Has results" : "No results";
  if (field === "enrollment") {
    const [from, to] = splitRange(value).map((end) => (end ? formatNumber(Number(end)) : ""));
    if (from && to) return `Enrollment ${from}–${to}`;
    return from ? `Enrollment ≥ ${from}` : `Enrollment ≤ ${to}`;
  }
  if (
    field === "start" ||
    field === "completion" ||
    field === "first_posted" ||
    field === "last_update"
  ) {
    const [from, to] = splitRange(value);
    const title = FIELD_TITLES[field];
    if (from && to) return `${title} ${from} – ${to}`;
    return from ? `${title} from ${from}` : `${title} until ${to}`;
  }
  return CODED.has(field) ? label(field, value) : value;
}

/** The active filter as removable chips, with "Clear all". */
export function FilterChips({
  filter,
  onChange,
}: {
  filter: TrialFilter;
  onChange: (filter: TrialFilter) => void;
}) {
  const label = useLabels();
  const list = chips(filter);
  if (!list.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="filter-chips">
      {list.map((chip) => (
        <span
          key={`${chip.field}:${chip.value}`}
          className="inline-flex h-7 max-w-full items-center gap-1 rounded-full border bg-card pr-1 pl-2.5 text-xs shadow-xs"
        >
          <span className="text-muted-foreground">{FIELD_TITLES[chip.field]}:</span>
          <span className="truncate font-medium">{describe(chip, label)}</span>
          <button
            type="button"
            className="ml-0.5 rounded-full p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label={`Remove ${FIELD_TITLES[chip.field]} ${chip.value}`}
            onClick={() => onChange(chip.remove)}
          >
            <X className="size-3" />
          </button>
        </span>
      ))}
      <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => onChange({})}>
        Clear all
      </Button>
    </div>
  );
}
