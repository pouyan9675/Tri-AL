/** Pure helpers for the term analyses, kept apart so tests needn't render anything. */

const GROUP_OF: Record<string, number> = {
  EARLY_PHASE1: 0,
  PHASE1: 0,
  PHASE1_PHASE2: 1,
  PHASE2: 1,
  PHASE2_PHASE3: 2,
  PHASE3: 2,
  PHASE4: 3,
};

/** A trial's phase group, as the API counts them: a combined phase goes with the later one. */
export function phaseGroupOf(phase: string | null | undefined): number {
  if (!phase) return 4;
  return GROUP_OF[phase] ?? 4;
}

export type StepCurve = { months: number[]; values: number[] };

/**
 * A Kaplan-Meier curve's value at ``month``: the value after the last step at or before it,
 * or ``before`` ahead of the first step (1 for "still running", 0 for "with results").
 */
export function stepAt(curve: StepCurve, month: number, before: number): number {
  let low = 0;
  let high = curve.months.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if ((curve.months[mid] ?? 0) <= month) low = mid + 1;
    else high = mid;
  }
  return low === 0 ? before : (curve.values[low - 1] ?? before);
}

/** Several curves on one month grid (0 to ``until``), one key each, for one chart. */
export function onGrid(
  curves: Record<string, StepCurve | undefined>,
  until: number,
  before: number,
  step = 1,
): Record<string, number>[] {
  const rows: Record<string, number>[] = [];
  for (let month = 0; month <= until; month += step) {
    const row: Record<string, number> = { month };
    for (const [key, curve] of Object.entries(curves)) {
      if (curve && curve.months.length > 0) row[key] = stepAt(curve, month, before);
    }
    rows.push(row);
  }
  return rows;
}

/** Where a standardized difference goes on a track from -limit to +limit, as 0 to 1. */
export function trackPosition(difference: number, limit = 1): number {
  const clamped = Math.max(-limit, Math.min(limit, difference));
  return (clamped + limit) / (2 * limit);
}
