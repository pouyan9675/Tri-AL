import { useLabels } from "@/lib/labels";
import { cn } from "@/lib/utils";

export type StatusTone = "good" | "info" | "warning" | "critical" | "neutral" | "muted";

const TONES: Record<string, StatusTone> = {
  RECRUITING: "good",
  ENROLLING_BY_INVITATION: "good",
  AVAILABLE: "good",
  APPROVED_FOR_MARKETING: "good",
  NOT_YET_RECRUITING: "info",
  ACTIVE_NOT_RECRUITING: "info",
  COMPLETED: "neutral",
  SUSPENDED: "warning",
  TEMPORARILY_NOT_AVAILABLE: "warning",
  TERMINATED: "critical",
  WITHDRAWN: "critical",
};

/** A status tone as a filled dot or marker. */
export const STATUS_DOT: Record<StatusTone, string> = {
  good: "bg-good",
  info: "bg-info",
  warning: "bg-warning",
  critical: "bg-critical",
  neutral: "bg-foreground/55",
  muted: "bg-muted-foreground/40",
};

const TINT: Record<StatusTone, string> = {
  good: "border-good/25 bg-good/8",
  info: "border-info/25 bg-info/8",
  warning: "border-warning/35 bg-warning/10",
  critical: "border-critical/25 bg-critical/8",
  neutral: "border-border bg-muted/60",
  muted: "border-border bg-transparent text-muted-foreground",
};

/** How a status is coloured: green when enrolling, blue before or after, red when stopped. */
export function statusTone(status: string | null | undefined): StatusTone {
  return (status && TONES[status]) || "muted";
}

/** A trial's overall status: always its name, with a colored dot. */
export function StatusBadge({ status, className }: { status: string | null; className?: string }) {
  const label = useLabels();
  const tone = statusTone(status);
  return (
    <span
      className={cn(
        "inline-flex h-6 max-w-full items-center gap-1.5 rounded-full border px-2 text-xs font-medium whitespace-nowrap",
        TINT[tone],
        className,
      )}
    >
      <span className={cn("size-1.5 shrink-0 rounded-full", STATUS_DOT[tone])} />
      <span className="truncate">{status ? label("status", status) : "No status"}</span>
    </span>
  );
}
