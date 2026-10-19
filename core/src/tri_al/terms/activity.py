"""A term's activity: an overview, trials over time with momentum, and upcoming results."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import numpy.typing as npt

from tri_al.stats.index import NO_SPONSOR, NULL_DAY, Mask, day_number, from_day_number
from tri_al.stats.methods import (
    Confidence,
    confidence,
    months_before,
    smoothed_ratio,
    two_sided_p,
)
from tri_al.storage import TrialSummary
from tri_al.terms.scope import (
    ACTIVE,
    DIMENSION,
    PHASE_GROUPS,
    STOPPED,
    Scope,
    TermCount,
    TermRef,
)

YEARS = 30
"""Years the timeline goes back at most."""

WINDOWS = (3, 6, 12)
"""Months of the windows momentum compares with the ``BASELINE`` months before each."""

BASELINE = 12

PRIOR = 10.0
"""Trials added to smooth momentum, as for emerging trends (``tri_al_insights.trends``)."""

READOUT_MONTHS = 24
"""How far ahead upcoming results go."""


@dataclass(frozen=True, slots=True)
class Overview:
    term: TermRef
    trials: int  # the term's within the filter
    registry_trials: int  # the term's without the filter
    within: int  # the filter's
    direct: int  # the term's tagged with it, not only with a narrower term
    narrower: list[TermCount]  # most trials first
    active: int
    completed: int
    stopped: int
    with_results: int
    lead_sponsors: int
    industry: int  # trials with an industry lead sponsor
    countries: int
    first_start: date | None
    as_of: date


def overview(scope: Scope, narrower: dict[int, TermCount], *, limit: int = 12) -> Overview:
    index, trials = scope.index, scope.trials
    link = index.link(DIMENSION[scope.ref.kind])
    tagged = link.trial[(link.value == scope.term_id) & trials[link.trial]]
    sponsors = index.lead_sponsors[trials]
    countries = index.link("countries")
    starts = index.dates("start_date")[trials]
    starts = starts[starts != NULL_DAY]
    first = int(starts.min()) if len(starts) else None
    return Overview(
        term=scope.ref,
        trials=scope.count,
        registry_trials=int(np.count_nonzero(scope.everywhere)),
        within=int(np.count_nonzero(scope.within)),
        direct=len(np.unique(tagged)),
        narrower=sorted(narrower.values(), key=lambda term: (-term.trials, term.term))[:limit],
        active=_count(trials & scope.coded("status", ACTIVE)),
        completed=_count(trials & scope.coded("status", ("COMPLETED",))),
        stopped=_count(trials & scope.coded("status", STOPPED)),
        with_results=_count(trials & scope.coded("has_results", (True,))),
        lead_sponsors=len(np.unique(sponsors[sponsors != NO_SPONSOR])),
        industry=_count(trials & scope.coded("sponsor_class", ("INDUSTRY",))),
        countries=len(np.unique(countries.value[trials[countries.trial]])),
        first_start=None if first is None else from_day_number(first),
        as_of=scope.as_of,
    )


# --- trials over time --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class YearCount:
    year: int
    trials: int  # started that year
    phases: list[int]  # by phase group, in ``PHASE_GROUPS`` order
    share: float  # of the filter's trials started that year
    new_sponsors: int  # lead sponsors whose first trial of the term started that year


@dataclass(frozen=True, slots=True)
class Momentum:
    """The term's share of newly posted trials in a recent window against the year before."""

    months: int
    since: date
    until: date
    trials: int  # the term's first posted in the window
    baseline: int  # ... in the ``BASELINE`` months before it
    expected: float  # in the window at its usual share
    growth: float  # its share in the window over its share before, smoothed
    raw_growth: float | None  # unsmoothed; None with no trials before
    p: float  # two-sided exact binomial test
    confidence: Confidence
    direction: Literal["rising", "falling", "steady"]


@dataclass(frozen=True, slots=True)
class Timeline:
    years: list[YearCount]
    partial: bool  # the last year isn't over
    momentum: list[Momentum]


def timeline(scope: Scope) -> Timeline:
    index = scope.index
    starts = index.dates("start_date")
    today = day_number(scope.as_of)
    started = (starts != NULL_DAY) & (starts <= today)
    years = _years(starts)
    term = scope.trials & started
    within = scope.within & started
    first_year = int(years[term].min()) if term.any() else scope.as_of.year
    low = max(first_year, scope.as_of.year - YEARS + 1)
    span = scope.as_of.year - low + 1

    def per_year(mask: Mask) -> npt.NDArray[np.int64]:
        offsets = years[mask & (years >= low)] - low
        return np.bincount(offsets, minlength=span)[:span]

    term_years, within_years = per_year(term), per_year(within)
    groups = scope.phase_groups()
    phases = [per_year(term & (groups == g)) for g in range(len(PHASE_GROUPS))]

    sponsors = index.lead_sponsors[term]
    sponsor_years = years[term]
    known = sponsors != NO_SPONSOR
    new = np.zeros(span, np.int64)
    if known.any():
        unique, inverse = np.unique(sponsors[known], return_inverse=True)
        first = np.full(len(unique), np.iinfo(np.int64).max, np.int64)
        np.minimum.at(first, inverse, sponsor_years[known])
        new = np.bincount(first[first >= low] - low, minlength=span)[:span]

    return Timeline(
        years=[
            YearCount(
                year=low + i,
                trials=int(term_years[i]),
                phases=[int(counts[i]) for counts in phases],
                share=round(float(term_years[i] / within_years[i]), 5) if within_years[i] else 0.0,
                new_sponsors=int(new[i]),
            )
            for i in range(span)
        ],
        partial=(scope.as_of.month, scope.as_of.day) != (12, 31),
        momentum=[_momentum(scope, months) for months in WINDOWS],
    )


def _momentum(scope: Scope, months: int) -> Momentum:
    posted = scope.index.dates("first_posted")
    end = scope.as_of
    since = months_before(end, months)
    base = months_before(since, BASELINE)
    window = (posted > day_number(since)) & (posted <= day_number(end))
    before = (posted > day_number(base)) & (posted <= day_number(since))
    r, b = _count(scope.trials & window), _count(scope.trials & before)
    total_r, total_b = _count(scope.within & window), _count(scope.within & before)
    if not total_r or not total_b:
        return Momentum(months, since, end, r, b, 0.0, 1.0, None, 1.0, "low", "steady")
    usual = total_r / (total_r + total_b)
    p = two_sided_p(r, r + b, usual)
    growth = smoothed_ratio(r, b, total_r, total_b, PRIOR)
    level = confidence(p)
    return Momentum(
        months=months,
        since=since,
        until=end,
        trials=r,
        baseline=b,
        expected=round((r + b) * usual, 1),
        growth=round(growth, 3),
        raw_growth=round((r / total_r) / (b / total_b), 3) if b else None,
        p=float(f"{p:.2g}"),
        confidence=level,
        direction="steady" if level == "low" else "rising" if growth > 1 else "falling",
    )


# --- upcoming results --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Readout:
    trial: TrialSummary
    primary_completion: date
    estimated: bool  # the date is the sponsor's estimate


@dataclass(frozen=True, slots=True)
class QuarterCount:
    quarter: str  # 2027-Q1
    start: date
    trials: int
    phases: list[int]  # by phase group


@dataclass(frozen=True, slots=True)
class Readouts:
    """Active trials by when their primary outcome is due: when their main results come."""

    as_of: date
    until: date
    total: int  # active trials due from ``as_of`` to ``until``
    overdue: int  # active trials whose primary completion date has passed
    quarters: list[QuarterCount]
    trials: list[Readout]  # the first ``limit``, soonest first


def readouts(scope: Scope, *, limit: int = 200) -> Readouts:
    index = scope.index
    due = index.dates("primary_completion_date")
    today, until = scope.as_of, months_before(scope.as_of, -READOUT_MONTHS)
    active = scope.trials & scope.coded("status", ACTIVE) & (due != NULL_DAY)
    upcoming = active & (due >= day_number(today)) & (due <= day_number(until))
    ids = np.flatnonzero(upcoming)
    ids = ids[np.lexsort((ids, due[ids]))]

    groups = scope.phase_groups()
    first = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    quarters: list[QuarterCount] = []
    start = first
    while start <= until:
        end = months_before(start, -3)
        inside = ids[(due[ids] >= day_number(start)) & (due[ids] < day_number(end))]
        quarters.append(
            QuarterCount(
                quarter=f"{start.year}-Q{(start.month - 1) // 3 + 1}",
                start=start,
                trials=len(inside),
                phases=[int(n) for n in np.bincount(groups[inside], minlength=len(PHASE_GROUPS))],
            )
        )
        start = end

    shown = [int(i) for i in ids[:limit]]
    estimated = scope.index.coded("primary_completion_date_type")
    estimate = estimated.code_of("ESTIMATED")
    summaries = {summary.id: summary for summary in scope.reader.summaries(shown)}
    return Readouts(
        as_of=today,
        until=until,
        total=len(ids),
        overdue=_count(active & (due < day_number(today))),
        quarters=quarters,
        trials=[
            Readout(
                summaries[key],
                from_day_number(int(due[key])),
                estimate is not None and int(estimated.values[key]) == estimate,
            )
            for key in shown
            if key in summaries
        ],
    )


def _years(days: npt.NDArray[np.int32]) -> npt.NDArray[np.int64]:
    """The calendar year of each day number (garbage where the day is missing)."""
    safe = np.where(days == NULL_DAY, 0, days)
    years: npt.NDArray[np.int64] = (
        safe.astype("datetime64[D]").astype("datetime64[Y]").astype(np.int64) + 1970
    )
    return years


def _count(mask: Mask) -> int:
    return int(np.count_nonzero(mask))
