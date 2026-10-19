"""Statistical methods that analyses share: significance, smoothing, survival and dates.

Written with the standard library and numpy only, so the core needs no scipy. The emerging
trends of the ``insights`` plugin and the term analyses (``tri_al.terms``) use the same
tests, so their confidence means the same thing everywhere.
"""

import calendar
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import numpy.typing as npt

HIGH = 0.05
"""The false discovery rate (``q``) under which confidence is high."""

MEDIUM = 0.25
"""The false discovery rate under which confidence is medium."""

type Confidence = Literal["high", "medium", "low"]


def months_before(day: date, months: int) -> date:
    """The same day ``months`` months earlier, or the last day of a shorter month."""
    index = day.year * 12 + day.month - 1 - months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def excess_p(observed: int, trials: int, rate: float) -> float:
    """The chance of ``observed`` or more of ``trials`` if each happens with chance ``rate``.

    The upper tail of a binomial distribution: a one-sided exact test that something is
    more common than chance. No more than the expected number gets 1.
    """
    if observed <= trials * rate or rate <= 0:
        return 1.0
    if rate >= 1 or observed > trials:
        return 0.0
    log_term = (
        math.lgamma(trials + 1)
        - math.lgamma(observed + 1)
        - math.lgamma(trials - observed + 1)
        + observed * math.log(rate)
        + (trials - observed) * math.log1p(-rate)
    )
    term = math.exp(log_term)
    total = term
    # Past the mean the terms only shrink, so stop once they no longer count.
    for k in range(observed, trials):
        term *= (trials - k) / (k + 1) * rate / (1 - rate)
        total += term
        if term < total * 1e-12:
            break
    return min(1.0, total)


def two_sided_p(observed: int, trials: int, rate: float) -> float:
    """An exact test that ``observed`` of ``trials`` differs from chance ``rate`` either way.

    Twice the smaller tail, at most 1.
    """
    if trials == 0:
        return 1.0
    if observed > trials * rate:
        return min(1.0, 2 * excess_p(observed, trials, rate))
    return min(1.0, 2 * excess_p(trials - observed, trials, 1 - rate))


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


def smoothed_ratio(
    inside: int, outside: int, inside_total: int, outside_total: int, prior: float
) -> float:
    """How many times more common something is inside a group than outside it, smoothed.

    ``inside`` of ``inside_total`` against ``outside`` of ``outside_total``, with ``prior``
    cases added, split between the two at the usual rate. Small counts move toward no
    difference (1) and the ratio is never infinite; large counts barely move.
    """
    usual = inside_total / (inside_total + outside_total)
    return ((inside + prior * usual) / inside_total) / (
        (outside + prior * (1 - usual)) / outside_total
    )


def standardized_difference(
    value: float, baseline: float, *, sd: float | None = None, share: bool = False
) -> float:
    """How far ``value`` is from ``baseline`` in standard deviations (Cohen's d).

    For shares (``share``), the two binomial spreads pooled; otherwise ``sd``. 0.2 is a
    small difference, 0.5 a medium one and 0.8 a large one.
    """
    if share:
        spread = math.sqrt((value * (1 - value) + baseline * (1 - baseline)) / 2)
    else:
        spread = sd or 0.0
    return 0.0 if spread <= 0 else (value - baseline) / spread


def weighted_quantile(
    values: npt.NDArray[np.floating] | npt.NDArray[np.integer],
    weights: npt.NDArray[np.floating],
    q: float,
) -> float | None:
    """The ``q`` quantile (0.5: the median) of ``values`` with ``weights``; None if empty."""
    keep = weights > 0
    values, weights = values[keep], weights[keep]
    if len(values) == 0:
        return None
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order])
    at = int(np.searchsorted(cumulative, q * cumulative[-1], side="left"))
    return float(values[order][min(at, len(order) - 1)])


@dataclass(frozen=True, slots=True)
class Survival:
    """A Kaplan-Meier curve: the share still without the event at each time."""

    times: tuple[float, ...]  # the event times, ascending
    survival: tuple[float, ...]  # the share without the event just after each time
    at_risk: int  # subjects
    events: int
    median: float | None  # when half have had the event; None if fewer ever did

    def at(self, time: float) -> float:
        """The share without the event at ``time``."""
        i = int(np.searchsorted(np.asarray(self.times), time, side="right"))
        return 1.0 if i == 0 else self.survival[i - 1]


def kaplan_meier(
    durations: npt.NDArray[np.floating] | npt.NDArray[np.integer], events: npt.NDArray[np.bool_]
) -> Survival:
    """The Kaplan-Meier estimate from each subject's time and whether its event happened.

    A subject without the event (censored) counts as at risk until its time, so subjects
    still being followed don't make the curve look faster than it is.
    """
    durations = np.asarray(durations, np.float64)
    events = np.asarray(events, np.bool_)
    n = len(durations)
    if n == 0:
        return Survival((), (), 0, 0, None)
    times, inverse = np.unique(durations, return_inverse=True)
    died = np.bincount(inverse, weights=events.astype(np.float64), minlength=len(times))
    left = np.bincount(inverse, minlength=len(times)).astype(np.float64)
    at_risk = n - np.concatenate(([0.0], np.cumsum(left)[:-1]))
    has_event = died > 0
    factors = 1 - died[has_event] / at_risk[has_event]
    curve = np.cumprod(factors)
    event_times = times[has_event]
    below = np.flatnonzero(curve <= 0.5)
    median = float(event_times[below[0]]) if len(below) else None
    return Survival(
        tuple(float(t) for t in event_times),
        tuple(float(s) for s in curve),
        n,
        int(events.sum()),
        median,
    )
