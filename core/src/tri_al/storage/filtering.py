"""``TrialFilter`` as SQL: conditions on the ``trials`` table (docs/design.md §5.5).

Fields on ``trials`` itself become comparisons; fields on link tables become
``trials.id IN (SELECT trial_id ...)``, which SQLite can either drive from (for a rare
condition) or test against. Charts and plugins build their queries on ``where``.
"""

import re

from sqlalchemy import ColumnElement, Integer, Select, column, select, text
from sqlalchemy.sql.selectable import TextualSelect

from tri_al.filters import TrialFilter
from tri_al.storage import tables as t

_WORD = re.compile(r"\w+")


def match_expression(words: str, *, any_word: bool = False) -> str | None:
    """An FTS5 query for plain ``words``: all of them (or any), each quoted as plain text.

    Quoting makes FTS5 syntax (AND, NOT, *, column:) plain text. None if there are no words.
    """
    found = _WORD.findall(words)
    if not found:
        return None
    return (" OR " if any_word else " ").join(f'"{word}"' for word in found)


def full_text_ids(match: str, *, name: str = "fts_q") -> TextualSelect:
    """The rowids of the trials an FTS5 ``match`` expression finds."""
    return (
        text(f"SELECT rowid FROM trials_fts WHERE trials_fts MATCH :{name}")
        .bindparams(**{name: match})
        .columns(column("rowid", Integer))
    )


def where(filter: TrialFilter) -> list[ColumnElement[bool]]:
    """Conditions on ``trials`` that the trials ``filter`` matches meet; [] for every trial."""
    c = t.trials.c
    clauses: list[ColumnElement[bool]] = []
    for name, col in (
        ("status", c.status),
        ("phase", c.phase),
        ("study_type", c.study_type),
        ("sponsor_class", c.lead_sponsor_class),
    ):
        values = getattr(filter, name)
        if values:
            clauses.append(col.in_(values))
    for name, col in (
        ("start", c.start_date),
        ("completion", c.completion_date),
        ("first_posted", c.first_posted),
        ("last_update", c.last_update),
    ):
        dates = getattr(filter, name)
        if dates is not None:
            if dates.since is not None:
                clauses.append(col >= dates.since)
            if dates.until is not None:
                clauses.append(col <= dates.until)
    if filter.enrollment is not None:
        if filter.enrollment.low is not None:
            clauses.append(c.enrollment >= filter.enrollment.low)
        if filter.enrollment.high is not None:
            clauses.append(c.enrollment <= filter.enrollment.high)
    if filter.has_results is not None:
        clauses.append(c.has_results == filter.has_results)

    linked: list[Select[tuple[int]]] = []
    if filter.conditions:
        linked.append(
            select(t.trial_conditions.c.trial_id)
            .join(t.conditions)
            .where(t.conditions.c.name.in_(filter.conditions))
        )
    if filter.mesh:
        linked.append(
            select(t.trial_mesh.c.trial_id)
            .join(t.mesh_terms)
            .where(t.mesh_terms.c.code.in_(filter.mesh))
        )
    if filter.interventions:
        linked.append(
            select(t.trial_interventions.c.trial_id)
            .join(t.interventions)
            .where(t.interventions.c.name.in_(filter.interventions))
        )
    if filter.intervention_types:
        linked.append(
            select(t.trial_interventions.c.trial_id).where(
                t.trial_interventions.c.type.in_(filter.intervention_types)
            )
        )
    if filter.sponsors:
        linked.append(
            select(t.trial_sponsors.c.trial_id)
            .join(t.sponsors)
            .where(t.sponsors.c.name.in_(filter.sponsors))
        )
    if filter.countries:
        linked.append(
            select(t.trial_countries.c.trial_id).where(
                t.trial_countries.c.country_code.in_(filter.countries)
            )
        )
    clauses += (c.id.in_(subquery) for subquery in linked)
    if filter.q is not None:
        match = match_expression(filter.q)
        if match is not None:
            clauses.append(c.id.in_(full_text_ids(match)))
    clauses += (filter_field.clause(values) for filter_field, values in filter.extra)
    return clauses


def matching_ids(filter: TrialFilter) -> Select[tuple[int]]:
    """``SELECT id FROM trials WHERE ...`` for ``filter``."""
    return select(t.trials.c.id).where(*where(filter))
