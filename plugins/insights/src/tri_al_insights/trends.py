"""Emerging research trends: what newly registered trials are about more often than before.

For each condition and intervention, as the MeSH terms the registry maps them to (so the
spellings of one name count together), compare its share of the trials first posted in the
last few months (the window) with its share in the year before (the baseline):

    raw growth = (r / R) / (b / B)

where ``r`` and ``b`` are its trials in the window and the baseline, and ``R`` and ``B`` all
trials in them under the filter. Shares, not counts, because registrations as a whole rise
and fall (October 2025 had half the usual number).

A few trials make raw growth jump (9 against 1 is 16 times the usual share), so two things
account for how many trials there are:

- **Growth** (what is shown and ranked) adds ``PRIOR`` trials to each term, split between
  window and baseline at the usual rate ``u = R / (R + B)``. That pulls small counts toward
  no change and leaves large ones alone: 9 against 1 becomes 3.0 times, 451 against 573
  stays 1.4 times. It is never infinite, even with no trials before.
- **Confidence** comes from a significance test: if nothing had changed, each of the term's
  ``r + b`` trials would fall in the window with chance ``u``, so ``p`` is the chance of
  ``r`` or more of them doing so (an exact binomial test). Hundreds of terms are tested at
  once, so some would pass by luck; ``q`` corrects for that (Benjamini-Hochberg, the false
  discovery rate). High: ``q < 0.05``; medium: ``q < 0.25``; low: the rest.

Entries are listed by confidence, then growth. An entry needs ``min_trials`` trials and
``min_sponsors`` different lead sponsors in the window, so that one sponsor registering a
series of studies isn't a trend, and a growth of at least ``MIN_GROWTH`` unless its
confidence is high. It is ``new`` when its first trial under the filter was posted in the
window.
"""

import calendar
import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from tri_al.filters import EVERY_TRIAL, TrialFilter
from tri_al.stats import ChartContext, LinkDimension, Rows, Timeline

PRIOR = 10.0
"""Trials added to each term for its growth, split between window and baseline as usual."""

HIGH = 0.05
"""The false discovery rate (``q``) under which confidence is high."""

MEDIUM = 0.25
"""The false discovery rate under which confidence is medium."""

MIN_GROWTH = 1.2
"""Growth an entry needs to be listed, unless its confidence is high."""

GROUPS: tuple[tuple[str, LinkDimension], ...] = (
    ("Conditions", "mesh_conditions"),
    ("Interventions", "mesh_interventions"),
)

type Confidence = Literal["high", "medium", "low"]
_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True, slots=True)
class Options:
    windows: Sequence[int] = (3, 6)  # months
    baseline: int = 12  # months before each window
    top: int = 10  # entries per group and window
    min_trials: int = 3
    min_sponsors: int = 2


def months_before(day: date, months: int) -> date:
    """The same day ``months`` months earlier, or the last day of a shorter month."""
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def growths(
    recent: int, baseline: int, recent_total: int, baseline_total: int
) -> tuple[float, float | None]:
    """Growth with ``PRIOR`` trials added, and raw growth (None: no trials before)."""
    odds = baseline_total / recent_total
    usual = recent_total / (recent_total + baseline_total)
    adjusted = (recent + PRIOR * usual) / (baseline + PRIOR * (1 - usual)) * odds
    return adjusted, (recent / baseline) * odds if baseline else None


def rise_p(recent: int, trials: int, usual: float) -> float:
    """The chance of ``recent`` or more of ``trials`` in the window if each has ``usual``.

    The upper tail of a binomial distribution. A term with no more than its usual share
    can't be rising, so it gets 1.
    """
    if recent <= trials * usual or usual <= 0:
        return 1.0
    if usual >= 1 or recent > trials:
        return 0.0
    log_term = (
        math.lgamma(trials + 1)
        - math.lgamma(recent + 1)
        - math.lgamma(trials - recent + 1)
        + recent * math.log(usual)
        + (trials - recent) * math.log1p(-usual)
    )
    term = math.exp(log_term)
    total = term
    # Past the mean the terms only shrink, so stop once they no longer count.
    for k in range(recent, trials):
        term *= (trials - k) / (k + 1) * usual / (1 - usual)
        total += term
        if term < total * 1e-12:
            break
    return min(1.0, total)


def false_discovery(ps: Sequence[float]) -> list[float]:
    """Benjamini-Hochberg q-values, in the order of ``ps``."""
    m = len(ps)
    q = [1.0] * m
    smallest = 1.0
    for rank, i in reversed(list(enumerate(sorted(range(m), key=ps.__getitem__), start=1))):
        smallest = min(smallest, ps[i] * m / rank)
        q[i] = smallest
    return q


def confidence(q: float) -> Confidence:
    return "high" if q < HIGH else "medium" if q < MEDIUM else "low"


def emerging(ctx: ChartContext, filter: TrialFilter, options: Options) -> Rows:
    latest = ctx.counts(EVERY_TRIAL).latest("first_posted")
    if latest is None:
        return []
    end = latest + timedelta(days=1)
    periods = max(options.windows) + options.baseline
    edges = [months_before(end, periods - i) for i in range(periods + 1)]
    counts = ctx.counts(filter)
    totals = [0] * periods
    for day, n in counts.per_day("first_posted", edges[0], latest).items():
        totals[bisect_right(edges, day) - 1] += n

    timelines = {
        dimension: counts.timelines(
            dimension,
            "first_posted",
            edges,
            recent=max(options.windows),
            at_least=options.min_trials,
        )
        for _, dimension in GROUPS
    }
    # Those with no trials before the longest window, as far back as the periods go: were
    # there ever any?
    unseen = {
        dimension: [
            line.value
            for line in lines
            if line.value is not None and not any(line.trials[: periods - max(options.windows)])
        ]
        for dimension, lines in timelines.items()
    }
    first = {
        dimension: counts.first_dates(dimension, "first_posted", values)
        for dimension, values in unseen.items()
    }

    rows: Rows = []
    for months in sorted(options.windows):
        start = periods - months
        base = start - options.baseline
        since = edges[start]
        recent_total, baseline_total = sum(totals[start:]), sum(totals[base:start])
        window = f"{months}m"
        rows.append(
            {
                "type": "window",
                "window": window,
                "label": f"{months} months",
                "since": since.isoformat(),
                "until": latest.isoformat(),
                "baseline_since": edges[base].isoformat(),
                "trials": recent_total,
                "baseline_trials": baseline_total,
            }
        )
        if not recent_total or not baseline_total:
            continue
        usual = recent_total / (recent_total + baseline_total)
        for group, dimension in GROUPS:
            tested = [
                (line, *entry)
                for line in timelines[dimension]
                if (entry := _entry(line, start, base, options)) is not None
            ]
            ps = [rise_p(r, r + b, usual) for _, r, b, _ in tested]
            qs = false_discovery(ps)
            entries = []
            for (line, recent, baseline, sponsors), p, q in zip(tested, ps, qs, strict=True):
                growth, raw = growths(recent, baseline, recent_total, baseline_total)
                level = confidence(q)
                if level != "high" and growth < MIN_GROWTH:
                    continue
                began = first[dimension].get(line.value or "")
                entries.append(
                    {
                        "type": "item",
                        "window": window,
                        "group": group,
                        "key": line.value,
                        "label": line.label,
                        "value": recent,
                        "baseline": baseline,
                        "expected": round(baseline * recent_total / baseline_total, 1),
                        "growth": round(growth, 2),
                        "raw_growth": None if raw is None else round(raw, 2),
                        "p": float(f"{p:.2g}"),
                        "q": float(f"{q:.2g}"),
                        "confidence": level,
                        "tested": len(tested),
                        "new": began is not None and began >= since,
                        "sponsors": sponsors,
                        "series": list(line.trials[base:]),
                        "recent": months,
                        "filter": {"mesh": [line.value], "first_posted": f"{since.isoformat()}.."},
                    }
                )
            entries.sort(key=_rank)
            rows += entries[: options.top]
    return rows


def _entry(line: Timeline, start: int, base: int, options: Options) -> tuple[int, int, int] | None:
    """Trials in the window and the baseline, and lead sponsors in the window; or None."""
    recent = sum(line.trials[start:])
    sponsors = sum(line.sponsors[start:])
    if recent < options.min_trials or sponsors < options.min_sponsors:
        return None
    return recent, sum(line.trials[base:start]), sponsors


def _rank(row: dict[str, Any]) -> tuple[int, float, int, str]:
    return (_ORDER[row["confidence"]], -row["growth"], -row["value"], row["label"])
