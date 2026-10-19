"""How a term's trials go: why they stop, how long they take, and how they're designed.

Each compares the term's trials with the filter's other trials, phase by phase, since
phases differ so much (a phase 1 trial is short and small, a phase 3 trial long and large)
that a term with more early trials would otherwise look faster and smaller for that alone.
"""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt

from tri_al.schema import age_in_days
from tri_al.stats.index import NULL_DAY, NULL_NUMBER, Mask, day_number
from tri_al.stats.methods import (
    Confidence,
    Survival,
    confidence,
    false_discovery,
    kaplan_meier,
    standardized_difference,
    two_sided_p,
    weighted_quantile,
)
from tri_al.terms.scope import PHASE_GROUPS, STOPPED, Scope

MONTH = 365.25 / 12
"""Days in a month, for durations."""

YEAR = 365.25

# --- why trials stop ----------------------------------------------------------------------

READ_LIMIT = 2_000
"""Stopped trials whose reasons are read at most (the most recently updated)."""

EXAMPLES = 3

REASONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("covid", "COVID-19", ("covid", "pandemic", "coronavirus", "sars-cov")),
    (
        "safety",
        "Safety",
        ("safety", "adverse", "toxicit", "side effect", "death", "harm", "risk", "interaction"),
    ),
    (
        "efficacy",
        "Efficacy or futility",
        (
            "futil",
            "efficacy",
            "effective",
            "benefit",
            "lack of effect",
            "interim analys",
            "did not meet",
            "not met",
            "endpoint",
            "stopping rule",
            "discouraging",
            "did not show",
        ),
    ),
    (
        "decision",
        "Sponsor or administrative decision",
        (
            "business",
            "decision",
            "decided",
            "company",
            "corporate",
            "commercial",
            "portfolio",
            "priorit",
            "strateg",
            "acqui",
            "leadership",
            "sponsor",
            "administrativ",
            "competing",
            "replaced",
            "outdated",
            "development program",
            "development plan",
            "no longer consistent",
            "interest",
        ),
    ),
    (
        "funding",
        "Funding or resources",
        ("fund", "budget", "financ", "grant", "money", "cost", "resource", "support"),
    ),
    (
        "enrollment",
        "Enrollment",
        (
            "enrol",
            "accru",
            "recruit",
            "participa",
            "subjects",
            "patient",
            "inclusion",
            "include",
            "eligible",
            "consent",
        ),
    ),
    (
        "feasibility",
        "Feasibility, staff or supply",
        (
            "feasib",
            "not possible",
            "difficult",
            "investigator",
            "pi ",
            "p.i.",
            "personnel",
            "manpower",
            "staff",
            "no longer at",
            "no longer work",
            "left",
            "logist",
            "supply",
            "manufactur",
            "availab",
            "relocat",
            "site",
            "technical",
            "electronic",
            "data collection",
            "expired",
        ),
    ),
    (
        "oversight",
        "Regulatory or oversight",
        ("fda", "regulat", "irb", "ethic", "approval", "clinical hold", "dsmb", "dsmc", "monitor"),
    ),
)
"""Kinds of reason, in the order they're tried: a reason is the first kind it mentions."""

OTHER_REASON = ("other", "Other")

# "No safety concerns", "not because of any concern with the safety or effectiveness": a
# sponsor saying what it wasn't. ("No apparent benefit" is a reason, so benefit isn't here.)
_NOT_SAFETY = re.compile(
    r"\b(?:no|not|non|without|unrelated to)\b[^.;]{0,40}?"
    r"\b(?:safety|adverse|toxicit\w*|side effects?|harm|efficacy|effectiveness)\b[^.;]*",
    re.IGNORECASE,
)


def reason_kind(reason: str) -> tuple[str, str]:
    """The kind of a stated reason for stopping: its key and label."""
    text = _NOT_SAFETY.sub(" ", reason).lower()
    for key, label, words in REASONS:
        if any(word in text for word in words):
            return key, label
    return OTHER_REASON


@dataclass(frozen=True, slots=True)
class StopRate:
    group: str  # a phase group
    closed: int  # the term's trials that finished: completed or stopped
    stopped: int  # terminated, withdrawn or suspended
    rate: float | None  # stopped / closed
    baseline_closed: int
    baseline_rate: float | None
    ratio: float | None  # rate / baseline_rate
    p: float  # two-sided exact binomial test against the baseline rate
    q: float  # corrected for the phases tested
    confidence: Confidence


@dataclass(frozen=True, slots=True)
class ReasonExample:
    source_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class StopReason:
    key: str
    label: str
    trials: int
    examples: list[ReasonExample]


@dataclass(frozen=True, slots=True)
class Attrition:
    phases: list[StopRate]
    observed: int  # the term's stopped trials among its closed ones
    expected: float  # ... at the baseline's rate, phase by phase
    ratio: float | None  # observed / expected: over 1, more stop than the phases explain
    p: float
    confidence: Confidence
    stopped: int  # every stopped trial of the term's, closed or not
    read: int  # those whose reasons were read
    stated: int  # ... that give one
    reasons: list[StopReason]  # most trials first


def attrition(scope: Scope) -> Attrition:
    stopped = scope.coded("status", STOPPED)
    closed = stopped | scope.coded("status", ("COMPLETED",))
    groups = scope.phase_groups()
    rows: list[tuple[str, int, int, int, int]] = []
    for g, (key, _) in enumerate(PHASE_GROUPS):
        here = groups == g
        term, base = scope.trials & here & closed, scope.others & here & closed
        rows.append(
            (
                key,
                _count(term),
                _count(term & stopped),
                _count(base),
                _count(base & stopped),
            )
        )
    ps = [
        two_sided_p(n_stopped, n_closed, b_stopped / b_closed) if n_closed and b_closed else 1.0
        for _, n_closed, n_stopped, b_closed, b_stopped in rows
    ]
    qs = false_discovery(ps)
    phases: list[StopRate] = []
    observed, expected, total = 0, 0.0, 0
    for (key, n_closed, n_stopped, b_closed, b_stopped), p, q in zip(rows, ps, qs, strict=True):
        rate = n_stopped / n_closed if n_closed else None
        base_rate = b_stopped / b_closed if b_closed else None
        if n_closed and base_rate is not None:
            observed += n_stopped
            expected += n_closed * base_rate
            total += n_closed
        phases.append(
            StopRate(
                group=key,
                closed=n_closed,
                stopped=n_stopped,
                rate=_round(rate),
                baseline_closed=b_closed,
                baseline_rate=_round(base_rate),
                ratio=_round(rate / base_rate) if rate is not None and base_rate else None,
                p=float(f"{p:.2g}"),
                q=float(f"{q:.2g}"),
                confidence=confidence(q),
            )
        )
    p = two_sided_p(observed, total, expected / total) if total and expected else 1.0
    reasons, read, stated = _reasons(scope, scope.trials & stopped)
    return Attrition(
        phases=phases,
        observed=observed,
        expected=round(expected, 1),
        ratio=_round(observed / expected) if expected else None,
        p=float(f"{p:.2g}"),
        confidence=confidence(p),
        stopped=_count(scope.trials & stopped),
        read=read,
        stated=stated,
        reasons=reasons,
    )


def _reasons(scope: Scope, stopped: Mask) -> tuple[list[StopReason], int, int]:
    ids = np.flatnonzero(stopped)
    updated = scope.index.dates("last_update")[ids]
    ids = ids[np.lexsort((-ids, -updated.astype(np.int64)))][:READ_LIMIT]
    texts = scope.reader.texts([int(i) for i in ids])
    source_ids = {
        summary.id: summary.source_id for summary in scope.reader.summaries([int(i) for i in ids])
    }
    found: dict[str, tuple[str, int, list[ReasonExample]]] = {}
    stated = 0
    for trial_id in (int(i) for i in ids):
        text = texts.get(trial_id)
        reason = (text.why_stopped or "").strip() if text is not None else ""
        if not reason:
            continue
        stated += 1
        key, label = reason_kind(reason)
        _, n, examples = found.get(key, (label, 0, []))
        if len(examples) < EXAMPLES:
            examples.append(ReasonExample(source_ids.get(trial_id, ""), reason[:300]))
        found[key] = (label, n + 1, examples)
    reasons = [StopReason(key, label, n, examples) for key, (label, n, examples) in found.items()]
    reasons.sort(key=lambda reason: (-reason.trials, reason.key))
    return reasons, len(ids), stated


# --- how long trials take -----------------------------------------------------------------

CURVE_POINTS = 80
"""Points a survival curve keeps for drawing."""

RESULTS_AT = (12, 24, 36)
"""Months after primary completion at which the share with results is given."""


@dataclass(frozen=True, slots=True)
class Curve:
    group: str  # a phase group, or "all"
    trials: int
    events: int
    median: float | None  # months
    months: list[float]
    values: list[float]  # still running (durations) or with results (results)


@dataclass(frozen=True, slots=True)
class ResultsShare:
    months: int
    share: float | None
    baseline: float | None


@dataclass(frozen=True, slots=True)
class Durations:
    completion: list[Curve]  # the term's, by phase group, then all
    completion_baseline: list[Curve]
    results: Curve
    results_baseline: Curve
    results_at: list[ResultsShare]


def durations(scope: Scope) -> Durations:
    """How long trials run, and how long results take, as Kaplan-Meier curves.

    **Running:** from the actual start to the primary completion date of a completed trial.
    Trials still running count until today and unknown ones until their last update
    (censored), so ongoing trials don't make the curve look faster than it is. Trials that
    stopped early are left out (see ``attrition``). **Results:** for interventional trials
    that finished (completed or terminated), from primary completion to results first
    posted, those without results counting until today.
    """
    groups = scope.phase_groups()
    keys = [key for key, _ in PHASE_GROUPS]

    def by_group(mask: Mask) -> list[Curve]:
        time, event, keep = _running(scope, mask)
        curves = [
            _curve(key, kaplan_meier(time[keep & (groups == g)], event[keep & (groups == g)]))
            for g, key in enumerate(keys)
        ]
        return [*curves, _curve("all", kaplan_meier(time[keep], event[keep]))]

    term_results = _results(scope, scope.trials)
    base_results = _results(scope, scope.others)
    return Durations(
        completion=by_group(scope.trials),
        completion_baseline=by_group(scope.others),
        results=_curve("all", term_results, reported=True),
        results_baseline=_curve("all", base_results, reported=True),
        results_at=[
            ResultsShare(
                months,
                _share_by(term_results, months),
                _share_by(base_results, months),
            )
            for months in RESULTS_AT
        ],
    )


def _running(scope: Scope, mask: Mask) -> tuple[npt.NDArray[np.float64], Mask, Mask]:
    """Each trial's months from start to primary completion (or censoring), whether it
    completed, and which trials count."""
    index = scope.index
    today = day_number(scope.as_of)
    start = index.dates("start_date").astype(np.int64)
    end = index.dates("primary_completion_date").astype(np.int64)
    end = np.where(end == NULL_DAY, index.dates("completion_date"), end)
    estimated = scope.coded("start_date_type", ("ESTIMATED",))
    started = mask & (start != NULL_DAY) & (start <= today) & ~estimated
    completed = scope.coded("status", ("COMPLETED",))
    event = started & completed & (end != NULL_DAY) & (end <= today)
    unknown = scope.coded("status", ("UNKNOWN",))
    censor = np.where(unknown, index.dates("last_update"), today)
    days = np.where(event, end - start, censor - start)
    keep = started & ~scope.coded("status", STOPPED) & ~(completed & ~event) & (days >= 0)
    return days / MONTH, event, keep


def _results(scope: Scope, mask: Mask) -> Survival:
    index = scope.index
    today = day_number(scope.as_of)
    done = index.dates("primary_completion_date").astype(np.int64)
    posted = index.dates("results_first_posted").astype(np.int64)
    finished = (
        mask
        & scope.coded("study_type", ("INTERVENTIONAL",))
        & scope.coded("status", ("COMPLETED", "TERMINATED"))
        & ~scope.coded("primary_completion_date_type", ("ESTIMATED",))
        & (done != NULL_DAY)
        & (done <= today)
    )
    event = finished & (posted != NULL_DAY)
    days = np.where(event, np.maximum(posted - done, 0), today - done)
    return kaplan_meier(days[finished] / MONTH, event[finished])


def _curve(group: str, survival: Survival, *, reported: bool = False) -> Curve:
    """A curve for drawing, at most ``CURVE_POINTS`` points; ``reported`` flips it to the
    share that had the event."""
    times = np.asarray(survival.times)
    values = np.asarray(survival.survival)
    if len(times) > CURVE_POINTS:
        keep = np.unique(np.linspace(0, len(times) - 1, CURVE_POINTS).round().astype(int))
        times, values = times[keep], values[keep]
    if reported:
        values = 1 - values
    median = survival.median
    return Curve(
        group=group,
        trials=survival.at_risk,
        events=survival.events,
        median=None if median is None else round(median, 1),
        months=[round(float(t), 2) for t in times],
        values=[round(float(v), 4) for v in values],
    )


def _share_by(survival: Survival, months: float) -> float | None:
    """The share with the event by ``months``, if anyone was followed that long."""
    if not survival.at_risk or not survival.times:
        return None
    return round(1 - survival.at(months), 4)


# --- design and population ----------------------------------------------------------------

type Unit = Literal["share", "years", "participants", "sites"]


@dataclass(frozen=True, slots=True)
class Benchmark:
    key: str
    label: str
    section: str
    unit: Unit
    value: float | None  # a share, or a median
    baseline: float | None  # the same for the filter's other trials, with the term's phases
    difference: float | None  # standardized: 0.2 is small, 0.5 medium and 0.8 large
    trials: int  # the term's trials it's measured on


@dataclass(frozen=True, slots=True)
class EnrollmentBin:
    low: int
    high: int | None  # None: no upper end
    share: float  # of the term's trials with an enrollment
    baseline: float


@dataclass(frozen=True, slots=True)
class Profile:
    trials: int
    baseline_trials: int
    rows: list[Benchmark]
    enrollment: list[EnrollmentBin]


ENROLLMENT_BINS: tuple[tuple[int, int | None], ...] = (
    (1, 10),
    (11, 50),
    (51, 100),
    (101, 500),
    (501, 1_000),
    (1_001, 5_000),
    (5_001, None),
)


def profile(scope: Scope) -> Profile:
    """How the term's trials are designed and whom they enroll, against the filter's others.

    The baseline is standardized to the term's phases: each other trial is weighted so the
    baseline has the term's mix of phase groups, so a term with more phase 3 trials isn't
    "larger" for that alone. Shares compare with a standardized difference of proportions,
    numbers (enrollment and sites on a log scale) with Cohen's d.
    """
    index = scope.index
    groups = scope.phase_groups()
    interventional = scope.coded("study_type", ("INTERVENTIONAL",))
    allocation = index.coded("allocation").values >= 0
    masking = index.coded("masking").values >= 0
    min_age = index.numbers("min_age_days")
    max_age = index.numbers("max_age_days")
    enrollment = index.numbers("enrollment")
    sites = index.numbers("num_sites")
    countries = np.bincount(index.link("countries").trial, minlength=index.size)[: index.size]
    everyone = index.present

    def share(key: str, label: str, section: str, has: Mask, where: Mask = everyone) -> Benchmark:
        term, weights = _standardized(scope, groups, where)
        value = float(has[term].mean()) if term.any() else None
        baseline = _weighted_mean(has.astype(np.float64), weights)
        difference = (
            standardized_difference(value, baseline, share=True)
            if value is not None and baseline is not None
            else None
        )
        return Benchmark(
            key,
            label,
            section,
            "share",
            _round(value),
            _round(baseline),
            _round(difference, 3),
            _count(term),
        )

    def number(
        key: str,
        label: str,
        section: str,
        unit: Unit,
        values: npt.NDArray[np.float64],
        where: Mask,
        transform: Callable[[npt.NDArray[np.float64]], npt.NDArray[np.float64]] = lambda v: v,
    ) -> Benchmark:
        term, weights = _standardized(scope, groups, where)
        if not term.any():
            return Benchmark(key, label, section, unit, None, None, None, 0)
        value = float(np.median(values[term]))
        baseline = weighted_quantile(values, weights, 0.5)
        shown = transform(values[term])
        base = transform(np.where(weights > 0, values, 0.0))
        base_mean = _weighted_mean(base, weights)
        difference = None
        if base_mean is not None:
            base_var = _weighted_mean((base - base_mean) ** 2, weights) or 0.0
            sd = math.sqrt((float(shown.var()) + base_var) / 2)
            difference = standardized_difference(float(shown.mean()), base_mean, sd=sd)
        return Benchmark(
            key,
            label,
            section,
            unit,
            _round(value, 2),
            _round(baseline, 2),
            _round(difference, 3),
            _count(term),
        )

    masked = scope.coded("masking", ("DOUBLE", "TRIPLE", "QUADRUPLE"))
    has_min = min_age != NULL_NUMBER
    years = np.where(has_min, min_age, 0) / YEAR
    rows = [
        share(
            "randomized",
            "Randomized",
            "Design",
            scope.coded("allocation", ("RANDOMIZED",)),
            interventional & allocation,
        ),
        share("blinded", "Double-blind or more", "Design", masked, interventional & masking),
        share("placebo", "Placebo-controlled", "Design", index.placebo, interventional),
        share(
            "healthy_volunteers",
            "Accepts healthy volunteers",
            "Population",
            scope.coded("healthy_volunteers", (True,)),
            index.coded("healthy_volunteers").values >= 0,
        ),
        share(
            "women_only",
            "Women only",
            "Population",
            scope.coded("sex", ("FEMALE",)),
            index.coded("sex").values >= 0,
        ),
        number("min_age", "Minimum age", "Population", "years", years, has_min),
        share(
            "children",
            "Accepts under-18s",
            "Population",
            ~has_min | (min_age < age_in_days(18, "years")),
        ),
        share("no_upper_age", "No upper age limit", "Population", max_age == NULL_NUMBER),
        number(
            "enrollment",
            "Enrollment",
            "Scale",
            "participants",
            enrollment.astype(np.float64),
            enrollment > 0,
            np.log1p,
        ),
        number("sites", "Sites", "Scale", "sites", sites.astype(np.float64), sites > 0, np.log1p),
        share("multinational", "Multinational", "Scale", countries >= 2, countries >= 1),
        share(
            "industry",
            "Industry-sponsored",
            "Sponsors",
            scope.coded("sponsor_class", ("INDUSTRY",)),
            index.coded("sponsor_class").values >= 0,
        ),
        share(
            "results",
            "Results posted (completed, interventional)",
            "Sponsors",
            scope.coded("has_results", (True,)),
            interventional & scope.coded("status", ("COMPLETED",)),
        ),
    ]
    term, weights = _standardized(scope, groups, enrollment > 0)
    total = float(weights.sum())
    bins = []
    for low, high in ENROLLMENT_BINS:
        inside = enrollment >= low
        if high is not None:
            inside &= enrollment <= high
        bins.append(
            EnrollmentBin(
                low,
                high,
                round(float(inside[term].mean()), 4) if term.any() else 0.0,
                round(float(weights[inside].sum()) / total, 4) if total else 0.0,
            )
        )
    return Profile(scope.count, _count(scope.others), rows, bins)


def _standardized(
    scope: Scope, groups: npt.NDArray[np.int8], where: Mask
) -> tuple[Mask, npt.NDArray[np.float64]]:
    """The term's trials in ``where``, and weights over every trial that make the filter's
    other trials in ``where`` have the term's mix of phase groups (zero elsewhere)."""
    term = scope.trials & where
    others = scope.others & where
    size = len(PHASE_GROUPS)
    term_groups = np.bincount(groups[term], minlength=size).astype(np.float64)
    other_groups = np.bincount(groups[others], minlength=size).astype(np.float64)
    matched = (term_groups > 0) & (other_groups > 0)
    per_trial = np.zeros(size)
    if matched.any():
        target = term_groups * matched / term_groups[matched].sum()
        per_trial[matched] = target[matched] / other_groups[matched]
    weights = np.where(others, per_trial[groups], 0.0)
    return term, weights


def _weighted_mean(
    values: npt.NDArray[np.float64], weights: npt.NDArray[np.float64]
) -> float | None:
    total = float(weights.sum())
    return None if total <= 0 else float((values * weights).sum() / total)


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None or math.isnan(value) else round(value, digits)


def _count(mask: Mask) -> int:
    return int(np.count_nonzero(mask))
