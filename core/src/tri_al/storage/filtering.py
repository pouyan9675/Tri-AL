"""``TrialFilter`` as SQL: conditions on the ``trials`` table (docs/design.md §5.5).

Fields on ``trials`` itself become comparisons; fields on link tables become
``trials.id IN (SELECT trial_id ...)``, which SQLite can either drive from (for a rare
condition) or test against. Charts and plugins build their queries on ``where``.
"""

import json
import re

from sqlalchemy import ColumnElement, Integer, Select, column, select, text
from sqlalchemy.sql.selectable import TextualSelect

from tri_al.filters import TrialFilter
from tri_al.storage import tables as t

_WORD = re.compile(r"\w+")
_TERM = re.compile(r"[^\s,;]+")
_TERM_EDGES = "\"'`()[]{}<>.:#"
_LETTER = re.compile(r"[^\W\d_]")
_DIGIT = re.compile(r"\d")

MAX_ID = 64
"""The longest term that may be a trial ID."""
MIN_ID_PREFIX = 7
"""The shortest start of a trial ID that search completes, such as ``NCT0443``."""


def match_expression(words: str, *, any_word: bool = False) -> str | None:
    """An FTS5 query for plain ``words``: all of them (or any), each quoted as plain text.

    Quoting makes FTS5 syntax (AND, NOT, *, column:) plain text. None if there are no words.
    """
    found = _WORD.findall(words)
    if not found:
        return None
    return (" OR " if any_word else " ").join(f'"{word}"' for word in found)


def trial_id_terms(words: str) -> list[str]:
    """The terms in ``words`` that may be trial IDs, each as typed and in capitals.

    A term is what's between spaces, commas and semicolons, without quotes, brackets or a
    full stop around it, and it must hold a letter and a digit: ``NCT04437511``,
    ``nct04437511,`` or ``CTRI/2020/05/025013``. So a pasted list of IDs finds every one.
    """
    found: dict[str, None] = {}
    for term in _TERM.findall(words):
        term = term.strip(_TERM_EDGES)
        if len(term) <= MAX_ID and _LETTER.search(term) and _DIGIT.search(term):
            found[term] = None
            found[term.upper()] = None
    return list(found)


def trial_id_prefixes(words: str) -> list[str]:
    """``trial_id_terms`` of ``words`` if it's one term that may start a trial ID, else []."""
    if len(_TERM.findall(words)) != 1:
        return []
    terms = trial_id_terms(words)
    return terms if terms and terms[0].isascii() and len(terms[0]) >= MIN_ID_PREFIX else []


def text_query(q: str) -> tuple[str, dict[str, str]] | None:
    """SQL for the ids of the trials ``TrialFilter.q`` finds, and its parameters.

    They are the trials whose text has every word, and the trials called by one of its
    ``trial_id_terms``. None if ``q`` has no words.
    """
    match = match_expression(q)
    if match is None:
        return None
    sql = "SELECT rowid FROM trials_fts WHERE trials_fts MATCH :fts_q"
    params = {"fts_q": match}
    if ids := trial_id_terms(q):
        sql += (
            " UNION SELECT id FROM trials WHERE source_id IN "
            "(SELECT value FROM json_each(:fts_ids))"
        )
        params["fts_ids"] = json.dumps(ids)
    return sql, params


def text_query_ids(q: str) -> TextualSelect | None:
    """``text_query`` as a select of ``rowid``."""
    query = text_query(q)
    if query is None:
        return None
    sql, params = query
    return text(sql).bindparams(**params).columns(column("rowid", Integer))


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
        found = text_query_ids(filter.q)
        if found is not None:
            clauses.append(c.id.in_(found))
    clauses += (filter_field.clause(values) for filter_field, values in filter.extra)
    return clauses


def matching_ids(filter: TrialFilter) -> Select[tuple[int]]:
    """``SELECT id FROM trials WHERE ...`` for ``filter``."""
    return select(t.trials.c.id).where(*where(filter))
