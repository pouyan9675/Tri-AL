import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CircleAlert,
  CloudDownload,
  Monitor,
  Moon,
  Palette,
  Puzzle,
  RefreshCw,
  Sun,
} from "lucide-react";
import { useMemo } from "react";
import { ApiError, api, type Job, type Plugin } from "@/api/client";
import { JOBS_KEY, jobsQuery, metaQuery, pluginsQuery } from "@/api/queries";
import { Page } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  formatDate,
  formatDateTime,
  formatDuration,
  formatNumber,
  formatRelative,
  humanize,
} from "@/lib/format";
import { isActive } from "@/lib/live";
import { useLive, useLiveEvents } from "@/lib/live-context";
import { notify } from "@/lib/notify";
import { type Theme, useTheme } from "@/lib/theme";
import { useNow } from "@/lib/use-now";
import { cn } from "@/lib/utils";
import { AiCard } from "./ai";
import { JobProgress } from "./job-progress";

export function SettingsPage() {
  return (
    <Page
      title="Settings"
      description="Keep the data current, follow jobs, and see what's installed."
    >
      <div className="grid gap-4 xl:grid-cols-2">
        <DataCard />
        <PluginsCard />
        <AiCard />
        <JobsCard />
        <AppearanceCard />
      </div>
    </Page>
  );
}

type RunSummary = {
  sources?: Record<
    string,
    { fetched?: number; new?: number; updated?: number; unchanged?: number; failed?: number }
  >;
  stages?: Record<string, number>;
};

function totals(job: Job) {
  const summary = job.result as RunSummary | null;
  const sources = Object.values(summary?.sources ?? {});
  const sum = (key: "fetched" | "new" | "updated" | "unchanged" | "failed") =>
    sources.reduce((total, source) => total + (source[key] ?? 0), 0);
  return sources.length
    ? {
        fetched: sum("fetched"),
        new: sum("new"),
        updated: sum("updated"),
        unchanged: sum("unchanged"),
        failed: sum("failed"),
      }
    : null;
}

function useActiveJob(): Job | undefined {
  const live = useLive((state) => state.jobs);
  const { data } = useQuery(jobsQuery());
  return useMemo(() => {
    const all = new Map<number, Job>();
    for (const job of data?.jobs ?? []) all.set(job.id, job);
    for (const job of Object.values(live)) all.set(job.id, job);
    return [...all.values()].filter(isActive).sort((a, b) => b.id - a.id)[0];
  }, [live, data]);
}

function useCancel() {
  return useMutation({
    mutationFn: async (id: number) => {
      const { data, error, response } = await api.POST("/api/jobs/{job_id}/cancel", {
        params: { path: { job_id: id } },
      });
      if (error || !data) throw new ApiError(response.status, "Couldn't cancel the job.");
      return data;
    },
    onError: (error) => notify.error(error.message),
  });
}

function DataCard() {
  const meta = useQuery(metaQuery());
  const active = useActiveJob();
  const live = useLiveEvents();
  const queryClient = useQueryClient();
  const cancel = useCancel();
  const now = useNow(30_000);

  const update = useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST("/api/jobs/update");
      if (response.status === 409 && error && "job" in error)
        return { job: error.job as Job, queued: false };
      if (!data)
        throw new ApiError(
          response.status,
          (error as { detail?: string } | undefined)?.detail ?? "The update didn't start.",
        );
      return { job: data, queued: true };
    },
    onSuccess: ({ job, queued }) => {
      live.job(job);
      void queryClient.invalidateQueries({ queryKey: JOBS_KEY });
      if (!queued)
        notify.info(`A ${job.type} is already ${job.status}`, {
          description: "Following it here.",
        });
    },
    onError: (error) => notify.error("The update didn't start", { description: error.message }),
  });

  const lastRun = meta.data?.last_run;
  const cursors = Object.entries(meta.data?.sources ?? {});

  return (
    <Card className="shadow-xs">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CloudDownload className="size-4 text-muted-foreground" />
          Data
        </CardTitle>
        <CardDescription>
          {meta.data
            ? `Updates run ${meta.data.schedule === "off" ? "only when you ask" : meta.data.schedule}; each fetches only what changed.`
            : "…"}
        </CardDescription>
        <CardAction>
          <Button
            onClick={() => update.mutate()}
            disabled={update.isPending || active !== undefined || !meta.data?.installed}
            data-testid="update-button"
          >
            {update.isPending || active ? <Spinner /> : <RefreshCw />}
            {active ? "Updating…" : "Update now"}
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        {active && <JobProgress job={active} onCancel={() => cancel.mutate(active.id)} />}
        {meta.data ? (
          <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border text-sm sm:grid-cols-4">
            {[
              ["Trials", formatNumber(meta.data.trials)],
              ["Data version", String(meta.data.data_version)],
              ...cursors.map(([name, cursor]) => [
                name === "ctgov" ? "Data through" : `${name} through`,
                formatDate(cursor),
              ]),
              [
                "Last update",
                lastRun?.finished_at ? formatRelative(lastRun.finished_at, now) : "Never",
              ],
            ].map(([term, value]) => (
              <div key={term} className="bg-card px-3 py-2.5">
                <dt className="text-xs text-muted-foreground">{term}</dt>
                <dd className="mt-0.5 font-medium tabular">{value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <Skeleton className="h-16 w-full" />
        )}
        {lastRun && (
          <p className="text-xs text-muted-foreground">
            The last {lastRun.kind} ({formatDateTime(lastRun.finished_at)}) found{" "}
            <span className="text-foreground">{formatNumber(lastRun.new)} new</span>,{" "}
            <span className="text-foreground">{formatNumber(lastRun.updated)} updated</span> and{" "}
            {formatNumber(lastRun.unchanged)} unchanged trials.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

const JOB_TONE: Record<Job["status"], string> = {
  queued: "bg-muted-foreground/50",
  running: "bg-info",
  succeeded: "bg-good",
  failed: "bg-critical",
  cancelled: "bg-warning",
};

function JobStatus({ job }: { job: Job }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium">
      <span className={cn("size-1.5 rounded-full", JOB_TONE[job.status])} />
      {humanize(job.status)}
    </span>
  );
}

function JobsCard() {
  const jobs = useQuery(jobsQuery());
  const now = useNow(30_000);
  return (
    <Card className="gap-3 shadow-xs xl:col-span-2">
      <CardHeader>
        <CardTitle>Jobs</CardTitle>
        <CardDescription>
          Installs, updates and plugin jobs, newest first. They update live.
        </CardDescription>
      </CardHeader>
      <CardContent className="px-0">
        {jobs.isError ? (
          <p className="px-4 text-sm text-destructive">{jobs.error.message}</p>
        ) : !jobs.data ? (
          <div className="space-y-2 px-4">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </div>
        ) : jobs.data.jobs.length === 0 ? (
          <p className="px-4 text-sm text-muted-foreground">
            No jobs yet. Press Update now to run one.
          </p>
        ) : (
          <Table data-testid="jobs-table">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-4">Job</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="hidden sm:table-cell">Started</TableHead>
                <TableHead className="hidden md:table-cell">Took</TableHead>
                <TableHead className="pr-4">Result</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobs.data.jobs.map((job) => {
                const counts = totals(job);
                const took =
                  job.started_at && job.finished_at
                    ? (new Date(job.finished_at).getTime() - new Date(job.started_at).getTime()) /
                      1000
                    : null;
                return (
                  <TableRow key={job.id}>
                    <TableCell className="pl-4">
                      <div className="font-medium">{humanize(job.type)}</div>
                      <div className="text-xs text-muted-foreground">
                        #{job.id} · from {job.origin}
                      </div>
                    </TableCell>
                    <TableCell>
                      <JobStatus job={job} />
                    </TableCell>
                    <TableCell className="hidden text-muted-foreground sm:table-cell">
                      <Tooltip>
                        <TooltipTrigger className="cursor-default">
                          {formatRelative(job.started_at ?? job.created_at, now)}
                        </TooltipTrigger>
                        <TooltipContent>
                          {formatDateTime(job.started_at ?? job.created_at)}
                        </TooltipContent>
                      </Tooltip>
                    </TableCell>
                    <TableCell className="hidden tabular text-muted-foreground md:table-cell">
                      {took !== null ? formatDuration(took) : isActive(job) ? "…" : "—"}
                    </TableCell>
                    <TableCell className="pr-4 whitespace-normal">
                      {job.error ? (
                        <span className="flex items-start gap-1.5 text-xs text-destructive">
                          <CircleAlert className="mt-px size-3.5 shrink-0" />
                          <span className="line-clamp-2">{job.error}</span>
                        </span>
                      ) : counts ? (
                        <span className="text-xs text-muted-foreground tabular">
                          <span className="text-foreground">{formatNumber(counts.new)}</span> new ·{" "}
                          <span className="text-foreground">{formatNumber(counts.updated)}</span>{" "}
                          updated · {formatNumber(counts.unchanged)} unchanged
                        </span>
                      ) : isActive(job) ? (
                        <span className="text-xs text-muted-foreground">
                          {job.stage ? humanize(job.stage) : "Waiting"}…
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function PluginsCard() {
  const plugins = useQuery(pluginsQuery());
  const queryClient = useQueryClient();
  const toggle = useMutation({
    mutationFn: async ({ name, enabled }: { name: string; enabled: boolean }) => {
      const { data, error, response } = await api.PATCH("/api/plugins/{name}", {
        params: { path: { name } },
        body: { enabled },
      });
      if (!data)
        throw new ApiError(
          response.status,
          (error as { detail?: string } | undefined)?.detail ?? "Couldn't change the plugin.",
        );
      return data;
    },
    onSuccess: (result) => {
      queryClient.setQueryData<{ plugins: Plugin[] }>(["plugins"], (old) =>
        old
          ? { plugins: old.plugins.map((p) => (p.name === result.plugin.name ? result.plugin : p)) }
          : old,
      );
      if (result.restart_required) {
        notify.info(`${result.plugin.name} ${result.plugin.enabled ? "enabled" : "disabled"}`, {
          description: "Restart Tri-AL (tri-al serve) to apply it.",
        });
      }
    },
    onError: (error) => notify.error(error.message),
  });

  return (
    <Card className="shadow-xs">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Puzzle className="size-4 text-muted-foreground" />
          Plugins
        </CardTitle>
        <CardDescription>
          Saved in tri-al.toml; changes apply when the server next starts.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!plugins.data ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <ul className="divide-y" data-testid="plugins">
            {plugins.data.plugins.map((plugin) => {
              const pending = plugin.enabled !== plugin.loaded;
              const settings = Object.entries(plugin.settings);
              return (
                <li key={plugin.name} className="flex items-start gap-3 py-3 first:pt-0 last:pb-0">
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{plugin.name}</span>
                      {plugin.version && (
                        <Badge
                          variant="secondary"
                          className="h-4.5 px-1.5 font-mono text-[0.65rem] font-normal"
                        >
                          {plugin.version}
                        </Badge>
                      )}
                      {pending && (
                        <Badge
                          variant="outline"
                          className="h-4.5 border-warning/40 px-1.5 text-[0.65rem] font-normal"
                        >
                          Restart to apply
                        </Badge>
                      )}
                    </div>
                    {plugin.description && (
                      <p className="text-xs text-muted-foreground">{plugin.description}</p>
                    )}
                    {settings.length > 0 && (
                      <p className="font-mono text-[0.7rem] text-muted-foreground">
                        {settings
                          .map(([key, value]) => `${key} = ${JSON.stringify(value)}`)
                          .join(" · ")}
                      </p>
                    )}
                    {plugin.problems.map((problem) => (
                      <p
                        key={problem}
                        className="flex items-start gap-1.5 text-xs text-destructive"
                      >
                        <CircleAlert className="mt-px size-3.5 shrink-0" />
                        {problem}
                      </p>
                    ))}
                  </div>
                  <Switch
                    checked={plugin.enabled}
                    disabled={!plugin.installed || toggle.isPending}
                    aria-label={`${plugin.enabled ? "Disable" : "Enable"} ${plugin.name}`}
                    onCheckedChange={(enabled) => toggle.mutate({ name: plugin.name, enabled })}
                  />
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function AppearanceCard() {
  const { theme, setTheme } = useTheme();
  return (
    <Card className="shadow-xs">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Palette className="size-4 text-muted-foreground" />
          Appearance
        </CardTitle>
        <CardDescription>System follows your computer's light or dark setting.</CardDescription>
      </CardHeader>
      <CardContent>
        <ToggleGroup
          type="single"
          variant="outline"
          value={theme}
          onValueChange={(value) => value && setTheme(value as Theme)}
          aria-label="Theme"
        >
          <ToggleGroupItem value="light" className="px-3">
            <Sun /> Light
          </ToggleGroupItem>
          <ToggleGroupItem value="dark" className="px-3">
            <Moon /> Dark
          </ToggleGroupItem>
          <ToggleGroupItem value="system" className="px-3">
            <Monitor /> System
          </ToggleGroupItem>
        </ToggleGroup>
      </CardContent>
    </Card>
  );
}
