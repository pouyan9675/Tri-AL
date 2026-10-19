/**
 * What a trial studies, at a glance: its conditions, its interventions (coloured by type),
 * its design, and who gets what (arms or cohorts).
 */
import { Link } from "@tanstack/react-router";
import {
  Brain,
  CalendarClock,
  Columns2,
  Combine,
  Cpu,
  Dna,
  EyeOff,
  HeartPulse,
  Leaf,
  type LucideIcon,
  Pill,
  Radiation,
  Scissors,
  Shapes,
  Shuffle,
  Syringe,
  Target,
  TestTube,
  Users,
} from "lucide-react";
import { useState } from "react";
import type { TrialDetail } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useLabels } from "@/lib/labels";
import { cn } from "@/lib/utils";

type Intervention = TrialDetail["interventions"][number];
type Arm = TrialDetail["arms"][number];

/** Literal class names per colour, so Tailwind sees them. */
const TONES = {
  blue: {
    text: "text-chart-1",
    tile: "bg-chart-1/12 text-chart-1",
    chip: "border-chart-1/30 bg-chart-1/8",
    bar: "border-l-chart-1",
  },
  orange: {
    text: "text-chart-2",
    tile: "bg-chart-2/12 text-chart-2",
    chip: "border-chart-2/30 bg-chart-2/8",
    bar: "border-l-chart-2",
  },
  teal: {
    text: "text-chart-3",
    tile: "bg-chart-3/12 text-chart-3",
    chip: "border-chart-3/30 bg-chart-3/8",
    bar: "border-l-chart-3",
  },
  amber: {
    text: "text-chart-4",
    tile: "bg-chart-4/14 text-chart-4",
    chip: "border-chart-4/35 bg-chart-4/10",
    bar: "border-l-chart-4",
  },
  pink: {
    text: "text-chart-5",
    tile: "bg-chart-5/12 text-chart-5",
    chip: "border-chart-5/30 bg-chart-5/8",
    bar: "border-l-chart-5",
  },
  green: {
    text: "text-chart-6",
    tile: "bg-chart-6/12 text-chart-6",
    chip: "border-chart-6/30 bg-chart-6/8",
    bar: "border-l-chart-6",
  },
  violet: {
    text: "text-chart-7",
    tile: "bg-chart-7/12 text-chart-7",
    chip: "border-chart-7/30 bg-chart-7/8",
    bar: "border-l-chart-7",
  },
  red: {
    text: "text-chart-8",
    tile: "bg-chart-8/12 text-chart-8",
    chip: "border-chart-8/30 bg-chart-8/8",
    bar: "border-l-chart-8",
  },
  neutral: {
    text: "text-muted-foreground",
    tile: "bg-muted text-muted-foreground",
    chip: "border-border bg-muted/50",
    bar: "border-l-muted-foreground/40",
  },
} as const;
type Tone = keyof typeof TONES;

const INTERVENTION_STYLE: Record<string, { icon: LucideIcon; tone: Tone }> = {
  DRUG: { icon: Pill, tone: "blue" },
  BIOLOGICAL: { icon: Syringe, tone: "teal" },
  DEVICE: { icon: Cpu, tone: "violet" },
  PROCEDURE: { icon: Scissors, tone: "red" },
  BEHAVIORAL: { icon: Brain, tone: "orange" },
  DIETARY_SUPPLEMENT: { icon: Leaf, tone: "green" },
  DIAGNOSTIC_TEST: { icon: TestTube, tone: "pink" },
  RADIATION: { icon: Radiation, tone: "amber" },
  GENETIC: { icon: Dna, tone: "pink" },
  COMBINATION_PRODUCT: { icon: Combine, tone: "violet" },
};
const OTHER_INTERVENTION = { icon: Shapes, tone: "neutral" } as const;

export function interventionStyle(type: string | null | undefined) {
  return (type && INTERVENTION_STYLE[type]) || OTHER_INTERVENTION;
}

const ARM_TONES: Record<string, Tone> = {
  EXPERIMENTAL: "blue",
  ACTIVE_COMPARATOR: "amber",
  PLACEBO_COMPARATOR: "neutral",
  SHAM_COMPARATOR: "neutral",
  NO_INTERVENTION: "neutral",
  OTHER: "violet",
};

/** Arms first, comparators after, the source's order otherwise. */
const ARM_ORDER = [
  "EXPERIMENTAL",
  "ACTIVE_COMPARATOR",
  "PLACEBO_COMPARATOR",
  "SHAM_COMPARATOR",
  "OTHER",
  "NO_INTERVENTION",
];

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[0.7rem] font-semibold tracking-wider text-muted-foreground uppercase">
      {children}
    </div>
  );
}

export function InterventionChip({
  intervention,
  className,
}: {
  intervention: Pick<Intervention, "name" | "type">;
  className?: string;
}) {
  const label = useLabels();
  const style = interventionStyle(intervention.type);
  const tone = TONES[style.tone];
  const Icon = style.icon;
  return (
    <Link
      to="/trials"
      search={{ interventions: [intervention.name] }}
      title={`${intervention.name}${intervention.type ? ` · ${label("intervention_type", intervention.type)}` : ""}: trials testing it`}
      className={cn(
        "inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-sm font-medium transition-colors hover:border-foreground/25",
        tone.chip,
        className,
      )}
    >
      <Icon className={cn("size-3.5 shrink-0", tone.text)} />
      <span className="truncate">{intervention.name}</span>
    </Link>
  );
}

type DesignPill = { icon: LucideIcon; text: string; title?: string };

function designPills(trial: TrialDetail, label: ReturnType<typeof useLabels>): DesignPill[] {
  const pills: DesignPill[] = [];
  if (trial.primary_purpose) {
    pills.push({
      icon: Target,
      text: label("primary_purpose", trial.primary_purpose),
      title: "Primary purpose",
    });
  }
  if (trial.allocation && trial.allocation !== "NA") {
    pills.push({ icon: Shuffle, text: label("allocation", trial.allocation), title: "Allocation" });
  }
  if (trial.intervention_model) {
    pills.push({
      icon: Columns2,
      text: label("intervention_model", trial.intervention_model),
      title: "Intervention model",
    });
  }
  if (trial.observational_model) {
    pills.push({
      icon: Users,
      text: label("observational_model", trial.observational_model),
      title: "Observational model",
    });
  }
  if (trial.time_perspective) {
    pills.push({
      icon: CalendarClock,
      text: label("time_perspective", trial.time_perspective),
      title: "Time perspective",
    });
  }
  if (trial.masking) {
    const roles = trial.masked_roles.map((role) => label("masked_role", role)).join(", ");
    pills.push({
      icon: EyeOff,
      text: label("masking", trial.masking),
      title: roles ? `Masked: ${roles}` : "Masking",
    });
  }
  return pills;
}

/** The band at the top of the overview: conditions → interventions, and the design. */
export function StudyFocus({ trial }: { trial: TrialDetail }) {
  const label = useLabels();
  const pills = designPills(trial, label);
  const keywords = trial.keywords.slice(0, 10);

  return (
    <Card className="gap-0 overflow-hidden p-0 shadow-xs">
      <div className="grid md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section className="flex flex-col gap-3 bg-brand/[0.04] p-5 md:border-r">
          <Eyebrow>{trial.conditions.length === 1 ? "Condition" : "Conditions"}</Eyebrow>
          {trial.conditions.length === 0 ? (
            <p className="text-sm text-muted-foreground">None listed.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {trial.conditions.map((condition) => (
                <Link
                  key={condition}
                  to="/trials"
                  search={{ conditions: [condition] }}
                  className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-brand/25 bg-brand/8 px-2.5 py-1 text-sm font-medium transition-colors hover:border-brand/50"
                  title={`${condition}: trials studying it`}
                >
                  <HeartPulse className="size-3.5 shrink-0 text-brand" />
                  <span className="truncate">{condition}</span>
                </Link>
              ))}
            </div>
          )}
          {keywords.length > 0 && (
            <p className="text-xs leading-relaxed text-muted-foreground">
              <span className="font-medium text-foreground/70">Keywords </span>
              {keywords.join(" · ")}
              {trial.keywords.length > keywords.length &&
                ` · +${trial.keywords.length - keywords.length}`}
            </p>
          )}
        </section>
        <section className="flex flex-col gap-3 border-t p-5 md:border-t-0">
          <Eyebrow>{trial.study_type === "OBSERVATIONAL" ? "Exposures" : "Tested with"}</Eyebrow>
          {trial.interventions.length === 0 ? (
            <p className="text-sm text-muted-foreground">No interventions listed.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {trial.interventions.map((intervention) => (
                <InterventionChip key={intervention.name} intervention={intervention} />
              ))}
            </div>
          )}
        </section>
      </div>
      {pills.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t bg-muted/30 px-5 py-3 text-sm">
          {pills.map((pill) => (
            <span key={pill.text} className="inline-flex items-center gap-1.5" title={pill.title}>
              <pill.icon className="size-3.5 text-muted-foreground" />
              {pill.text}
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}

/** Text that shows its first lines, with a toggle when there's more. */
export function Clamp({ text, lines = 3 }: { text: string; lines?: 2 | 3 | 4 }) {
  const [open, setOpen] = useState(false);
  const long = text.length > lines * 90;
  return (
    <div className="space-y-1">
      <p
        className={cn(
          "text-sm leading-relaxed whitespace-pre-line text-foreground/80",
          !open && long && { 2: "line-clamp-2", 3: "line-clamp-3", 4: "line-clamp-4" }[lines],
        )}
      >
        {text}
      </p>
      {long && (
        <Button
          variant="link"
          size="sm"
          className="h-auto p-0 text-xs text-muted-foreground"
          onClick={() => setOpen(!open)}
        >
          {open ? "Show less" : "Show more"}
        </Button>
      )}
    </div>
  );
}

function sortedArms(arms: Arm[]): Arm[] {
  const rank = (arm: Arm) => {
    const index = arm.type ? ARM_ORDER.indexOf(arm.type) : -1;
    return index === -1 ? ARM_ORDER.length : index;
  };
  return arms
    .map((arm, index) => ({ arm, index }))
    .sort((a, b) => rank(a.arm) - rank(b.arm) || a.index - b.index)
    .map(({ arm }) => arm);
}

/** Who gets what: each arm (or cohort) with its description and interventions. */
export function ArmCards({ trial }: { trial: TrialDetail }) {
  const label = useLabels();
  const byName = new Map(trial.interventions.map((i) => [i.name, i]));
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {sortedArms(trial.arms).map((arm) => {
        const tone = TONES[(arm.type && ARM_TONES[arm.type]) || (arm.type ? "neutral" : "teal")];
        return (
          <article
            key={arm.label}
            className={cn(
              "flex flex-col gap-2.5 rounded-lg border border-l-4 bg-card p-3.5",
              tone.bar,
              arm.type === "NO_INTERVENTION" && "border-dashed",
            )}
            data-testid="arm"
          >
            <header className="flex flex-col gap-1">
              {arm.type && (
                <span
                  className={cn("text-[0.7rem] font-semibold tracking-wider uppercase", tone.text)}
                >
                  {label("arm_type", arm.type)}
                </span>
              )}
              <h3 className="text-sm leading-snug font-semibold">{arm.label}</h3>
            </header>
            {arm.description && <Clamp text={arm.description} />}
            {arm.interventions.length > 0 && (
              <div className="mt-auto flex flex-wrap gap-1.5 pt-1">
                {arm.interventions.map((name) => (
                  <InterventionChip
                    key={name}
                    intervention={byName.get(name) ?? { name, type: null }}
                    className="px-2 py-0.5 text-xs"
                  />
                ))}
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}

/** Each intervention with its type, other names, description and the arms that get it. */
export function InterventionList({ trial }: { trial: TrialDetail }) {
  const label = useLabels();
  const armsOf = (name: string) =>
    trial.arms.filter((arm) => arm.interventions.includes(name)).map((arm) => arm.label);
  return (
    <ul className="flex flex-col divide-y">
      {trial.interventions.map((intervention) => {
        const style = interventionStyle(intervention.type);
        const Icon = style.icon;
        const arms = armsOf(intervention.name);
        return (
          <li key={intervention.name} className="flex gap-3 py-3.5 first:pt-0 last:pb-0">
            <span
              className={cn(
                "flex size-9 shrink-0 items-center justify-center rounded-lg",
                TONES[style.tone].tile,
              )}
            >
              <Icon className="size-4.5" />
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <Link
                  to="/trials"
                  search={{ interventions: [intervention.name] }}
                  className="font-medium hover:underline"
                >
                  {intervention.name}
                </Link>
                {intervention.type && (
                  <span className={cn("text-xs font-medium", TONES[style.tone].text)}>
                    {label("intervention_type", intervention.type)}
                  </span>
                )}
              </div>
              {intervention.other_names.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  Also known as {intervention.other_names.join(", ")}
                </p>
              )}
              {intervention.description && <Clamp text={intervention.description} lines={2} />}
              {arms.length > 0 && trial.arms.length > 1 && (
                <p className="text-xs text-muted-foreground">
                  Given in: <span className="text-foreground/80">{arms.join(" · ")}</span>
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
