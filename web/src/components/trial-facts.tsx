/** A trial's key facts on one wrapping line: its ID, status, phase, start, size, sponsor. */
import type { TrialSummary } from "@/api/client";
import { StatusBadge } from "@/components/status-badge";
import { formatDate, formatNumber } from "@/lib/format";

export function TrialFacts({ trial, phase }: { trial: TrialSummary; phase?: string }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <span className="font-mono text-[0.7rem] text-foreground/70">{trial.source_id}</span>
      <StatusBadge status={trial.status} className="h-5" />
      {phase && <span>{phase}</span>}
      {trial.start_date && <span>Started {formatDate(trial.start_date)}</span>}
      {trial.enrollment !== null && (
        <span className="tabular">{formatNumber(trial.enrollment)} enrolled</span>
      )}
      {trial.lead_sponsor && (
        <span className="max-w-72 truncate" title={trial.lead_sponsor}>
          {trial.lead_sponsor}
        </span>
      )}
    </div>
  );
}
