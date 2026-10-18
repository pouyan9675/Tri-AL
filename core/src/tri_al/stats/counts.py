"""Counting trials under a filter: what charts and facets are made of (docs/design.md §5.5).

``Counts`` is a small set of questions (how many trials, how many per status, the top
conditions, ...). Two backends answer them: ``SqlCounts`` asks SQLite, and ``IndexCounts``
(``tri_al.stats.index``) asks the in-memory index each API worker keeps. Charts and facets
are written once against ``Counts`` and run on either.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

from sqlalchemy import ColumnElement, Connection, Select, Table, case, func, literal, select
from sqlalchemy.sql.elements import KeyedColumnElement

from tri_al.filters import TrialFilter
from tri_al.storage import tables as t
from tri_al.storage.filtering import matching_ids, where

type CodedField = Literal["status", "phase", "study_type", "sponsor_class", "has_results"]
type LinkDimension = Literal[
    "conditions", "interventions", "sponsors", "countries", "mesh_conditions", "mesh_interventions"
]
type DateField = Literal["start_date", "completion_date", "first_posted", "last_update"]

CODED_FIELDS: tuple[CodedField, ...] = (
    "status",
    "phase",
    "study_type",
    "sponsor_class",
    "has_results",
)
LINK_DIMENSIONS: tuple[LinkDimension, ...] = (
    "conditions",
    "interventions",
    "sponsors",
    "countries",
    "mesh_conditions",  # the MeSH terms a trial's conditions map to, not their ancestors
    "mesh_interventions",
)
DATE_COLUMNS: tuple[DateField, ...] = (
    "start_date",
    "completion_date",
    "first_posted",
    "last_update",
)


@dataclass(frozen=True, slots=True)
class Count:
    """How many trials have ``value``; ``label`` is how to show it."""

    value: str | None  # what the filter field takes: a code, a name, or None for "not given"
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class Timeline:
    """One condition, intervention, ... and its trials per period (``Counts.timelines``)."""

    value: str | None  # what the filter field takes, as in ``Count``
    label: str
    trials: tuple[int, ...]  # trials in each period
    sponsors: tuple[int, ...]
    """Lead sponsors whose latest trial of it falls in each period, so ``sum(sponsors[i:])``
    is how many different lead sponsors registered one from period ``i`` on."""


@dataclass(frozen=True, slots=True)
class _Link:
    table: Table
    key: KeyedColumnElement[Any]  # the link column: an entity id, or a country code
    entity: Table
    entity_key: KeyedColumnElement[Any]
    value: KeyedColumnElement[Any]  # what a filter takes: a name or a code
    label: KeyedColumnElement[Any]
    where: tuple[ColumnElement[bool], ...] = ()  # which of the table's rows are links


def _links() -> dict[str, _Link]:
    def mesh(kind: str) -> _Link:
        tm = t.trial_mesh
        return _Link(
            tm,
            tm.c.mesh_term_id,
            t.mesh_terms,
            t.mesh_terms.c.id,
            t.mesh_terms.c.code,
            t.mesh_terms.c.term,
            (tm.c.kind == kind, tm.c.ancestor.is_(False)),
        )

    return {
        "conditions": _Link(
            t.trial_conditions,
            t.trial_conditions.c.condition_id,
            t.conditions,
            t.conditions.c.id,
            t.conditions.c.name,
            t.conditions.c.name,
        ),
        "interventions": _Link(
            t.trial_interventions,
            t.trial_interventions.c.intervention_id,
            t.interventions,
            t.interventions.c.id,
            t.interventions.c.name,
            t.interventions.c.name,
        ),
        "sponsors": _Link(
            t.trial_sponsors,
            t.trial_sponsors.c.sponsor_id,
            t.sponsors,
            t.sponsors.c.id,
            t.sponsors.c.name,
            t.sponsors.c.name,
        ),
        "countries": _Link(
            t.trial_countries,
            t.trial_countries.c.country_code,
            t.countries,
            t.countries.c.code,
            t.countries.c.code,
            t.countries.c.name,
        ),
        "mesh_conditions": mesh("condition"),
        "mesh_interventions": mesh("intervention"),
    }


LINKS = _links()

CODED_COLUMNS: Mapping[str, KeyedColumnElement[Any]] = {
    "status": t.trials.c.status,
    "phase": t.trials.c.phase,
    "study_type": t.trials.c.study_type,
    "sponsor_class": t.trials.c.lead_sponsor_class,
    "has_results": t.trials.c.has_results,
}


class Counts(Protocol):
    """Questions about the trials one filter matches."""

    def total(self) -> int: ...

    def by(self, field: CodedField) -> dict[Any, int]:
        """Trials per value of a ``trials`` column (None: no value); zero counts left out."""
        ...

    def top(self, dimension: LinkDimension, limit: int) -> list[Count]:
        """The ``limit`` conditions, interventions, sponsors or countries with most trials.

        Ties go to the entity registered first (the lower id; for countries, the code).
        """
        ...

    def intervention_types(self) -> dict[str, int]:
        """Trials per intervention type; a trial with two drugs counts once for DRUG."""
        ...

    def distinct(self, dimension: LinkDimension, *, intervention_type: str | None = None) -> int:
        """How many different conditions, interventions, ... the trials have between them."""
        ...

    def per_day(self, field: DateField, since: date, until: date) -> dict[date, int]:
        """Trials per day of ``field`` from ``since`` to ``until``; days with none left out."""
        ...

    def latest(self, field: DateField) -> date | None:
        """The latest ``field`` among the trials."""
        ...

    def timelines(
        self,
        dimension: LinkDimension,
        field: DateField,
        edges: Sequence[date],
        *,
        recent: int = 1,
        at_least: int = 1,
    ) -> list[Timeline]:
        """Trials of each condition, intervention, ... per period of ``field``.

        Period ``i`` is from ``edges[i]`` up to the day before ``edges[i + 1]``. Only those
        with at least ``at_least`` trials (and at least one) in the last ``recent`` periods
        are returned, most such trials first, ties as in ``top``.
        """
        ...

    def first_dates(
        self, dimension: LinkDimension, field: DateField, values: Sequence[str]
    ) -> dict[str, date]:
        """The earliest ``field`` among each one's trials, by the value a filter takes.

        Those with no trials, or none with a date, are left out.
        """
        ...


class SqlCounts:
    """``Counts`` answered by SQLite, inside the caller's transaction."""

    def __init__(self, conn: Connection, filter: TrialFilter) -> None:
        self._conn = conn
        self._filter = filter
        self._where = where(filter)

    def _ids(self) -> Select[tuple[int]]:
        return matching_ids(self._filter)

    def _linked(self, link: _Link) -> list[ColumnElement[bool]]:
        if self._filter.is_empty:
            return list(link.where)
        return [*link.where, link.table.c.trial_id.in_(self._ids())]

    def total(self) -> int:
        stmt = select(func.count()).select_from(t.trials).where(*self._where)
        count: int = self._conn.execute(stmt).scalar_one()
        return count

    def by(self, field: CodedField) -> dict[Any, int]:
        col = CODED_COLUMNS[field]
        stmt = select(col, func.count()).where(*self._where).group_by(col)
        return dict(self._conn.execute(stmt).all())

    def top(self, dimension: LinkDimension, limit: int) -> list[Count]:
        link = LINKS[dimension]
        n = func.count().label("n")
        counted = (
            select(link.key.label("key"), n)
            .where(*self._linked(link))
            .group_by(link.key)
            .order_by(n.desc(), link.key)
            .limit(limit)
            .subquery()
        )
        stmt = (
            select(link.value, link.label, counted.c.n)
            .join(link.entity, link.entity_key == counted.c.key)
            .order_by(counted.c.n.desc(), counted.c.key)
        )
        return [Count(value, label, n) for value, label, n in self._conn.execute(stmt)]

    def intervention_types(self) -> dict[str, int]:
        ti = t.trial_interventions
        stmt = (
            select(ti.c.type, func.count(ti.c.trial_id.distinct()))
            .where(ti.c.type.is_not(None), *self._linked(LINKS["interventions"]))
            .group_by(ti.c.type)
        )
        return dict(self._conn.execute(stmt).all())

    def distinct(self, dimension: LinkDimension, *, intervention_type: str | None = None) -> int:
        link = LINKS[dimension]
        clauses = self._linked(link)
        if intervention_type is not None:
            clauses.append(t.trial_interventions.c.type == intervention_type)
        stmt = select(func.count(link.key.distinct())).where(*clauses)
        count: int = self._conn.execute(stmt).scalar_one()
        return count

    def per_day(self, field: DateField, since: date, until: date) -> dict[date, int]:
        col = t.trials.c[field]
        stmt = (
            select(col, func.count()).where(*self._where, col >= since, col <= until).group_by(col)
        )
        return dict(self._conn.execute(stmt).all())

    def latest(self, field: DateField) -> date | None:
        col = t.trials.c[field]
        latest: date | None = self._conn.execute(
            select(func.max(col)).where(*self._where)
        ).scalar_one()
        return latest

    def timelines(
        self,
        dimension: LinkDimension,
        field: DateField,
        edges: Sequence[date],
        *,
        recent: int = 1,
        at_least: int = 1,
    ) -> list[Timeline]:
        link = LINKS[dimension]
        col = t.trials.c[field]
        periods = len(edges) - 1
        if periods < 1:
            return []
        period: ColumnElement[int] = (
            case(*((col < edge, i) for i, edge in enumerate(edges[1:-1])), else_=periods - 1)
            if periods > 1
            else literal(0)
        )
        lead = t.trials.c.lead_sponsor_id
        stmt = (
            select(link.key, lead, period, func.count())
            .select_from(t.trials)
            # "+ 0" keeps SQLite from scanning the whole link table to look up trials: the
            # trials in the date range are far fewer.
            .join(link.table, link.table.c.trial_id == t.trials.c.id + 0)
            .where(*link.where, col >= edges[0], col < edges[-1], *self._where)
            .group_by(link.key, lead, period)
        )
        trials: dict[Any, list[int]] = defaultdict(lambda: [0] * periods)
        last: dict[tuple[Any, int], int] = {}  # (entity, lead sponsor) -> its latest period
        for key, sponsor, i, count in self._conn.execute(stmt):
            trials[key][i] += count
            if sponsor is not None:
                last[key, sponsor] = max(last.get((key, sponsor), i), i)
        recent_trials = {key: sum(counts[periods - recent :]) for key, counts in trials.items()}
        chosen = sorted(
            (key for key, n in recent_trials.items() if n >= max(at_least, 1)),
            key=lambda key: (-recent_trials[key], key),
        )
        if not chosen:
            return []
        sponsors: dict[Any, list[int]] = defaultdict(lambda: [0] * periods)
        for (key, _), i in last.items():
            sponsors[key][i] += 1
        names = {
            key: (value, label)
            for key, value, label in self._conn.execute(
                select(link.entity_key, link.value, link.label).where(link.entity_key.in_(chosen))
            )
        }
        return [Timeline(*names[key], tuple(trials[key]), tuple(sponsors[key])) for key in chosen]

    def first_dates(
        self, dimension: LinkDimension, field: DateField, values: Sequence[str]
    ) -> dict[str, date]:
        if not values:
            return {}
        link = LINKS[dimension]
        col = t.trials.c[field]
        stmt = (
            select(link.value, func.min(col))
            .select_from(link.entity)
            .join(link.table, link.key == link.entity_key)
            .join(t.trials, t.trials.c.id == link.table.c.trial_id)
            .where(link.value.in_(values), *link.where, col.is_not(None), *self._where)
            .group_by(link.value)
        )
        return {value: day for value, day in self._conn.execute(stmt) if day is not None}
