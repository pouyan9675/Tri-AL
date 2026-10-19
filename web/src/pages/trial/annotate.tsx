/**
 * The Annotate button on a trial text, and the legend over the marked text.
 *
 * Pressing it streams the text's annotations from the model (`annotationQuery`): marks fade
 * in as each piece of the text is answered. Results stay in the query cache, so pressing it
 * again, or coming back to the trial, shows them at once.
 */
import { useQuery } from "@tanstack/react-query";
import { Eye, EyeOff, RotateCcw, Sparkles } from "lucide-react";
import { useState } from "react";
import { aiSettingsQuery, annotationQuery } from "@/api/ai";
import type { AiSettings, AnnotatedField, TrialDetail } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { type Annotation, LABEL_TONES, sourceText } from "@/lib/annotations";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import type { Marks } from "./text";

export type AnnotationView = {
  /** AI is on: show the button. */
  available: boolean;
  /** Why the button can't run, if it can't. */
  blocked: string | null;
  data: Annotation | undefined;
  running: boolean;
  failed: boolean;
  shown: boolean;
  hidden: ReadonlySet<string>;
  press: () => void;
  toggleLabel: (name: string) => void;
  /** What `TextBlocks` draws. */
  marks: Marks | undefined;
};

function settingsVersion(settings: AiSettings, dataVersion: number): string {
  const { backend, server, model, labels } = settings;
  return JSON.stringify([backend, server, model, labels, dataVersion]);
}

export function useAnnotation(trial: TrialDetail, field: AnnotatedField): AnnotationView {
  const settings = useQuery(aiSettingsQuery());
  const version = settings.data ? settingsVersion(settings.data, trial.data_version) : "";
  const query = useQuery(annotationQuery(trial.source_id, field, version));
  const [shown, setShown] = useState(false);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());

  const data = query.data;
  const running = query.fetchStatus === "fetching";
  const done = data?.seconds != null;
  const failed = query.isError && !running;
  const text = trial[field] ?? "";
  const fits = data?.length == null || data.length === sourceText(text).length;

  const press = () => {
    if (running) return;
    if (shown && done) {
      setShown(false);
      return;
    }
    setShown(true);
    if (done && !failed) return;
    void query.refetch().then((result) => {
      if (result.error)
        notify.error("Couldn't annotate the text", { description: result.error.message });
    });
  };

  const colors = Object.fromEntries((data?.labels ?? []).map((l) => [l.name, l.color]));
  const marks =
    shown && data && fits
      ? { spans: data.spans.filter((span) => !hidden.has(span.label)), colors }
      : undefined;

  return {
    available: settings.data?.enabled === true && text.trim().length > 0,
    blocked:
      settings.data && settings.data.labels.length === 0
        ? "Add annotation labels in Settings first."
        : null,
    data,
    running,
    failed,
    shown,
    hidden,
    press,
    toggleLabel: (name) =>
      setHidden((old) => {
        const next = new Set(old);
        if (!next.delete(name)) next.add(name);
        return next;
      }),
    marks,
  };
}

export function AnnotateButton({ view }: { view: AnnotationView }) {
  if (!view.available) return null;
  const { data, running, failed, shown } = view;
  const done = data?.seconds != null;
  let icon = <Sparkles />;
  let label = "Annotate";
  if (running) {
    icon = <Spinner />;
    label = data?.chunks ? `Annotating ${data.received}/${data.chunks}` : "Annotating…";
  } else if (failed) {
    icon = <RotateCcw />;
    label = "Try again";
  } else if (done) {
    icon = shown ? <EyeOff /> : <Eye />;
    label = shown ? "Hide annotations" : "Show annotations";
  }
  const button = (
    <Button
      variant="ghost"
      size="sm"
      className={cn("-my-1 tabular", running && "text-muted-foreground")}
      onClick={view.press}
      disabled={view.blocked !== null}
      aria-busy={running}
      data-testid="annotate"
    >
      {icon}
      {label}
    </Button>
  );
  if (view.blocked === null) return button;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span>{button}</span>
      </TooltipTrigger>
      <TooltipContent>{view.blocked}</TooltipContent>
    </Tooltip>
  );
}

/** The labels with their counts (each a switch), and which model answered. */
export function AnnotationLegend({ view }: { view: AnnotationView }) {
  const { data, shown, running } = view;
  if (!shown || !data || data.labels.length === 0) return null;
  const counts = new Map<string, number>();
  for (const span of data.spans) counts.set(span.label, (counts.get(span.label) ?? 0) + 1);
  return (
    <div
      className="mb-3 flex flex-wrap items-center gap-1.5 duration-300 animate-in fade-in"
      data-testid="annotation-legend"
    >
      {data.labels.map((label) => {
        const off = view.hidden.has(label.name);
        return (
          <button
            key={label.name}
            type="button"
            aria-pressed={!off}
            onClick={() => view.toggleLabel(label.name)}
            title={off ? `Show ${label.name}` : `Hide ${label.name}`}
            className={cn(
              "inline-flex h-6 items-center gap-1.5 rounded-full border px-2 text-xs transition-opacity hover:bg-muted",
              off && "opacity-45",
            )}
          >
            <span className={cn("size-2 rounded-full", LABEL_TONES[label.color].dot)} />
            {label.name}
            <span className="text-muted-foreground tabular">{counts.get(label.name) ?? 0}</span>
          </button>
        );
      })}
      <span className="ml-auto text-xs text-muted-foreground tabular">
        {running
          ? `${data.model} · reading…`
          : data.seconds != null &&
            `${data.model} · ${data.cached ? "remembered" : `${data.seconds.toFixed(1)} s`}`}
      </span>
    </div>
  );
}
