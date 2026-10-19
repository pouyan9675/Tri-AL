/**
 * A trial's life on one line: registered, started, primary completion, completion and
 * results, each actual or estimated, with today's status where it falls and the status
 * changes Tri-AL's updates have seen.
 */
import type { Change, TrialDetail } from "@/api/client";
import { STATUS_DOT, type StatusTone, statusTone } from "@/components/status-badge";
import { Card } from "@/components/ui/card";
import { formatDate } from "@/lib/format";
import { useLabels } from "@/lib/labels";
import { cn } from "@/lib/utils";

type Label = ReturnType<typeof useLabels>;

/**
 * - `done`: it happened (an actual date, or a past one the registry didn't qualify).
 * - `planned`: an estimated date still ahead.
 * - `overdue`: an estimated date that has passed without being confirmed.
 * - `cancelled`: an estimated date of a trial that stopped, so it won't happen.
 */
export type MilestoneState = "done" | "planned" | "overdue" | "cancelled";

export type Milestone = {
  key: string;
  kind: "milestone" | "change" | "now";
  title: string;
  date: string; // YYYY-MM-DD
  state: MilestoneState;
  note?: string;
  tone?: StatusTone;
};

const STOPPED = new Set(["TERMINATED", "WITHDRAWN"]);
const ENDED = new Set(["COMPLETED", "TERMINATED", "WITHDRAWN"]);

const month = new Intl.DateTimeFormat("en-US", {
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/** A `YYYY-MM-DD` date at month precision: "Aug 2026". */
export function formatMonth(value: string): string {
  return month.format(new Date(`${value.slice(0, 10)}T00:00:00Z`));
}

const DAY = 24 * 3600 * 1000;

function days(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY);
}

/** The time between two dates, roughly: "2 yr 10 mo", "5 mo", "3 wk"; "" under a week. */
export function formatSpan(from: string, to: string): string {
  const span = Math.abs(days(from, to));
  const months = span < 28 ? 0 : Math.max(1, Math.round(span / (365.25 / 12)));
  if (months >= 12) {
    const years = Math.floor(months / 12);
    const rest = months % 12;
    return rest ? `${years} yr ${rest} mo` : `${years} yr`;
  }
  if (months >= 1) return `${months} mo`;
  const weeks = Math.floor(span / 7);
  return weeks >= 1 ? `${weeks} wk` : "";
}

function state(
  date: string,
  type: string | null,
  status: string | null,
  today: string,
): MilestoneState {
  const past = date <= today;
  if (type === "ACTUAL" || (type === null && past)) return "done";
  if (status && STOPPED.has(status)) return "cancelled";
  return past ? "overdue" : "planned";
}

/** The trial's milestones in date order, with today's status among them while it runs. */
export function milestones(
  trial: TrialDetail,
  changes: Change[] | undefined,
  label: Label,
  today: string,
): Milestone[] {
  const out: Milestone[] = [];
  const status = trial.status;
  if (trial.first_posted) {
    out.push({
      key: "posted",
      kind: "milestone",
      title: "Registered",
      date: trial.first_posted,
      state: "done",
      note: "First posted",
    });
  }
  if (trial.start_date) {
    const s = state(trial.start_date, trial.start_date_type, status, today);
    out.push({
      key: "start",
      kind: "milestone",
      title: s === "done" ? "Started" : s === "cancelled" ? "Planned start" : "Expected start",
      date: trial.start_date,
      state: s,
    });
  }
  if (trial.primary_completion_date) {
    out.push({
      key: "primary",
      kind: "milestone",
      title: "Primary completion",
      date: trial.primary_completion_date,
      state: state(
        trial.primary_completion_date,
        trial.primary_completion_date_type,
        status,
        today,
      ),
      note: "Main outcome measured",
    });
  }
  if (trial.completion_date) {
    const s = state(trial.completion_date, trial.completion_date_type, status, today);
    const stopped = status === "TERMINATED" && s === "done";
    out.push({
      key: "completion",
      kind: "milestone",
      title: stopped ? "Stopped early" : "Study completion",
      date: trial.completion_date,
      state: s,
      note: stopped ? (trial.why_stopped ?? undefined) : undefined,
      tone: stopped ? "critical" : undefined,
    });
  }
  if (trial.results_first_posted) {
    out.push({
      key: "results",
      kind: "milestone",
      title: "Results posted",
      date: trial.results_first_posted,
      state: "done",
      tone: "good",
    });
  }
  for (const [index, change] of (changes ?? []).entries()) {
    if (change.field !== "status" || !change.changed_at || typeof change.new !== "string") continue;
    out.push({
      key: `change-${index}`,
      kind: "change",
      title: label("status", change.new),
      date: change.changed_at.slice(0, 10),
      state: "done",
      note: typeof change.old === "string" ? `Was ${label("status", change.old)}` : undefined,
      tone: statusTone(change.new),
    });
  }
  if (!status || !ENDED.has(status)) {
    // The card's header says when the status was verified; for an unknown status, that
    // date and the last known status are the point, so they go here too.
    const unknown = status === "UNKNOWN";
    const known =
      unknown && trial.last_known_status
        ? `last known ${label("status", trial.last_known_status).toLowerCase()}`
        : null;
    const verified =
      unknown && trial.status_verified ? `verified ${formatMonth(trial.status_verified)}` : null;
    out.push({
      key: "now",
      kind: "now",
      title: status ? label("status", status) : "No status",
      date: today,
      state: "done",
      note: [known, verified, status === "SUSPENDED" ? trial.why_stopped : null]
        .filter(Boolean)
        .join(" · "),
      tone: statusTone(status),
    });
  }
  // Stable: milestones on the same day keep the order above.
  return out
    .map((item, index) => ({ item, index }))
    .sort((a, b) => a.item.date.localeCompare(b.item.date) || a.index - b.index)
    .map(({ item }) => item);
}

function Dot({ milestone }: { milestone: Milestone }) {
  const { kind, state: s, tone } = milestone;
  if (kind === "now") {
    return (
      <span className="relative flex size-4 items-center justify-center">
        <span
          className={cn(
            "absolute inset-0 animate-ping rounded-full opacity-40",
            STATUS_DOT[tone ?? "muted"],
          )}
        />
        <span
          className={cn(
            "relative size-3 rounded-full ring-4 ring-card",
            STATUS_DOT[tone ?? "muted"],
          )}
        />
      </span>
    );
  }
  if (kind === "change") {
    return (
      <span className={cn("size-2.5 rotate-45 ring-4 ring-card", STATUS_DOT[tone ?? "muted"])} />
    );
  }
  return (
    <span
      className={cn(
        "size-3 rounded-full ring-4 ring-card",
        s === "done" && (tone ? STATUS_DOT[tone] : "bg-foreground/80"),
        s === "planned" && "border-2 border-dashed border-foreground/45 bg-card",
        s === "overdue" && "border-2 border-dashed border-warning bg-card",
        s === "cancelled" && "border-2 border-muted-foreground/30 bg-card",
      )}
    />
  );
}

function Detail({ milestone, className }: { milestone: Milestone; className?: string }) {
  const { title, date, state: s, note, kind } = milestone;
  const qualifier =
    s === "planned"
      ? "Estimated"
      : s === "overdue"
        ? "Estimated, not confirmed"
        : s === "cancelled"
          ? "Won't happen"
          : null;
  return (
    <div className={cn("min-w-0 space-y-0.5", className)}>
      <div
        className={cn(
          "text-sm leading-tight font-medium",
          s === "cancelled" && "text-muted-foreground line-through",
          kind === "now" && "font-semibold",
        )}
      >
        {kind === "now" ? `Now: ${title}` : title}
      </div>
      <div className="text-xs text-muted-foreground tabular">
        {kind === "now" ? "Today" : formatDate(date)}
        {qualifier && (
          <span className={cn("ml-1", s === "overdue" && "text-warning")}>· {qualifier}</span>
        )}
      </div>
      {note && (
        <div className="line-clamp-2 text-xs text-muted-foreground/90" title={note}>
          {note}
        </div>
      )}
    </div>
  );
}

/** A stretch is solid when both its ends happened, dashed while either is unconfirmed. */
function settled(from: Milestone, to: Milestone): boolean {
  return from.state === "done" && to.state === "done";
}

export function TrialTimeline({
  trial,
  changes,
  today = new Date().toISOString().slice(0, 10),
}: {
  trial: TrialDetail;
  changes?: Change[];
  today?: string;
}) {
  const label = useLabels();
  const items = milestones(trial, changes, label, today);
  if (items.length === 0) return null;

  return (
    <Card className="gap-4 p-4 shadow-xs sm:p-5" data-testid="timeline">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-[0.95rem] font-semibold">Timeline</h2>
        <p className="text-xs text-muted-foreground">
          {trial.status_verified && <>Status verified {formatMonth(trial.status_verified)} · </>}
          Last update posted {formatDate(trial.last_update)}
        </p>
      </div>

      {/* Across, from medium screens up. */}
      <ol
        className="hidden md:grid"
        style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}
      >
        {items.map((item, index) => {
          const next = items[index + 1];
          const previous = items[index - 1];
          const span =
            next && next.kind !== "now" && item.kind !== "now"
              ? formatSpan(item.date, next.date)
              : "";
          return (
            <li
              key={item.key}
              className="relative flex flex-col items-center gap-2.5 px-2 text-center"
            >
              <div className="relative flex h-4 w-full items-center justify-center">
                {previous && (
                  <span
                    className={cn(
                      "absolute top-1/2 right-1/2 left-0 border-t-2",
                      settled(previous, item)
                        ? "border-foreground/30"
                        : "border-dashed border-foreground/20",
                    )}
                  />
                )}
                {next && (
                  <span
                    className={cn(
                      "absolute top-1/2 right-0 left-1/2 border-t-2",
                      settled(item, next)
                        ? "border-foreground/30"
                        : "border-dashed border-foreground/20",
                    )}
                  />
                )}
                {span && (
                  <span className="absolute -top-3.5 left-full -translate-x-1/2 rounded bg-card px-1 text-[0.65rem] whitespace-nowrap text-muted-foreground tabular">
                    {span}
                  </span>
                )}
                <Dot milestone={item} />
              </div>
              <Detail milestone={item} />
            </li>
          );
        })}
      </ol>

      {/* Down, on small screens. */}
      <ol className="flex flex-col md:hidden">
        {items.map((item, index) => {
          const next = items[index + 1];
          return (
            <li key={item.key} className="relative flex gap-3 pb-4 last:pb-0">
              {next && (
                <span
                  className={cn(
                    "absolute top-4 bottom-0 left-[7px] border-l-2",
                    settled(item, next)
                      ? "border-foreground/30"
                      : "border-dashed border-foreground/20",
                  )}
                />
              )}
              <span className="relative flex h-4 w-4 shrink-0 items-center justify-center">
                <Dot milestone={item} />
              </span>
              <Detail milestone={item} className="-mt-0.5" />
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
