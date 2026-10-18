"""Counting trials under a filter: what charts and facets are made of (docs/design.md §5.5).

``Counts`` is a small set of questions (how many trials, how many per status, the top
conditions, ...). Two backends answer them: ``SqlCounts`` asks SQLite, and ``IndexCounts``
(``tri_al.stats.index``) asks the in-memory index each API worker keeps. Charts and facets
are written once against ``Counts`` and run on either.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Protocol

from sqlalchemy import ColumnElement, Connection, Select, Table, func, select
from sqlalchemy.sql.elements import KeyedColumnElement

from tri_al.filters import TrialFilter
from tri_al.storage import tables as t
from tri_al.storage.filtering import matching_ids, where

type CodedField = Literal["status", "phase", "study_type", "sponsor_class", "has_results"]
type LinkDimension = Literal["conditions", "interventions", "sponsors", "countries"]
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
class _Link:
    table: Table
    key: KeyedColumnElement[Any]  # the link column: an entity id, or a country code
    entity: Table
    entity_key: KeyedColumnElement[Any]


def _links() -> dict[str, _Link]:
    return {
        "conditions": _Link(
            t.trial_conditions,
            t.trial_conditions.c.condition_id,
            t.conditions,
            t.conditions.c.id,
        ),
        "interventions": _Link(
            t.trial_interventions,
            t.trial_interventions.c.intervention_id,
            t.interventions,
            t.interventions.c.id,
        ),
        "sponsors": _Link(
            t.trial_sponsors,
            t.trial_sponsors.c.sponsor_id,
            t.sponsors,
            t.sponsors.c.id,
        ),
        "countries": _Link(
            t.trial_countries,
            t.trial_countries.c.country_code,
            t.countries,
            t.countries.c.code,
        ),
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


class SqlCounts:
    """``Counts`` answered by SQLite, inside the caller's transaction."""

    def __init__(self, conn: Connection, filter: TrialFilter) -> None:
        self._conn = conn
        self._filter = filter
        self._where = where(filter)

    def _ids(self) -> Select[tuple[int]]:
        return matching_ids(self._filter)

    def _linked(self, table: Table) -> list[ColumnElement[bool]]:
        if self._filter.is_empty:
            return []
        return [table.c.trial_id.in_(self._ids())]

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
            .where(*self._linked(link.table))
            .group_by(link.key)
            .order_by(n.desc(), link.key)
            .limit(limit)
            .subquery()
        )
        stmt = (
            select(counted.c.key, link.entity.c.name, counted.c.n)
            .join(link.entity, link.entity_key == counted.c.key)
            .order_by(counted.c.n.desc(), counted.c.key)
        )
        rows = self._conn.execute(stmt).all()
        if dimension == "countries":
            return [Count(key, name, n) for key, name, n in rows]
        return [Count(name, name, n) for _, name, n in rows]

    def intervention_types(self) -> dict[str, int]:
        ti = t.trial_interventions
        stmt = (
            select(ti.c.type, func.count(ti.c.trial_id.distinct()))
            .where(ti.c.type.is_not(None), *self._linked(ti))
            .group_by(ti.c.type)
        )
        return dict(self._conn.execute(stmt).all())

    def distinct(self, dimension: LinkDimension, *, intervention_type: str | None = None) -> int:
        link = LINKS[dimension]
        clauses = self._linked(link.table)
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
