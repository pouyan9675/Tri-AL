import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { metaQuery } from "@/api/queries";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatDate, formatDateTime, formatRelative } from "@/lib/format";
import { useLive } from "@/lib/live-context";
import { useNow } from "@/lib/use-now";
import { cn } from "@/lib/utils";

const FRESH_MS = 90_000;

/** "Data updated 2 hours ago", or "just now" (highlighted) right after an update lands. */
export function DataStatus() {
  const { data: meta } = useQuery(metaQuery());
  const changedAt = useLive((state) => state.dataChangedAt);
  const now = useNow(15_000);
  if (!meta?.installed) return null;

  const fresh = changedAt !== null && now - changedAt < FRESH_MS;
  const finished = meta.last_run?.finished_at;
  const text = fresh
    ? "Data updated just now"
    : finished
      ? `Data updated ${formatRelative(finished, now)}`
      : "Data installed";
  const through = Object.values(meta.sources).filter(Boolean).sort().at(-1);

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link
          to="/settings"
          data-testid="data-status"
          className={cn(
            "hidden h-8 items-center gap-2 rounded-full border px-3 text-xs whitespace-nowrap text-muted-foreground transition-colors hover:bg-muted hover:text-foreground sm:flex",
            fresh && "border-brand/40 bg-brand/10 text-foreground",
          )}
        >
          <span
            className={cn("size-1.5 rounded-full bg-good", fresh && "animate-pulse bg-brand")}
          />
          {text}
        </Link>
      </TooltipTrigger>
      <TooltipContent side="bottom" align="end">
        <div className="space-y-0.5">
          {through && <div>ClinicalTrials.gov data through {formatDate(through)}</div>}
          {finished && (
            <div className="opacity-80">
              Last {meta.last_run?.kind}: {formatDateTime(finished)}
            </div>
          )}
          <div className="opacity-80">Data version {meta.data_version}</div>
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
