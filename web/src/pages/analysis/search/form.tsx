/**
 * The advanced search form: words in chosen parts of a trial, whom it takes, how it's designed
 * and where it runs. It edits a draft; Search puts the draft in the URL, which runs it.
 */
import { useQuery } from "@tanstack/react-query";
import { CircleHelp, Plus, SearchIcon, X } from "lucide-react";
import { type ReactNode, useId, useState } from "react";
import { metaQuery } from "@/api/queries";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  type AdvancedSearch,
  DEFAULT_DISTANCE,
  DESIGN_FIELDS,
  type DesignField,
  DISTANCES,
  FIELDS,
  parseAge,
  type Sex,
  TEXT_FIELDS,
  type TextField,
} from "@/lib/advanced";
import { humanize } from "@/lib/format";
import { PlacePicker, placeName } from "./place-picker";

const DESIGN_TITLES: Record<DesignField, string> = {
  allocation: "Allocation",
  masking: "Masking",
  intervention_model: "Model",
  primary_purpose: "Purpose",
};

const ANY = "any";

export function SearchForm({
  initial,
  onSubmit,
  onClear,
}: {
  initial: AdvancedSearch;
  onSubmit: (search: AdvancedSearch) => void;
  onClear: () => void;
}) {
  const [rows, setRows] = useState<TextField[]>(() => {
    const used = TEXT_FIELDS.filter((field) => initial[field]);
    return used.length ? used : ["text"];
  });
  const [draft, setDraft] = useState<AdvancedSearch>(initial);
  const [age, setAge] = useState(initial.age ?? "");
  const ageValid = !age.trim() || parseAge(age) !== undefined;
  const id = useId();

  const set = (patch: Partial<AdvancedSearch>) => setDraft((prev) => ({ ...prev, ...patch }));
  const unused = TEXT_FIELDS.filter((field) => !rows.includes(field));

  const submit = () => {
    if (!ageValid) return;
    const next: AdvancedSearch = { ...draft, age: parseAge(age) };
    for (const field of TEXT_FIELDS) {
      if (!rows.includes(field) || !next[field]?.trim()) delete next[field];
    }
    onSubmit(next);
  };

  return (
    <form
      aria-label="Advanced search"
      className="flex flex-col gap-5 rounded-xl border bg-card p-4"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <Group
        title="Words"
        action={<SyntaxHelp />}
        description="Each field searches its own part of a trial; every field must match."
      >
        <div className="flex flex-col gap-2">
          {rows.map((field) => (
            <div key={field} className="flex min-w-0 flex-col gap-1.5 sm:flex-row">
              <Select
                value={field}
                onValueChange={(value) => {
                  const next = value as TextField;
                  setRows((prev) => prev.map((row) => (row === field ? next : row)));
                  set({ [next]: draft[field], [field]: undefined });
                }}
              >
                <SelectTrigger
                  className="w-full sm:w-52"
                  aria-label={`Field of ${FIELDS[field].label}`}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TEXT_FIELDS.map((option) => (
                    <SelectItem
                      key={option}
                      value={option}
                      disabled={option !== field && rows.includes(option)}
                    >
                      {FIELDS[option].label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="flex min-w-0 flex-1 gap-1.5">
                <Input
                  aria-label={FIELDS[field].label}
                  className="h-8"
                  placeholder={FIELDS[field].placeholder}
                  value={draft[field] ?? ""}
                  onChange={(event) => set({ [field]: event.target.value })}
                  autoComplete="off"
                  spellCheck={false}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="size-8"
                  aria-label={`Remove ${FIELDS[field].label}`}
                  disabled={rows.length === 1}
                  onClick={() => {
                    setRows((prev) => prev.filter((row) => row !== field));
                    set({ [field]: undefined });
                  }}
                >
                  <X />
                </Button>
              </div>
            </div>
          ))}
          {unused.length > 0 && (
            <Select
              value=""
              onValueChange={(value) => setRows((prev) => [...prev, value as TextField])}
            >
              <SelectTrigger className="w-fit" aria-label="Add a field">
                <Plus />
                <span>Add a field</span>
              </SelectTrigger>
              <SelectContent>
                {unused.map((option) => (
                  <SelectItem key={option} value={option}>
                    {FIELDS[option].label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
      </Group>

      <div className="grid gap-5 lg:grid-cols-[1fr_1.4fr_1fr]">
        <Group title="Participants" description="Trials that would take this person.">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${id}-age`} className="text-xs text-muted-foreground">
              Age in years
            </Label>
            <Input
              id={`${id}-age`}
              className="h-8"
              placeholder="70, or a range: 60..80"
              value={age}
              onChange={(event) => setAge(event.target.value)}
              aria-invalid={!ageValid}
              inputMode="numeric"
              autoComplete="off"
            />
            {!ageValid && (
              <p className="text-xs text-destructive">
                An age (70) or a range (60..80, ..17, 65..).
              </p>
            )}
          </div>
          <Choice
            label="Sex"
            value={draft.sex ?? ANY}
            options={[
              [ANY, "Any"],
              ["FEMALE", "Female"],
              ["MALE", "Male"],
            ]}
            onChange={(value) => set({ sex: value === ANY ? undefined : (value as Sex) })}
          />
          <Choice
            label="Healthy volunteers"
            value={yesNo(draft.healthy_volunteers)}
            options={[
              [ANY, "Any"],
              ["yes", "Accepted"],
              ["no", "Not accepted"],
            ]}
            onChange={(value) => set({ healthy_volunteers: fromYesNo(value) })}
          />
        </Group>

        <Group title="Design" description="Any of the chosen values, field by field.">
          <DesignChoices draft={draft} set={set} />
          <Choice
            label="Placebo"
            value={yesNo(draft.placebo)}
            options={[
              [ANY, "Any"],
              ["yes", "With a placebo"],
              ["no", "Without"],
            ]}
            onChange={(value) => set({ placebo: fromYesNo(value) })}
          />
        </Group>

        <Group title="Location" description="Trials with a site within a distance of a city.">
          <PlacePicker
            place={draft.place}
            onChoose={(place) =>
              set(
                place
                  ? {
                      near: `${place.lat},${place.lon}`,
                      place: placeName(place),
                      within: draft.within ?? DEFAULT_DISTANCE,
                    }
                  : { near: undefined, place: undefined, within: undefined },
              )
            }
          />
          <Select
            value={String(draft.within ?? DEFAULT_DISTANCE)}
            onValueChange={(value) => set({ within: Number(value) })}
            disabled={!draft.near}
          >
            <SelectTrigger className="w-full" aria-label="Distance">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DISTANCES.map((km) => (
                <SelectItem key={km} value={String(km)}>
                  Within {km} km
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            ClinicalTrials.gov places each site at its city, so distances are between cities.
          </p>
        </Group>
      </div>

      <div className="flex gap-2">
        <Button type="submit" disabled={!ageValid}>
          <SearchIcon />
          Search
        </Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => {
            setRows(["text"]);
            setDraft({});
            setAge("");
            onClear();
          }}
        >
          Clear
        </Button>
      </div>
    </form>
  );
}

function Group({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <fieldset className="flex min-w-0 flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <legend className="text-sm font-semibold tracking-tight">{title}</legend>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
        {action}
      </div>
      {children}
    </fieldset>
  );
}

/** One of a few options, as a row of toggles. */
function Choice({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        spacing={1}
        className="flex-wrap"
        aria-label={label}
        value={value}
        onValueChange={(next) => onChange(next || ANY)}
      >
        {options.map(([option, text]) => (
          <ToggleGroupItem key={option} value={option}>
            {text}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </div>
  );
}

/** Allocation, masking, model and purpose: any of the codes chosen, labelled from the meta. */
function DesignChoices({
  draft,
  set,
}: {
  draft: AdvancedSearch;
  set: (patch: Partial<AdvancedSearch>) => void;
}) {
  const { data: meta } = useQuery(metaQuery());
  return (
    <>
      {DESIGN_FIELDS.map((field) => {
        const labels = meta?.labels[field] ?? {};
        const codes = [...new Set([...Object.keys(labels), ...(draft[field] ?? [])])];
        return (
          <div key={field} className="flex flex-col gap-1.5">
            <span className="text-xs text-muted-foreground">{DESIGN_TITLES[field]}</span>
            <ToggleGroup
              type="multiple"
              variant="outline"
              size="sm"
              spacing={1}
              className="flex-wrap"
              aria-label={DESIGN_TITLES[field]}
              value={draft[field] ?? []}
              onValueChange={(values) => set({ [field]: values.length ? values : undefined })}
            >
              {codes.map((code) => (
                <ToggleGroupItem key={code} value={code}>
                  {labels[code] ?? humanize(code)}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
        );
      })}
    </>
  );
}

function yesNo(value: boolean | undefined): string {
  return value === undefined ? ANY : value ? "yes" : "no";
}

function fromYesNo(value: string): boolean | undefined {
  return value === "yes" ? true : value === "no" ? false : undefined;
}

const SYNTAX: [string, string][] = [
  ["amyloid tau", "both words, anywhere in the field"],
  ['"amyloid PET"', "the words together, in order"],
  ['"amyloid PET"~5', "within 5 words of each other"],
  ["donepezil OR rivastigmine", "either word"],
  ["anticoag*", "words starting with it"],
  ["-warfarin", "leave out trials with it"],
];

function SyntaxHelp() {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button type="button" variant="ghost" size="sm" className="text-muted-foreground">
          <CircleHelp />
          Syntax
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80">
        <div className="flex flex-col gap-3 text-sm">
          <p className="text-xs text-muted-foreground">
            Words match as the full-text index reads them: any case, and stems, so{" "}
            <span className="font-medium text-foreground">anticoagulants</span> finds anticoagulant
            too.
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
            {SYNTAX.map(([example, meaning]) => (
              <div key={example} className="contents">
                <dt className="font-mono text-foreground">{example}</dt>
                <dd className="text-muted-foreground">{meaning}</dd>
              </div>
            ))}
          </dl>
          <p className="text-xs text-muted-foreground">
            Inclusion and exclusion criteria are told apart by their headings, and checked in the
            text of the newest 2,000 trials that match the rest.
          </p>
        </div>
      </PopoverContent>
    </Popover>
  );
}
