"""The analysis page's Results charts: who took part, and safety.

Every chart reads the plugin's tables (``store``) for the trials the page's filter matches,
so it follows the filter. A few very large studies would outweigh everything else in
counts pooled over participants (the 10 largest hold 22% of the 12.7 million participants
whose race is reported), so shares of a whole are also given "in the average trial", where
each trial counts once; rates of adverse events are pooled over participants at risk, as
safety reports give them.
"""

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, case, func, select

from tri_al.filters import TrialFilter
from tri_al.schema import labels
from tri_al.stats import Chart, ChartContext, Layout, Rows, Series
from tri_al.stats.methods import false_discovery
from tri_al.storage import filtering
from tri_al.storage import tables as t
from tri_al_results import store
from tri_al_results.parse import (
    DROPOUTS,
    ESTIMATES,
    ETHNICITY,
    HYPOTHESES,
    ORGANS,
    RACE,
    RATIOS,
    REPORTING,
)

PEOPLE = "Who took part"
SAFETY = "Safety"
EFFICACY = "Did it work"
FLOW = "Who finished"

MIN_TRIALS = 5
"""Trials a year or a phase needs before a chart shows it."""

LARGE_TRIAL = 100
"""Participants a trial needs to count in "enrolled no one from a group"."""

SIGNAL_MIN_TRIALS = 3
SIGNAL_MIN_EVENTS = 5
SIGNALS = 15

type Query = Callable[[ChartContext, TrialFilter], Rows]

_rt = store.trials
_ORGAN_NAMES = dict(enumerate(ORGANS.values(), start=1))


def _matching(filter: TrialFilter, trial_id: Any) -> list[ColumnElement[bool]]:
    """Conditions keeping rows whose ``trial_id`` is a trial the filter matches."""
    conditions = filtering.where(filter)
    if not conditions:
        return []
    return [trial_id.in_(select(t.trials.c.id).where(*conditions))]


def _phase(code: str | None) -> str:
    return labels.label(labels.PHASE, code)


def _phases(found: Iterable[str | None]) -> list[str | None]:
    """The phases found, in the order phases come in, then unknown codes, then none."""
    present = set(found)
    ordered: list[str | None] = [code for code in labels.PHASE if code in present]
    ordered += sorted(code for code in present if code is not None and code not in labels.PHASE)
    return ordered + ([None] if None in present else [])


def _ratio(part: float | None, whole: float | None) -> float | None:
    return None if not whole or part is None else part / whole


# --- who took part -------------------------------------------------------------------------


def people(ctx: ChartContext, filter: TrialFilter) -> Rows:
    row = ctx.conn.execute(
        select(
            func.count(),
            func.sum(_rt.c.participants),
            func.sum(_rt.c.female),
            func.sum(_rt.c.male),
            func.avg(_rt.c.age),
        ).where(*_matching(filter, _rt.c.trial_id))
    ).one()
    trials, participants, female, male, age = row
    return [
        {"key": "trials", "label": "Trials with results", "value": trials},
        {"key": "participants", "label": "Participants", "value": participants or 0},
        {
            "key": "women",
            "label": "Women",
            "value": _ratio(female, (female or 0) + (male or 0)),
            "format": "percent",
        },
        {"key": "age", "label": "Mean age", "value": None if age is None else round(age, 1)},
    ]


def race_reporting(ctx: ChartContext, filter: TrialFilter) -> Rows:
    """Trials by how they reported race, per year their results were first posted."""
    year = func.strftime("%Y", t.trials.c.results_first_posted)
    found = ctx.conn.execute(
        select(year, _rt.c.race, func.count())
        .join(t.trials, t.trials.c.id == _rt.c.trial_id)
        .where(t.trials.c.results_first_posted.is_not(None), *filtering.where(filter))
        .group_by(year, _rt.c.race)
    ).all()
    years: dict[str, dict[str, Any]] = {}
    for when, kind, count in found:
        years.setdefault(when, {"year": when, **dict.fromkeys(REPORTING, 0)})[kind] = count
    return [years[when] for when in sorted(years)]


def _shares(
    ctx: ChartContext, filter: TrialFilter, kind: str, *extra: Any
) -> dict[int, tuple[dict[str, int], tuple[Any, ...]]]:
    """Each trial's participants by category of ``kind``, with ``extra`` trial columns."""
    d = store.demographics
    stmt: Select[Any] = (
        select(d.c.trial_id, d.c.category, d.c.participants, *extra)
        .join(t.trials, t.trials.c.id == d.c.trial_id)
        .where(d.c.kind == kind, *filtering.where(filter))
    )
    trials: dict[int, tuple[dict[str, int], tuple[Any, ...]]] = {}
    for trial_id, category, participants, *rest in ctx.conn.execute(stmt):
        trials.setdefault(trial_id, ({}, tuple(rest)))[0][category] = participants
    return trials


def composition(kind: str, names: Mapping[str, str]) -> Query:
    """Participants by race (or ethnicity): pooled, and in the average trial."""

    def query(ctx: ChartContext, filter: TrialFilter) -> Rows:
        pooled: dict[str, int] = defaultdict(int)
        shares: dict[str, float] = defaultdict(float)
        trials = 0
        for counts, _ in _shares(ctx, filter, kind).values():
            total = sum(counts.values())
            if not total:
                continue
            trials += 1
            for category, n in counts.items():
                pooled[category] += n
                shares[category] += n / total
        everyone = sum(pooled.values())
        if not everyone:
            return []
        return [
            {
                "key": category,
                "label": name,
                "participants": pooled[category] / everyone,
                "average": shares[category] / trials,
                "count": pooled[category],
            }
            for category, name in names.items()
            if category != "other" or pooled[category]
        ]

    return query


def race_by_year(ctx: ChartContext, filter: TrialFilter) -> Rows:
    """Black, Asian and Hispanic participants in the average trial, by year it started."""
    year = func.strftime("%Y", t.trials.c.start_date)
    sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for kind, wanted in (("race", ("black", "asian")), ("ethnicity", ("hispanic",))):
        for counts, (when,) in _shares(ctx, filter, kind, year).values():
            total = sum(counts.values())
            if not total or when is None:
                continue
            sums[when][kind] += 1
            for category in wanted:
                sums[when][category] += counts.get(category, 0) / total
    rows: Rows = []
    for when in sorted(sums):
        point = sums[when]
        if point["race"] < MIN_TRIALS:
            continue
        rows.append(
            {
                "year": when,
                "black": point["black"] / point["race"],
                "asian": point["asian"] / point["race"],
                "hispanic": (
                    point["hispanic"] / point["ethnicity"]
                    if point["ethnicity"] >= MIN_TRIALS
                    else None
                ),
                "trials": int(point["race"]),
            }
        )
    return rows


def race_by_phase(ctx: ChartContext, filter: TrialFilter) -> Rows:
    """Participants by race in the average trial of each phase."""
    groups: dict[str | None, list[dict[str, int]]] = defaultdict(list)
    for counts, (phase,) in _shares(ctx, filter, "race", t.trials.c.phase).values():
        if sum(counts.values()):
            groups[phase].append(counts)
    rows: Rows = []
    for phase in _phases(groups):
        trials = groups[phase]
        if len(trials) < MIN_TRIALS:
            continue
        row: dict[str, Any] = {"phase": _phase(phase), "trials": len(trials)}
        for category in RACE:
            row[category] = sum(c.get(category, 0) / sum(c.values()) for c in trials) / len(trials)
        rows.append(row)
    return rows


def representation(ctx: ChartContext, filter: TrialFilter) -> Rows:
    """Of larger trials reporting the standard categories, those with no one from a group."""
    rows: Rows = []
    for kind, groups in (
        ("race", ("black", "asian", "aian", "nhpi")),
        ("ethnicity", ("hispanic",)),
    ):
        names = RACE if kind == "race" else ETHNICITY
        trials = [
            counts
            for counts, _ in _shares(ctx, filter, kind).values()
            if sum(counts.values()) >= LARGE_TRIAL
        ]
        for group in groups:
            rows.append(
                {
                    "key": group,
                    "label": names[group],
                    "value": (
                        sum(1 for c in trials if not c.get(group)) / len(trials) if trials else None
                    ),
                    "trials": len(trials),
                }
            )
    return rows if any(row["trials"] for row in rows) else []


# --- safety --------------------------------------------------------------------------------


def _left_for(kind: str) -> Any:
    """Each trial's share of participants who left for ``kind`` (0 if none did)."""
    d = store.dropouts
    left = (
        select(d.c.participants)
        .where(d.c.trial_id == _rt.c.trial_id, d.c.kind == kind)
        .scalar_subquery()
    )
    return case((_rt.c.started > 0, func.min(func.coalesce(left, 0) * 1.0 / _rt.c.started, 1.0)))


def safety(ctx: ChartContext, filter: TrialFilter) -> Rows:
    trials, at_risk, serious, deaths_at_risk, deaths, left = ctx.conn.execute(
        select(
            func.count(),
            func.sum(_rt.c.at_risk),
            func.sum(_rt.c.serious),
            func.sum(_rt.c.deaths_at_risk),
            func.sum(_rt.c.deaths),
            func.avg(_left_for("adverse_event")),
        ).where(_rt.c.ae_groups > 0, *_matching(filter, _rt.c.trial_id))
    ).one()
    return [
        {"key": "trials", "label": "Trials with adverse events", "value": trials},
        {"key": "at_risk", "label": "Participants at risk", "value": at_risk or 0},
        {
            "key": "serious",
            "label": "Had a serious adverse event",
            "value": _ratio(serious, at_risk),
            "format": "percent",
        },
        {
            "key": "deaths",
            "label": "Died",
            "value": _ratio(deaths, deaths_at_risk),
            "format": "percent",
        },
        {"key": "left", "label": "Left for an adverse event", "value": left, "format": "percent"},
    ]


def serious_by_phase(ctx: ChartContext, filter: TrialFilter) -> Rows:
    found = ctx.conn.execute(
        select(
            t.trials.c.phase,
            func.count(),
            func.sum(_rt.c.at_risk),
            func.sum(_rt.c.serious),
            func.sum(_rt.c.deaths_at_risk),
            func.sum(_rt.c.deaths),
        )
        .join(t.trials, t.trials.c.id == _rt.c.trial_id)
        .where(_rt.c.ae_groups > 0, *filtering.where(filter))
        .group_by(t.trials.c.phase)
    ).all()
    by_phase = {row[0]: row[1:] for row in found}
    return [
        {
            "key": phase,
            "label": _phase(phase),
            "serious": _ratio(serious, at_risk),
            "deaths": _ratio(deaths, deaths_at_risk),
            "trials": trials,
        }
        for phase in _phases(by_phase)
        for trials, at_risk, serious, deaths_at_risk, deaths in [by_phase[phase]]
        if trials >= MIN_TRIALS
    ]


def _at_risk(ctx: ChartContext, filter: TrialFilter) -> int:
    total = ctx.conn.execute(
        select(func.sum(_rt.c.at_risk)).where(
            _rt.c.ae_groups > 0, *_matching(filter, _rt.c.trial_id)
        )
    ).scalar_one()
    return int(total or 0)


def organ_systems(ctx: ChartContext, filter: TrialFilter) -> Rows:
    e = store.events
    at_risk = _at_risk(ctx, filter)
    if not at_risk:
        return []
    found = ctx.conn.execute(
        select(e.c.organ, func.sum(e.c.affected + func.coalesce(e.c.placebo_affected, 0)))
        .where(e.c.serious.is_(True), e.c.organ.is_not(None), *_matching(filter, e.c.trial_id))
        .group_by(e.c.organ)
    ).all()
    rows = [
        {"key": organ, "label": _ORGAN_NAMES[organ], "value": affected / at_risk}
        for organ, affected in found
        if organ in _ORGAN_NAMES
    ]
    return sorted(rows, key=lambda row: -row["value"])


def top_serious(limit: int) -> Query:
    def query(ctx: ChartContext, filter: TrialFilter) -> Rows:
        e = store.events
        at_risk = _at_risk(ctx, filter)
        found = ctx.conn.execute(
            select(
                e.c.term_id,
                e.c.organ,
                func.count(),
                func.sum(e.c.affected + func.coalesce(e.c.placebo_affected, 0)),
            )
            .where(e.c.serious.is_(True), *_matching(filter, e.c.trial_id))
            .group_by(e.c.term_id, e.c.organ)
        ).all()
        # An event's organ system is the one most trials file it under.
        terms: dict[int, list[Any]] = {}  # term id: trials, participants, organ, its trials
        for term_id, organ, count, n in found:
            entry = terms.setdefault(term_id, [0, 0, None, 0])
            entry[0] += count
            entry[1] += n or 0
            if organ is not None and count > entry[3]:
                entry[2], entry[3] = organ, count
        top = sorted(terms.items(), key=lambda item: (-item[1][0], -item[1][1]))[:limit]
        names = dict(
            ctx.conn.execute(
                select(store.terms.c.id, store.terms.c.term).where(
                    store.terms.c.id.in_([term_id for term_id, _ in top])
                )
            ).all()
        )
        return [
            {
                "event": names.get(term_id, "?"),
                "organ": _ORGAN_NAMES.get(organ) if organ is not None else None,
                "trials": count,
                "participants": n,
                "rate": _ratio(n, at_risk),
            }
            for term_id, (count, n, organ, _) in top
        ]

    return query


def signals(ctx: ChartContext, filter: TrialFilter) -> Rows:
    """Adverse events more common in active arms than on placebo, pooled over trials.

    For each event, the trials that list it and have placebo and active arms give a 2x2
    table each; the Mantel-Haenszel risk ratio pools them (Greenland-Robins interval), and
    the Cochran-Mantel-Haenszel test gives a p-value, corrected for testing every event
    (Benjamini-Hochberg). Serious events must all be reported, so a trial that doesn't list
    one had none; other events are listed only above the trial's threshold, so they are
    compared only within the trials that list them. SQLite sums each event's tables in one
    pass, so only the events tested reach Python.
    """
    e = store.events
    a = func.min(e.c.affected, e.c.at_risk) * 1.0
    c = func.min(e.c.placebo_affected, e.c.placebo_at_risk) * 1.0
    n1, n0 = e.c.at_risk * 1.0, e.c.placebo_at_risk * 1.0
    n = n1 + n0
    m1 = a + c
    found = ctx.conn.execute(
        select(
            e.c.term_id,
            e.c.serious,
            func.count(),
            func.sum(a),
            func.sum(c),
            func.sum(n1),
            func.sum(n0),
            func.sum(a * n0 / n),
            func.sum(c * n1 / n),
            func.sum((n1 * n0 * m1 - a * c * n) / (n * n)),
            func.sum(a - n1 * m1 / n),
            func.sum(case((n > 1, n1 * n0 * m1 * (n - m1) / (n * n * (n - 1))), else_=0.0)),
        )
        .where(e.c.placebo_at_risk > 0, e.c.at_risk > 0, *_matching(filter, e.c.trial_id))
        .group_by(e.c.term_id, e.c.serious)
        .having(func.count() >= SIGNAL_MIN_TRIALS, func.sum(m1) >= SIGNAL_MIN_EVENTS)
    ).all()
    tested = [row for row in found if row[7] > 0 and row[8] > 0 and row[11] > 0]
    if not tested:
        return []
    ps = [math.erfc(math.sqrt(max(abs(row[10]) - 0.5, 0) ** 2 / row[11] / 2)) for row in tested]
    qs = false_discovery(ps)
    picked = sorted(
        (i for i, row in enumerate(tested) if row[7] > row[8] and qs[i] < 0.05),
        key=lambda i: (qs[i], -tested[i][7] / tested[i][8]),
    )[:SIGNALS]
    names = dict(
        ctx.conn.execute(
            select(store.terms.c.id, store.terms.c.term).where(
                store.terms.c.id.in_([tested[i][0] for i in picked])
            )
        ).all()
    )
    rows: Rows = []
    for i in picked:
        term_id, serious, count, sa, sc, sn1, sn0, r, s_, spread, _, _ = tested[i]
        ratio = r / s_
        se = math.sqrt(max(spread, 0) / (r * s_))
        rows.append(
            {
                "label": names.get(term_id, "?"),
                "detail": "Serious" if serious else "Not serious",
                "ratio": ratio,
                "low": math.exp(math.log(ratio) - 1.96 * se),
                "high": math.exp(math.log(ratio) + 1.96 * se),
                "trials": count,
                "active": sa / sn1,
                "placebo": sc / sn0,
                "q": qs[i],
            }
        )
    return rows


def dropouts(ctx: ChartContext, filter: TrialFilter) -> Rows:
    """Why participants left: each reason's share of those who started, in the average trial."""
    d = store.dropouts
    trials = ctx.conn.execute(
        select(func.count()).where(_rt.c.started > 0, *_matching(filter, _rt.c.trial_id))
    ).scalar_one()
    if not trials:
        return []
    found = ctx.conn.execute(
        select(d.c.kind, func.sum(func.min(d.c.participants * 1.0 / _rt.c.started, 1.0)))
        .join(_rt, _rt.c.trial_id == d.c.trial_id)
        .where(_rt.c.started > 0, *_matching(filter, d.c.trial_id))
        .group_by(d.c.kind)
    ).all()
    rows = [
        {"key": kind, "label": DROPOUTS.get(kind, kind), "value": share / trials}
        for kind, share in found
    ]
    return sorted(rows, key=lambda row: -row["value"])


# --- did it work ----------------------------------------------------------------------------

_an = store.analyses_table
_COMPLETION = case(
    (_rt.c.started > 0, func.min(func.coalesce(_rt.c.completed, 0) * 1.0 / _rt.c.started, 1.0))
)


def _significant(p: float, bound: str | None) -> bool:
    return p < 0.05 or (bound == "<" and p <= 0.05)


def _first(filter: TrialFilter, *conditions: Any) -> Any:
    """Each trial's first primary analysis meeting ``conditions``, in the registry's order (the
    first primary outcome is usually the one the trial was built around)."""
    rank = func.row_number().over(
        partition_by=_an.c.trial_id, order_by=(_an.c.outcome, _an.c.analysis)
    )
    return (
        select(_an, rank.label("rank"))
        .where(_an.c.kind == "PRIMARY", *conditions, *_matching(filter, _an.c.trial_id))
        .subquery()
    )


def _primary_results(ctx: ChartContext, filter: TrialFilter, *extra: Any) -> list[Any]:
    """Each trial's first primary p-value: (significant, *extra), extra from ``trials``."""
    first = _first(filter, _an.c.p.is_not(None))
    found = ctx.conn.execute(
        select(first.c.p, first.c.p_bound, *extra)
        .join(t.trials, t.trials.c.id == first.c.trial_id)
        .where(first.c.rank == 1)
    ).all()
    return [(_significant(p, bound), *rest) for p, bound, *rest in found]


def efficacy(ctx: ChartContext, filter: TrialFilter) -> Rows:
    has_estimate = and_(_an.c.estimate.is_not(None), _an.c.ci_lower.is_not(None))
    tested = _an.c.hypothesis.in_(("non_inferiority", "equivalence"))
    per_trial = (
        select(
            func.max(case((has_estimate, 1), else_=0)).label("estimated"),
            func.max(case((tested, 1), else_=0)).label("non_inferior"),
        )
        .where(_an.c.kind == "PRIMARY", *_matching(filter, _an.c.trial_id))
        .group_by(_an.c.trial_id)
        .subquery()
    )
    trials, estimated, non_inferior = ctx.conn.execute(
        select(func.count(), func.sum(per_trial.c.estimated), func.sum(per_trial.c.non_inferior))
    ).one()
    results = _primary_results(ctx, filter)
    return [
        {"key": "analysed", "label": "Trials with a primary analysis", "value": trials},
        {
            "key": "significant",
            "label": "Primary result p < 0.05",
            "value": _ratio(sum(1 for (hit,) in results if hit), len(results)),
            "format": "percent",
        },
        {
            "key": "estimate",
            "label": "Gave an effect estimate",
            "value": _ratio(estimated, trials),
            "format": "percent",
        },
        {
            "key": "non_inferiority",
            "label": "Tested non-inferiority",
            "value": _ratio(non_inferior, trials),
            "format": "percent",
        },
    ]


def _shares_by(
    found: Iterable[tuple[bool, Any]], order: list[Any], name: Callable[[Any], str]
) -> Rows:
    counts: dict[Any, list[int]] = defaultdict(lambda: [0, 0])
    for hit, key in found:
        counts[key][0] += hit
        counts[key][1] += 1
    return [
        {"key": key, "label": name(key), "value": hits / n, "trials": n}
        for key in order
        for hits, n in [counts[key]]
        if n >= MIN_TRIALS
    ]


def success_by_phase(ctx: ChartContext, filter: TrialFilter) -> Rows:
    found = [(hit, phase) for hit, phase in _primary_results(ctx, filter, t.trials.c.phase)]
    return _shares_by(found, _phases(phase for _, phase in found), _phase)


def success_by_sponsor(ctx: ChartContext, filter: TrialFilter) -> Rows:
    column = t.trials.c.lead_sponsor_class
    found = [(hit, kind) for hit, kind in _primary_results(ctx, filter, column)]
    present = {kind for _, kind in found}
    order: list[str | None] = [code for code in labels.SPONSOR_CLASS if code in present]
    order += sorted(k for k in present if k is not None and k not in labels.SPONSOR_CLASS)
    order += [None] if None in present else []
    rows = _shares_by(found, order, lambda code: labels.label(labels.SPONSOR_CLASS, code))
    return sorted(rows, key=lambda row: -row["trials"])


def success_by_year(ctx: ChartContext, filter: TrialFilter) -> Rows:
    year = func.strftime("%Y", t.trials.c.results_first_posted)
    found = [(hit, when) for hit, when in _primary_results(ctx, filter, year) if when]
    rows = _shares_by(found, sorted({when for _, when in found}), str)
    return [{"year": row["label"], "value": row["value"], "trials": row["trials"]} for row in rows]


def p_values(ctx: ChartContext, filter: TrialFilter) -> Rows:
    """Every primary p-value given exactly, in bins of 0.01 up to 0.2."""
    found = ctx.conn.execute(
        select(_an.c.p).where(
            _an.c.kind == "PRIMARY",
            _an.c.p.is_not(None),
            _an.c.p_bound.is_(None),
            *_matching(filter, _an.c.trial_id),
        )
    ).scalars()
    bins = [0] * 20
    total = 0
    for p in found:
        total += 1
        if p < 0.2:
            bins[min(19, int(p * 100 + 1e-9))] += 1
    if not total:
        return []
    return [
        {"bin": f"{i / 100:.2f} to {(i + 1) / 100:.2f}", "value": n / total, "count": n}
        for i, n in enumerate(bins)
    ]


def hypotheses(ctx: ChartContext, filter: TrialFilter) -> Rows:
    first = _first(filter, _an.c.hypothesis.is_not(None))
    found: dict[str, int] = dict(
        ctx.conn.execute(
            select(first.c.hypothesis, func.count())
            .where(first.c.rank == 1)
            .group_by(first.c.hypothesis)
        ).all()
    )
    total = sum(found.values())
    return [
        {"key": key, "label": name, "value": found.get(key, 0) / total, "trials": found.get(key, 0)}
        for key, name in HYPOTHESES.items()
        if total
    ]


def effects(limit: int) -> Query:
    """The largest trials' first primary ratio (hazard, odds or risk) with its interval."""

    def query(ctx: ChartContext, filter: TrialFilter) -> Rows:
        first = _first(
            filter,
            _an.c.estimate_type.in_(RATIOS),
            _an.c.estimate > 0,
            _an.c.ci_lower > 0,
            _an.c.ci_upper > 0,
        )
        found = ctx.conn.execute(
            select(
                t.trials.c.source_id,
                t.trials.c.title,
                first.c.estimate_type,
                first.c.estimate,
                first.c.ci_lower,
                first.c.ci_upper,
                first.c.p,
                first.c.p_bound,
                _rt.c.participants,
            )
            .join(t.trials, t.trials.c.id == first.c.trial_id)
            .join(_rt, _rt.c.trial_id == first.c.trial_id)
            .where(first.c.rank == 1)
            .order_by(func.coalesce(_rt.c.participants, 0).desc(), t.trials.c.source_id)
            .limit(limit)
        ).all()
        return [
            {
                "label": title,
                "detail": f"{source_id} · {ESTIMATES.get(kind, kind)}",
                "source_id": source_id,
                "estimate": estimate,
                "low": low,
                "high": high,
                "participants": participants,
                "p": None if p is None else f"{bound or ''}{p:g}",
            }
            for source_id, title, kind, estimate, low, high, p, bound, participants in found
        ]

    return query


# --- who finished --------------------------------------------------------------------------


def flow(ctx: ChartContext, filter: TrialFilter) -> Rows:
    started, completed, average, withdrew, lost = ctx.conn.execute(
        select(
            func.sum(_rt.c.started),
            func.sum(func.min(func.coalesce(_rt.c.completed, 0), _rt.c.started)),
            func.avg(_COMPLETION),
            func.avg(_left_for("withdrawal")),
            func.avg(_left_for("lost")),
        ).where(_rt.c.started > 0, *_matching(filter, _rt.c.trial_id))
    ).one()
    return [
        {"key": "started", "label": "Started", "value": started or 0},
        {
            "key": "completed",
            "label": "Completed",
            "value": _ratio(completed, started),
            "format": "percent",
        },
        {
            "key": "average",
            "label": "Completed, average trial",
            "value": average,
            "format": "percent",
        },
        {"key": "withdrew", "label": "Withdrew", "value": withdrew, "format": "percent"},
        {"key": "lost", "label": "Lost to follow-up", "value": lost, "format": "percent"},
    ]


def _by_phase(ctx: ChartContext, filter: TrialFilter, **columns: Any) -> Rows:
    """Averages of ``columns`` over the trials of each phase that report a participant flow."""
    found = ctx.conn.execute(
        select(t.trials.c.phase, func.count(), *(func.avg(c) for c in columns.values()))
        .join(t.trials, t.trials.c.id == _rt.c.trial_id)
        .where(_rt.c.started > 0, *filtering.where(filter))
        .group_by(t.trials.c.phase)
    ).all()
    by_phase = {row[0]: row[1:] for row in found}
    return [
        {
            "key": phase,
            "label": _phase(phase),
            **dict(zip(columns, values, strict=True)),
            "trials": n,
        }
        for phase in _phases(by_phase)
        for n, *values in [by_phase[phase]]
        if n >= MIN_TRIALS
    ]


def completion_by_phase(ctx: ChartContext, filter: TrialFilter) -> Rows:
    return _by_phase(ctx, filter, value=_COMPLETION)


def left_by_phase(ctx: ChartContext, filter: TrialFilter) -> Rows:
    return _by_phase(
        ctx,
        filter,
        adverse_event=_left_for("adverse_event"),
        lack_of_efficacy=_left_for("lack_of_efficacy"),
    )


# --- the specs -----------------------------------------------------------------------------


def charts(*, top: int = 20, effects_shown: int = 15) -> list[Chart]:
    def chart(order: int, width: int = 2, height: int = 1, **spec: Any) -> Chart:
        return Chart(page="results", layout=Layout(width=width, height=height, order=order), **spec)

    percent = "percent"
    both = (
        Series("participants", "Share of participants"),
        Series("average", "In the average trial"),
    )
    return [
        # --- who took part
        chart(
            100,
            width=4,
            id="results_people",
            title="Trials with results",
            widget="stat",
            query=people,
            section=PEOPLE,
            description=(
                "Trials whose results are posted, the participants they analysed, the share who "
                "were women, and their mean age (averaged over trials)."
            ),
        ),
        chart(
            110,
            id="results_race",
            title="Participants by race",
            widget="bar",
            query=composition("race", RACE),
            section=PEOPLE,
            format=percent,
            series=both,
            description=(
                "From trials that report the standard NIH/OMB categories. The average trial "
                "counts each trial once, so a few very large studies don't outweigh the rest."
            ),
        ),
        chart(
            120,
            id="results_ethnicity",
            title="Participants by ethnicity",
            widget="bar",
            query=composition("ethnicity", ETHNICITY),
            section=PEOPLE,
            format=percent,
            series=both,
            description="From trials that report the standard NIH/OMB categories.",
        ),
        chart(
            130,
            id="results_race_by_year",
            title="Participants over time",
            widget="line",
            query=race_by_year,
            section=PEOPLE,
            x="year",
            format=percent,
            series=(
                Series("black", "Black or African American"),
                Series("asian", "Asian"),
                Series("hispanic", "Hispanic or Latino"),
            ),
            description=(
                f"Share of participants in the average trial, by the year trials started; years "
                f"with fewer than {MIN_TRIALS} trials reporting race are left out."
            ),
        ),
        chart(
            140,
            id="results_race_by_phase",
            title="Race by phase",
            widget="stacked",
            query=race_by_phase,
            section=PEOPLE,
            x="phase",
            format=percent,
            series=tuple(Series(key, name) for key, name in RACE.items()),
            description="Participants by race in the average trial of each phase.",
        ),
        chart(
            150,
            id="results_representation",
            title="Trials that enrolled no one from a group",
            widget="bar",
            query=representation,
            section=PEOPLE,
            format=percent,
            description=(
                f"Of trials with {LARGE_TRIAL} or more participants that report the standard "
                "categories, the share with no participants from each group."
            ),
        ),
        chart(
            160,
            width=4,
            id="results_race_reporting",
            title="How trials report race",
            widget="stacked",
            query=race_reporting,
            section=PEOPLE,
            x="year",
            series=tuple(Series(key, name) for key, name in REPORTING.items()),
            description=(
                "Trials by the year their results were first posted: the standard NIH/OMB "
                "categories, categories of their own, a statement that race wasn't collected, "
                "or nothing. ClinicalTrials.gov has required race and ethnicity, when collected, "
                "since 2017."
            ),
        ),
        # --- safety
        chart(
            200,
            width=4,
            id="results_safety",
            title="Adverse events",
            widget="stat",
            query=safety,
            section=SAFETY,
            description=(
                "Trials that report adverse events, the participants at risk, the share who had "
                "a serious adverse event or died (over everyone at risk), and the share who left "
                "because of an adverse event (in the average trial)."
            ),
        ),
        chart(
            210,
            id="results_serious_by_phase",
            title="Serious adverse events and deaths by phase",
            widget="bar",
            query=serious_by_phase,
            section=SAFETY,
            format=percent,
            series=(Series("serious", "Serious adverse event"), Series("deaths", "Died")),
            description="Share of participants at risk, pooled over the trials of each phase.",
        ),
        chart(
            220,
            height=2,
            id="results_organ_systems",
            title="Serious adverse events by organ system",
            widget="bar",
            query=organ_systems,
            section=SAFETY,
            format=percent,
            description=(
                "Participants with a serious event in each MedDRA organ system, per participant "
                "at risk; someone with two events in a system counts twice."
            ),
        ),
        chart(
            230,
            width=4,
            height=2,
            id="results_signals",
            title="Adverse events more common than on placebo",
            widget="forest",
            query=signals,
            section=SAFETY,
            y="ratio",
            series=(
                Series("trials", "Trials"),
                Series("active", "Active arms", "percent"),
                Series("placebo", "Placebo", "percent"),
            ),
            description=(
                "Risk ratios pooled over placebo-controlled trials (Mantel-Haenszel, 95% "
                f"interval), for events listed by at least {SIGNAL_MIN_TRIALS} trials; shown "
                "when the difference holds after correcting for every event tested (q < 0.05)."
            ),
        ),
        chart(
            240,
            width=4,
            height=2,
            id="results_top_serious",
            title="Most reported serious adverse events",
            widget="table",
            query=top_serious(top),
            section=SAFETY,
            x="event",
            series=(
                Series("trials", "Trials"),
                Series("participants", "Participants"),
                Series("rate", "Share of participants", "percent"),
            ),
            description=(
                "By the number of trials that report each event; the share is over everyone at "
                "risk in the trials shown."
            ),
        ),
        # --- did it work
        chart(
            300,
            width=4,
            id="results_efficacy",
            title="Primary outcomes",
            widget="stat",
            query=efficacy,
            section=EFFICACY,
            description=(
                "Trials with a statistical analysis of a primary outcome; of those with a "
                "p-value, the share whose first one is under 0.05; and the shares that gave an "
                "effect estimate with an interval or tested non-inferiority or equivalence."
            ),
        ),
        chart(
            310,
            id="results_success_by_phase",
            title="Primary result p < 0.05, by phase",
            widget="bar",
            query=success_by_phase,
            section=EFFICACY,
            format=percent,
            description=(
                "Each trial's first primary p-value, in the registry's order; a p-value says "
                "the result is unlikely by chance, not that the treatment helps."
            ),
        ),
        chart(
            320,
            id="results_success_by_sponsor",
            title="Primary result p < 0.05, by sponsor",
            widget="bar",
            query=success_by_sponsor,
            section=EFFICACY,
            format=percent,
            description="By the lead sponsor's kind, largest first.",
        ),
        chart(
            330,
            id="results_success_by_year",
            title="Primary result p < 0.05, over time",
            widget="line",
            query=success_by_year,
            section=EFFICACY,
            x="year",
            format=percent,
            description="By the year results were first posted.",
        ),
        chart(
            340,
            id="results_p_values",
            title="Primary p-values",
            widget="area",
            query=p_values,
            section=EFFICACY,
            x="bin",
            format=percent,
            description=(
                "Share of all exact primary p-values in each band of 0.01, up to 0.2; a pile "
                "just under 0.05 against just over it would hint at selective reporting."
            ),
        ),
        chart(
            350,
            id="results_hypotheses",
            title="What primary analyses tested",
            widget="bar",
            query=hypotheses,
            section=EFFICACY,
            format=percent,
            description="Each trial's first primary analysis that names its hypothesis.",
        ),
        chart(
            360,
            width=4,
            height=2,
            id="results_effects",
            title="Effect estimates in the largest trials",
            widget="forest",
            query=effects(effects_shown),
            section=EFFICACY,
            y="estimate",
            series=(Series("participants", "Participants"), Series("p", "p-value")),
            description=(
                "The first primary hazard, odds or risk ratio of the largest trials, with its "
                "95% interval, as each trial reports it: which arm is the reference varies."
            ),
        ),
        # --- who finished
        chart(
            400,
            width=4,
            id="results_flow",
            title="Participant flow",
            widget="stat",
            query=flow,
            section=FLOW,
            description=(
                "Participants who started, the share who completed (pooled, and in the average "
                "trial), and the shares who withdrew or were lost to follow-up (average trial)."
            ),
        ),
        chart(
            410,
            id="results_completion_by_phase",
            title="Completion by phase",
            widget="bar",
            query=completion_by_phase,
            section=FLOW,
            format=percent,
            description="Share of those who started who completed, in the average trial.",
        ),
        chart(
            420,
            id="results_left_by_phase",
            title="Left for safety or for lack of effect, by phase",
            widget="bar",
            query=left_by_phase,
            section=FLOW,
            format=percent,
            series=(
                Series("adverse_event", "Adverse event"),
                Series("lack_of_efficacy", "Lack of efficacy"),
            ),
            description="Share of those who started, in the average trial.",
        ),
        chart(
            430,
            height=2,
            id="results_dropouts",
            title="Why participants left",
            widget="bar",
            query=dropouts,
            section=FLOW,
            format=percent,
            description=(
                "Each reason's share of the participants who started, in the average trial."
            ),
        ),
    ]


__all__ = [
    "EFFICACY",
    "FLOW",
    "PEOPLE",
    "SAFETY",
    "charts",
    "completion_by_phase",
    "composition",
    "dropouts",
    "effects",
    "efficacy",
    "flow",
    "hypotheses",
    "left_by_phase",
    "organ_systems",
    "p_values",
    "people",
    "race_by_phase",
    "race_by_year",
    "race_reporting",
    "representation",
    "safety",
    "serious_by_phase",
    "signals",
    "success_by_phase",
    "success_by_sponsor",
    "success_by_year",
    "top_serious",
]
