import { X } from "lucide-react";
import type { Job } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Spinner } from "@/components/ui/spinner";
import { formatDuration, formatNumber, humanize } from "@/lib/format";
import { useNow } from "@/lib/use-now";

const STAGES: Record<string, string> = {
  download: "Downloading",
  fetch: "Fetching studies",
  load: "Loading trials",
  write: "Writing trials",
  index: "Building indexes",
  enrich: "Enriching",
  stats: "Computing charts",
  check: "Checking the database",
  commit: "Committing",
  swap: "Swapping in the new database",
};

const BYTES = new Intl.NumberFormat("en-US", {
  style: "unit",
  unit: "megabyte",
  maximumFractionDigits: 0,
});

function amount(value: number, unit: string | null): string {
  if (unit === "bytes") return BYTES.format(value / 1e6);
  return `${formatNumber(value)}${unit ? ` ${unit}` : ""}`;
}

/** A running or queued job as it streams in: stage, a bar when the total is known, time. */
export function JobProgress({ job, onCancel }: { job: Job; onCancel?: () => void }) {
  const now = useNow(1000);
  const started = job.started_at ? new Date(job.started_at).getTime() : null;
  const percent = job.total ? Math.min(100, (job.progress / job.total) * 100) : null;
  const stage =
    job.status === "queued"
      ? "Waiting for the worker"
      : job.stage
        ? (STAGES[job.stage] ?? humanize(job.stage))
        : "Starting";

  return (
    <div
      className="space-y-3 rounded-lg border bg-muted/30 p-4"
      data-testid="job-progress"
      aria-live="polite"
    >
      <div className="flex items-center gap-3">
        <Spinner className="size-4 text-brand" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">
            {humanize(job.type)} · {stage}
            {job.cancel_requested && <span className="text-muted-foreground"> · cancelling…</span>}
          </div>
          <div className="truncate text-xs text-muted-foreground">
            {job.message ??
              (job.total
                ? `${amount(job.progress, job.unit)} of ${amount(job.total, job.unit)}`
                : job.progress
                  ? amount(job.progress, job.unit)
                  : `Job ${job.id}, from ${job.origin}`)}
          </div>
        </div>
        <span className="text-xs tabular text-muted-foreground">
          {started ? formatDuration(Math.max(0, (now - started) / 1000)) : "queued"}
        </span>
        {onCancel && !job.cancel_requested && (
          <Button variant="ghost" size="icon-sm" aria-label="Cancel" onClick={onCancel}>
            <X />
          </Button>
        )}
      </div>
      {percent !== null ? (
        <Progress value={percent} className="h-1.5" />
      ) : (
        <div className="relative h-1.5 overflow-hidden rounded-full bg-muted">
          <div className="absolute inset-y-0 w-1/3 animate-[indeterminate_1.4s_ease-in-out_infinite] rounded-full bg-brand" />
        </div>
      )}
    </div>
  );
}
