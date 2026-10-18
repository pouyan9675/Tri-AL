/**
 * `TrialFilter` in the URL. Search params use the API's own format, so a page's URL and its
 * API requests carry the same query: repeated fields for several values
 * (`?status=RECRUITING&status=COMPLETED`) and `from..to` ranges (`start=2020..2023`).
 */
import type { SortKey } from "@/api/client";

export const LIST_FIELDS = [
  "status",
  "phase",
  "study_type",
  "conditions",
  "mesh",
  "interventions",
  "intervention_types",
  "sponsors",
  "sponsor_class",
  "countries",
] as const;
export type ListField = (typeof LIST_FIELDS)[number];

export const RANGE_FIELDS = ["start", "completion", "first_posted", "last_update", "enrollment"];
export type RangeField = "start" | "completion" | "first_posted" | "last_update" | "enrollment";

export type TrialFilter = { [F in ListField]?: string[] } & { [F in RangeField]?: string } & {
  has_results?: boolean;
  q?: string;
};

export const SORT_KEYS = [
  "-last_update",
  "last_update",
  "-start_date",
  "start_date",
  "-first_posted",
  "first_posted",
  "-enrollment",
  "enrollment",
  "-id",
  "id",
] as const satisfies readonly SortKey[];
export const DEFAULT_SORT: SortKey = "-last_update";

export type TrialsSearch = TrialFilter & { sort?: SortKey };

export const FIELD_TITLES: Record<ListField | RangeField | "has_results" | "q", string> = {
  status: "Status",
  phase: "Phase",
  study_type: "Study type",
  conditions: "Condition",
  mesh: "MeSH term",
  interventions: "Intervention",
  intervention_types: "Intervention type",
  sponsors: "Sponsor",
  sponsor_class: "Lead sponsor type",
  countries: "Country",
  start: "Start",
  completion: "Completion",
  first_posted: "First posted",
  last_update: "Last update",
  enrollment: "Enrollment",
  has_results: "Results",
  q: "Text",
};

function strings(value: unknown): string[] {
  const values = Array.isArray(value) ? value : value === undefined ? [] : [value];
  return values.map((item) => String(item).trim()).filter((item) => item.length > 0);
}

/** A filter from parsed search params, with anything malformed dropped. */
export function parseFilter(search: Record<string, unknown>): TrialFilter {
  const filter: TrialFilter = {};
  for (const field of LIST_FIELDS) {
    const values = [...new Set(strings(search[field]))];
    if (values.length) filter[field] = values;
  }
  for (const field of RANGE_FIELDS as RangeField[]) {
    const [value] = strings(search[field]);
    if (value?.includes("..") && value !== "..") filter[field] = value;
  }
  const [results] = strings(search.has_results);
  if (results === "true" || results === "false") filter.has_results = results === "true";
  const [q] = strings(search.q);
  if (q) filter.q = q;
  return filter;
}

export function parseTrialsSearch(search: Record<string, unknown>): TrialsSearch {
  const filter: TrialsSearch = parseFilter(search);
  const [sort] = strings(search.sort);
  if (sort && sort !== DEFAULT_SORT && (SORT_KEYS as readonly string[]).includes(sort)) {
    filter.sort = sort as SortKey;
  }
  return filter;
}

/** The same filter with its values sorted, so equal filters make equal query keys. */
export function canonical(filter: TrialFilter): TrialFilter {
  const out: TrialFilter = {};
  for (const key of Object.keys(filter).sort() as (keyof TrialFilter)[]) {
    const value = filter[key];
    if (value === undefined) continue;
    (out as Record<string, unknown>)[key] = Array.isArray(value) ? [...value].sort() : value;
  }
  return out;
}

/** Just the filter fields of a page's search params (no sort, no tab). */
export function onlyFilter(search: TrialsSearch): TrialFilter {
  const { sort: _sort, ...filter } = search;
  return parseFilter(filter);
}

export function activeCount(filter: TrialFilter): number {
  let count = 0;
  for (const field of LIST_FIELDS) count += filter[field]?.length ?? 0;
  for (const field of RANGE_FIELDS as RangeField[]) if (filter[field]) count += 1;
  if (filter.has_results !== undefined) count += 1;
  if (filter.q) count += 1;
  return count;
}

export function toggleValue(filter: TrialFilter, field: ListField, value: string): TrialFilter {
  const current = filter[field] ?? [];
  const next = current.includes(value)
    ? current.filter((item) => item !== value)
    : [...current, value];
  return { ...filter, [field]: next.length ? next : undefined };
}

export type Chip = { field: keyof TrialFilter; value: string; remove: TrialFilter };

/** One removable chip per active value, in field order. */
export function chips(filter: TrialFilter): Chip[] {
  const out: Chip[] = [];
  if (filter.q) out.push({ field: "q", value: filter.q, remove: { ...filter, q: undefined } });
  for (const field of LIST_FIELDS) {
    for (const value of filter[field] ?? []) {
      out.push({ field, value, remove: toggleValue(filter, field, value) });
    }
  }
  for (const field of RANGE_FIELDS as RangeField[]) {
    const value = filter[field];
    if (value) out.push({ field, value, remove: { ...filter, [field]: undefined } });
  }
  if (filter.has_results !== undefined) {
    out.push({
      field: "has_results",
      value: filter.has_results ? "true" : "false",
      remove: { ...filter, has_results: undefined },
    });
  }
  return out;
}

/** `from..to` split into its ends ("" for an open end). */
export function splitRange(value: string | undefined): [string, string] {
  if (!value) return ["", ""];
  const [from = "", to = ""] = value.split("..");
  return [from, to];
}

export function joinRange(from: string, to: string): string | undefined {
  const a = from.trim();
  const b = to.trim();
  return a || b ? `${a}..${b}` : undefined;
}
