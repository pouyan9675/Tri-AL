/**
 * The AI engine's settings: which model answers (a server such as LM Studio, and one of its
 * models), and the labels Annotate marks in trial text. Saved in tri-al.toml; they apply to
 * the next request, with no restart.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Plus, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useId, useMemo, useState } from "react";
import { AI_KEY, aiSettingsQuery } from "@/api/ai";
import { type AiSettings, type AiSettingsPatch, api, type LabelColor, unwrap } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { LABEL_TONES } from "@/lib/annotations";
import { notify } from "@/lib/notify";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";

const AUTOMATIC = "__automatic__";
const MAX_LABELS = 12;

type LabelDraft = {
  key: number;
  name: string;
  description: string;
  /** Comma-separated, as typed. */
  examples: string;
  color: LabelColor;
};

type Draft = { backend: string; server: string; model: string; labels: LabelDraft[] };

let nextKey = 0;

function draftOf(settings: AiSettings): Draft {
  return {
    backend: settings.backend,
    server: settings.server,
    model: settings.model,
    labels: settings.labels.map((label) => ({
      key: nextKey++,
      name: label.name,
      description: label.description,
      examples: label.examples.join(", "),
      color: label.color,
    })),
  };
}

function examplesOf(text: string): string[] {
  return text
    .split(",")
    .map((example) => example.trim())
    .filter(Boolean);
}

function labelsOf(draft: Draft) {
  return draft.labels.map((label) => ({
    name: label.name.trim(),
    description: label.description.trim(),
    examples: examplesOf(label.examples),
    color: label.color,
  }));
}

/** What the draft changes, so tri-al.toml only gets what someone set. */
function changes(draft: Draft, settings: AiSettings): AiSettingsPatch {
  const saved = draftOf(settings);
  const patch: AiSettingsPatch = {};
  if (draft.backend !== saved.backend) patch.backend = draft.backend;
  const server = draft.server.trim().replace(/\/+$/, "");
  if (server !== saved.server) patch.server = server;
  if (draft.model !== saved.model) patch.model = draft.model;
  const labels = labelsOf(draft);
  if (JSON.stringify(labels) !== JSON.stringify(labelsOf(saved))) patch.labels = labels;
  return patch;
}

function labelProblem(labels: LabelDraft[]): string | null {
  const names = labels.map((label) => label.name.trim().toLowerCase());
  if (names.some((name) => !name)) return "Every label needs a name.";
  if (new Set(names).size !== names.length) return "Label names must differ.";
  return null;
}

export function AiCard() {
  const settings = useQuery(aiSettingsQuery());
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft | null>(null);
  useEffect(() => {
    if (settings.data && draft === null) setDraft(draftOf(settings.data));
  }, [settings.data, draft]);

  const save = useMutation({
    mutationFn: (body: AiSettingsPatch) => unwrap(api.PATCH("/api/ai", { body })),
    onSuccess: (saved) => queryClient.setQueryData(aiSettingsQuery().queryKey, saved),
    onError: (error) =>
      notify.error("Couldn't save the AI settings", { description: error.message }),
  });

  if (!settings.data || !draft) {
    return (
      <Card className="shadow-xs xl:col-span-2">
        <CardHeader>
          <CardTitle>AI</CardTitle>
        </CardHeader>
        <CardContent>
          {settings.isError ? (
            <p className="text-sm text-destructive">{settings.error.message}</p>
          ) : (
            <Skeleton className="h-40 w-full" />
          )}
        </CardContent>
      </Card>
    );
  }

  const saved = settings.data;
  const locked = new Set(saved.locked);
  const patch = changes(draft, saved);
  const dirty = Object.keys(patch).length > 0;
  const problem = labelProblem(draft.labels);
  const update = (change: Partial<Draft>) => setDraft({ ...draft, ...change });

  return (
    <Card className="shadow-xs xl:col-span-2" data-testid="ai-settings">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="size-4 text-muted-foreground" />
          AI
        </CardTitle>
        <CardDescription>
          Annotate trial text with a model you run. Saved in tri-al.toml; changes apply at once.
        </CardDescription>
        <CardAction>
          <Switch
            checked={saved.enabled}
            disabled={save.isPending || locked.has("enabled")}
            aria-label={saved.enabled ? "Turn AI off" : "Turn AI on"}
            onCheckedChange={(enabled) => save.mutate({ enabled })}
          />
        </CardAction>
      </CardHeader>
      <CardContent className={cn("space-y-6", !saved.enabled && "opacity-60")}>
        <ModelSection draft={draft} saved={saved} locked={locked} update={update} />
        <LabelsSection draft={draft} locked={locked.has("labels")} update={update} />
      </CardContent>
      <CardFooter className="justify-end gap-2 border-t">
        {problem && dirty && (
          <span className="mr-auto flex items-center gap-1.5 text-xs text-destructive">
            <CircleAlert className="size-3.5" />
            {problem}
          </span>
        )}
        <Button
          variant="ghost"
          size="sm"
          disabled={!dirty || save.isPending}
          onClick={() => setDraft(draftOf(saved))}
        >
          Discard
        </Button>
        <Button
          size="sm"
          disabled={!dirty || problem !== null || save.isPending}
          onClick={() => save.mutate(patch, { onSuccess: (result) => setDraft(draftOf(result)) })}
          data-testid="ai-save"
        >
          {save.isPending && <Spinner />}
          Save changes
        </Button>
      </CardFooter>
    </Card>
  );
}

function ModelSection({
  draft,
  saved,
  locked,
  update,
}: {
  draft: Draft;
  saved: AiSettings;
  locked: ReadonlySet<string>;
  update: (change: Partial<Draft>) => void;
}) {
  const id = useId();
  const server = useDebounced(draft.server.trim(), 500);
  const models = useQuery({
    queryKey: [...AI_KEY, "models", draft.backend, server],
    queryFn: ({ signal }) =>
      unwrap(api.POST("/api/ai/models", { body: { backend: draft.backend, server }, signal })),
    enabled: /^https?:\/\/./.test(server),
    retry: false,
    staleTime: 10_000,
  });
  const listed = models.data?.models ?? [];
  const backend = saved.backends.find((b) => b.name === draft.backend);
  const known = useMemo(() => new Set(listed.map((model) => model.id)), [listed]);

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-medium">Model</h3>
      <div className="grid gap-4 md:grid-cols-2">
        {saved.backends.length > 1 && (
          <div className="space-y-1.5 md:col-span-2">
            <Label htmlFor={`${id}-backend`}>Backend</Label>
            <Select
              value={draft.backend}
              onValueChange={(value) => update({ backend: value, model: "" })}
              disabled={locked.has("backend")}
            >
              <SelectTrigger id={`${id}-backend`} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {saved.backends.map((b) => (
                  <SelectItem key={b.name} value={b.name}>
                    {b.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-server`}>Server</Label>
          <div className="flex gap-1.5">
            <Input
              id={`${id}-server`}
              value={draft.server}
              onChange={(event) => update({ server: event.target.value })}
              placeholder="http://127.0.0.1:1234/v1"
              spellCheck={false}
              disabled={locked.has("server")}
              data-testid="ai-server"
            />
            <Button
              variant="outline"
              size="icon-sm"
              className="size-8"
              aria-label="Check the server again"
              onClick={() => void models.refetch()}
              disabled={!models.isEnabled || models.isFetching}
            >
              {models.isFetching ? <Spinner /> : <RefreshCw />}
            </Button>
          </div>
          <ServerStatus
            fetching={models.isFetching}
            error={models.data?.error ?? (models.isError ? models.error.message : null)}
            count={models.data && !models.data.error ? listed.length : null}
            hint={backend?.title}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-model`}>Model</Label>
          <Select
            value={draft.model || AUTOMATIC}
            onValueChange={(value) => update({ model: value === AUTOMATIC ? "" : value })}
            disabled={locked.has("model")}
          >
            <SelectTrigger id={`${id}-model`} className="w-full" data-testid="ai-model">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={AUTOMATIC}>Automatic: the first loaded model</SelectItem>
              {(listed.length > 0 || (draft.model && !known.has(draft.model))) && (
                <SelectSeparator />
              )}
              {draft.model && !known.has(draft.model) && (
                <SelectItem value={draft.model}>{draft.model}</SelectItem>
              )}
              {listed.map((model) => (
                <SelectItem key={model.id} value={model.id}>
                  <span className="truncate">{model.id}</span>
                  {model.detail && (
                    <span className="text-xs text-muted-foreground">{model.detail}</span>
                  )}
                  {model.loaded && (
                    <Badge
                      variant="outline"
                      className="h-4.5 border-good/40 bg-good/8 px-1.5 text-[0.65rem] font-normal"
                    >
                      loaded
                    </Badge>
                  )}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            A model that isn't loaded loads on first use, if the server allows it.
          </p>
        </div>
      </div>
    </section>
  );
}

function ServerStatus({
  fetching,
  error,
  count,
  hint,
}: {
  fetching: boolean;
  error: string | null;
  count: number | null;
  hint: string | undefined;
}) {
  if (fetching) return <p className="text-xs text-muted-foreground">Checking the server…</p>;
  if (error) {
    return (
      <p className="flex items-start gap-1.5 text-xs text-destructive" data-testid="ai-status">
        <CircleAlert className="mt-px size-3.5 shrink-0" />
        {error}
      </p>
    );
  }
  if (count === null) return <p className="text-xs text-muted-foreground">{hint}</p>;
  return (
    <p className="flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="ai-status">
      <span className="size-1.5 rounded-full bg-good" />
      Connected · {count} model{count === 1 ? "" : "s"}
    </p>
  );
}

function LabelsSection({
  draft,
  locked,
  update,
}: {
  draft: Draft;
  locked: boolean;
  update: (change: Partial<Draft>) => void;
}) {
  const setLabel = (key: number, change: Partial<LabelDraft>) =>
    update({ labels: draft.labels.map((l) => (l.key === key ? { ...l, ...change } : l)) });
  const used = new Set(draft.labels.map((label) => label.color));
  const add = () => {
    const colors = Object.keys(LABEL_TONES) as LabelColor[];
    const color = colors.find((c) => !used.has(c)) ?? colors[draft.labels.length % colors.length];
    update({
      labels: [
        ...draft.labels,
        { key: nextKey++, name: "", description: "", examples: "", color: color ?? "blue" },
      ],
    });
  };

  return (
    <section className="space-y-3">
      <div className="space-y-0.5">
        <h3 className="text-sm font-medium">Annotation labels</h3>
        <p className="text-xs text-muted-foreground">
          What Annotate marks on a trial's text. The model reads each label's name, description and
          examples, so clear ones help a small model most.
        </p>
      </div>
      {draft.labels.length > 0 && (
        <div className="hidden gap-2 px-px text-xs text-muted-foreground md:grid md:grid-cols-[2rem_10rem_minmax(0,1fr)_minmax(0,16rem)_2rem]">
          <span />
          <span>Name</span>
          <span>Description</span>
          <span>Examples, comma-separated</span>
        </div>
      )}
      <ul className="space-y-2" data-testid="ai-labels">
        {draft.labels.map((label) => (
          <li
            key={label.key}
            className="grid grid-cols-[2rem_minmax(0,1fr)_2rem] gap-2 md:grid-cols-[2rem_10rem_minmax(0,1fr)_minmax(0,16rem)_2rem]"
          >
            <ColorPicker
              color={label.color}
              disabled={locked}
              onChange={(color) => setLabel(label.key, { color })}
            />
            <Input
              value={label.name}
              onChange={(event) => setLabel(label.key, { name: event.target.value })}
              placeholder="Name"
              aria-label="Label name"
              maxLength={40}
              disabled={locked}
            />
            <Button
              variant="ghost"
              size="icon-sm"
              className="size-8 text-muted-foreground md:order-last"
              aria-label={`Remove ${label.name || "label"}`}
              onClick={() => update({ labels: draft.labels.filter((l) => l.key !== label.key) })}
              disabled={locked}
            >
              <Trash2 />
            </Button>
            <Input
              value={label.description}
              onChange={(event) => setLabel(label.key, { description: event.target.value })}
              placeholder="What it covers"
              aria-label="Label description"
              maxLength={300}
              disabled={locked}
              className="col-span-2 col-start-2 md:col-span-1"
            />
            <Input
              value={label.examples}
              onChange={(event) => setLabel(label.key, { examples: event.target.value })}
              placeholder="e.g. MMSE, CDR-SB"
              aria-label="Label examples"
              disabled={locked}
              className="col-span-2 col-start-2 md:col-span-1"
            />
          </li>
        ))}
      </ul>
      {draft.labels.length === 0 && (
        <p className="text-sm text-muted-foreground">No labels: Annotate has nothing to mark.</p>
      )}
      <Button
        variant="outline"
        size="sm"
        onClick={add}
        disabled={locked || draft.labels.length >= MAX_LABELS}
      >
        <Plus />
        Add label
      </Button>
    </section>
  );
}

function ColorPicker({
  color,
  disabled,
  onChange,
}: {
  color: LabelColor;
  disabled: boolean;
  onChange: (color: LabelColor) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="icon-sm"
          className="size-8"
          aria-label={`Colour: ${color}`}
          disabled={disabled}
        >
          <span className={cn("size-3 rounded-full", LABEL_TONES[color].dot)} />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-2" align="start">
        <div className="grid grid-cols-4 gap-1.5">
          {(Object.keys(LABEL_TONES) as LabelColor[]).map((option) => (
            <button
              key={option}
              type="button"
              aria-label={option}
              aria-pressed={option === color}
              onClick={() => {
                onChange(option);
                setOpen(false);
              }}
              className={cn(
                "flex size-7 items-center justify-center rounded-md hover:bg-muted",
                option === color && "ring-2 ring-ring",
              )}
            >
              <span className={cn("size-3.5 rounded-full", LABEL_TONES[option].dot)} />
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
