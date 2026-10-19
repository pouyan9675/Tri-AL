/**
 * Advanced search in the URL: its fields sit beside the page's filter, in the API's own query
 * format (`?exclusion=warfarin&age=70&masking=DOUBLE&masking=TRIPLE`), so the URL and the
 * request carry the same search. The router validates them for `/analysis/search`, so this
 * module stays small: it's in the first load.
 */
import type { Schemas, SortKey } from "@/api/client";
import { SORT_KEYS } from "./filters";

export type TextField = Schemas["FieldReadOut"]["field"];

export const TEXT_FIELDS = [
  "text",
  "title",
  "condition",
  "intervention",
  "summary",
  "eligibility",
  "inclusion",
  "exclusion",
  "outcome",
  "primary_outcome",
  "secondary_outcome",
] as const satisfies readonly TextField[];

export const DESIGN_FIELDS = [
  "allocation",
  "masking",
  "intervention_model",
  "primary_purpose",
] as const;
export type DesignField = (typeof DESIGN_FIELDS)[number];

export type AdvancedSort = "relevance" | "distance" | SortKey;
export type Sex = "FEMALE" | "MALE";

export type AdvancedSearch = { [F in TextField]?: string } & {
  [F in DesignField]?: string[];
} & {
  age?: string;
  sex?: Sex;
  healthy_volunteers?: boolean;
  placebo?: boolean;
  near?: string;
  within?: number;
  place?: string; // the place's name, for showing; the API reads `near`
  sort?: AdvancedSort;
};

export const FIELDS: Record<TextField, { label: string; placeholder: string }> = {
  text: { label: "Anywhere", placeholder: "tau OR p-tau -preclinical" },
  title: { label: "Title", placeholder: '"amyloid PET"' },
  condition: { label: "Condition", placeholder: "alzheimer" },
  intervention: { label: "Intervention", placeholder: "lecanemab OR BAN2401" },
  summary: { label: "Summary or description", placeholder: "aerobic exercise" },
  eligibility: { label: "Eligibility criteria", placeholder: "MMSE" },
  inclusion: { label: "Inclusion criteria", placeholder: '"amyloid PET"~3' },
  exclusion: { label: "Exclusion criteria", placeholder: "warfarin OR anticoag*" },
  outcome: { label: "Outcome measures", placeholder: "ADAS-Cog" },
  primary_outcome: { label: "Primary outcomes", placeholder: "ADAS-Cog" },
  secondary_outcome: { label: "Secondary outcomes", placeholder: "quality of life" },
};

/** Distances a place can be searched within, in km. */
export const DISTANCES = [10, 25, 50, 100, 250, 500] as const;
export const DEFAULT_DISTANCE = 50;

const AGE = /^\s*(\d{1,3})?\s*(\.\.)?\s*(\d{1,3})?\s*$/;
const POINT = /^-?\d{1,2}(\.\d+)?,-?\d{1,3}(\.\d+)?$/;
const SORTS: readonly string[] = ["relevance", "distance", ...SORT_KEYS];

function first(value: unknown): string | undefined {
  const item = Array.isArray(value) ? value[0] : value;
  if (item === undefined || item === null) return undefined;
  const text = String(item).trim();
  return text || undefined;
}

function all(value: unknown): string[] {
  const values = Array.isArray(value) ? value : value === undefined ? [] : [value];
  return [...new Set(values.map((item) => String(item).trim()).filter(Boolean))];
}

function flag(value: unknown): boolean | undefined {
  const text = first(value);
  return text === "true" ? true : text === "false" ? false : undefined;
}

/** An age (`70`) or a range (`60..80`, `..17`), normalized; undefined if it isn't one. */
export function parseAge(text: string | undefined): string | undefined {
  const match = text === undefined ? null : AGE.exec(text);
  if (!match) return undefined;
  const [, low, range, high] = match;
  if (!range) return low !== undefined && high === undefined ? String(Number(low)) : undefined;
  if (low === undefined && high === undefined) return undefined;
  if (low !== undefined && high !== undefined && Number(low) > Number(high)) return undefined;
  return `${low === undefined ? "" : Number(low)}..${high === undefined ? "" : Number(high)}`;
}

/** The advanced search's own params, with anything malformed dropped. */
export function parseAdvancedSearch(search: Record<string, unknown>): AdvancedSearch {
  const out: AdvancedSearch = {};
  for (const field of TEXT_FIELDS) {
    const text = first(search[field]);
    if (text) out[field] = text;
  }
  for (const field of DESIGN_FIELDS) {
    const values = all(search[field]);
    if (values.length) out[field] = values;
  }
  const age = parseAge(first(search.age));
  if (age) out.age = age;
  const sex = first(search.sex);
  if (sex === "FEMALE" || sex === "MALE") out.sex = sex;
  const healthy = flag(search.healthy_volunteers);
  if (healthy !== undefined) out.healthy_volunteers = healthy;
  const placebo = flag(search.placebo);
  if (placebo !== undefined) out.placebo = placebo;
  const near = first(search.near)?.replace(/\s+/g, "");
  if (near && POINT.test(near)) {
    out.near = near;
    const within = Number(first(search.within));
    if (Number.isFinite(within) && within > 0 && within <= 20_000) out.within = within;
    const place = first(search.place);
    if (place) out.place = place;
  }
  const sort = first(search.sort);
  if (sort && SORTS.includes(sort)) out.sort = sort as AdvancedSort;
  return out;
}

/** Whether there's anything to search for (the sort alone isn't). */
export function hasQuery(search: AdvancedSearch): boolean {
  const { sort: _sort, place: _place, ...fields } = search;
  return Object.keys(fields).length > 0;
}

/** How many of the fields besides text are set: the person, the design and the place. */
export function extraFieldCount(search: AdvancedSearch): number {
  const set = [
    !!search.age?.trim(),
    !!search.sex,
    search.healthy_volunteers !== undefined,
    search.placebo !== undefined,
    !!search.near,
    ...DESIGN_FIELDS.map((field) => (search[field]?.length ?? 0) > 0),
  ];
  return set.filter(Boolean).length;
}

/** The search as the API reads it: no display-only `place`, and arrays sorted (cache keys). */
export function apiQuery(search: AdvancedSearch) {
  const { place: _place, ...query } = search;
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(query).sort() as (keyof typeof query)[]) {
    const value = query[key];
    if (value !== undefined) out[key] = Array.isArray(value) ? [...value].sort() : value;
  }
  return out as Omit<AdvancedSearch, "place">;
}

/** Search params without the advanced search's: the filter (and anything else). */
export function withoutAdvanced(search: Record<string, unknown>): Record<string, unknown> {
  const fields = new Set<string>([
    ...TEXT_FIELDS,
    ...DESIGN_FIELDS,
    "age",
    "sex",
    "healthy_volunteers",
    "placebo",
    "near",
    "within",
    "place",
    "sort",
  ]);
  return Object.fromEntries(Object.entries(search).filter(([key]) => !fields.has(key)));
}
