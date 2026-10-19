"""Running an advanced search: the matching trials in order, then a page of them described.

The page's filter, the participant and design fields and a place are masks over the trial
index; the text fields become one FTS5 query on ``trials_fts`` (each field restricted to its
columns), read as a mask too. Fields narrower than a column (inclusion and exclusion criteria,
primary and secondary outcomes) are then checked in the text of at most
``SECTION_CANDIDATES`` candidates, the newest (``tri_al.advanced.sections``).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np
import numpy.typing as npt
from sqlalchemy import Connection

from tri_al.advanced.places import NearestSite, Sites, nearest_sites
from tri_al.advanced.query import SECTION_FIELDS, AdvancedQuery, TextField, column_filter
from tri_al.advanced.sections import Snippet, TextTable, text_row
from tri_al.schema import age_in_days
from tri_al.stats import TrialIndex
from tri_al.stats.index import NULL_NUMBER, Mask
from tri_al.storage import SEARCH_CANDIDATES, Sort, SQLiteReader, TrialSummary

SECTION_CANDIDATES = 2_000
"""Candidates whose text is checked for inclusion, exclusion, primary or secondary at most:
the newest. Reading and checking a trial's text takes about 150 µs."""

SNIPPET_COLUMNS: dict[TextField, tuple[str, ...]] = {
    "text": (),
    "intervention": ("interventions", "other_names"),
    "summary": ("summary", "description"),
    "eligibility": ("eligibility",),
    "inclusion": ("inclusion",),
    "exclusion": ("exclusion",),
    "outcome": ("outcomes",),
    "primary_outcome": ("primary_outcomes",),
    "secondary_outcome": ("secondary_outcomes",),
}
"""The text table's columns a field's snippet comes from. Titles and conditions have none:
a hit shows them already."""

type Order = Literal["relevance", "distance"] | Sort

type Cached = Callable[[tuple[object, ...], Callable[[], Mask]], Mask]

_MATCH = "SELECT rowid FROM trials_fts WHERE trials_fts MATCH ?"


@dataclass(frozen=True, slots=True)
class SectionCheck:
    candidates: int  # trials matching everything else, whose text was to be checked
    checked: int  # the newest of them, whose text was checked


@dataclass(frozen=True, slots=True)
class Found:
    """An advanced search's matches, in order, as of one data version."""

    ids: npt.NDArray[np.int32]
    scores: npt.NDArray[np.float32]  # relevance of the first ``len(scores)`` (higher is better)
    km: npt.NDArray[np.float32] | None  # each match's nearest site in range, with a place
    sections: SectionCheck | None

    @property
    def nbytes(self) -> int:
        return self.ids.nbytes + self.scores.nbytes + (0 if self.km is None else self.km.nbytes)

    @property
    def ranked(self) -> int:
        return len(self.scores)


@dataclass(frozen=True, slots=True)
class Hit:
    trial: TrialSummary
    score: float | None
    snippets: tuple[Snippet, ...]
    nearest: NearestSite | None


def default_order(query: AdvancedQuery) -> Order:
    """By relevance when words must match, by distance with a place, else as the trial list."""
    if query.index_expressions()[0] is not None:
        return "relevance"
    if query.near is not None:
        return "distance"
    return Sort()


def find(
    reader: SQLiteReader,
    index: TrialIndex,
    within: Mask,
    query: AdvancedQuery,
    order: Order,
    *,
    sites: Sites | None = None,
    table: TextTable,
    cached: Cached | None = None,
) -> Found:
    """The trials in ``within`` that ``query`` finds, in ``order``.

    ``sites`` is needed with a place; ``cached(key, make)`` may keep full-text masks.
    """
    conn = reader.connection

    def keep(key: tuple[object, ...], make: Callable[[], Mask]) -> Mask:
        return make() if cached is None else cached(key, make)

    mask = within & participant_mask(index, query)
    positive, negative = query.index_expressions()
    if positive is not None:
        expression = positive if negative is None else f"({positive}) NOT ({negative})"
        mask &= keep(("fts", expression), lambda: index.select_mask(conn, _MATCH, (expression,)))
    elif negative is not None:
        mask &= ~keep(("fts", negative), lambda: index.select_mask(conn, _MATCH, (negative,)))
    km = None
    if query.near is not None:
        if sites is None:
            raise ValueError("a search near a place needs the sites")
        found = sites.within(query.near)
        inside = found.trials < index.size
        km = np.full(index.size, np.inf, np.float32)
        km[found.trials[inside]] = found.km[inside]
        mask &= np.isfinite(km)
    sections = None
    if query.sections:
        candidates = np.flatnonzero(mask)[::-1]
        checked = candidates[:SECTION_CANDIDATES]
        mask = np.zeros(index.size, np.bool_)
        mask[check_sections(reader, table, query, [int(i) for i in checked])] = True
        sections = SectionCheck(len(candidates), len(checked))
    ids, scores = _ordered(conn, index, mask, order, positive, km)
    return Found(ids, scores, None if km is None else km[ids], sections)


def participant_mask(index: TrialIndex, query: AdvancedQuery) -> Mask:
    """The trials whose eligibility and design fit the query's participant and design fields."""
    mask = index.present.copy()
    if query.ages is not None:
        low, high = query.ages.low, query.ages.high
        if high is not None:  # someone aged ``high`` is up to a day short of ``high + 1``
            minimum = index.numbers("min_age_days")
            mask &= (minimum == NULL_NUMBER) | (minimum < age_in_days(high + 1, "years"))
        if low is not None:
            maximum = index.numbers("max_age_days")
            mask &= (maximum == NULL_NUMBER) | (maximum >= age_in_days(low, "years"))
    if query.sex is not None:
        sex = index.coded("sex")
        allowed = [code for value in ("ALL", query.sex) if (code := sex.code_of(value)) is not None]
        mask &= np.isin(sex.values, [*allowed, -1])  # -1: not stated
    if query.healthy_volunteers is not None:
        mask &= _coded(index, "healthy_volunteers", (query.healthy_volunteers,))
    for name in ("allocation", "masking", "intervention_model", "primary_purpose"):
        if values := getattr(query, name):
            mask &= _coded(index, name, values)
    if query.placebo is not None:
        mask &= index.placebo if query.placebo else ~index.placebo
    return mask


def _coded(index: TrialIndex, name: str, values: tuple[object, ...]) -> Mask:
    column = index.coded(name)
    return np.isin(column.values, [c for v in values if (c := column.code_of(v)) is not None])


def check_sections(
    reader: SQLiteReader, table: TextTable, query: AdvancedQuery, trial_ids: list[int]
) -> list[int]:
    """The trials among ``trial_ids`` whose text has each section field's words in its part."""
    if not trial_ids:
        return []
    columns = {SECTION_FIELDS[name] for name, _ in query.sections}
    rows = {
        trial_id: {column: row[column] for column in columns}
        for trial_id, text in reader.texts(trial_ids).items()
        if (row := text_row(text))
    }
    conn = table.load(rows)
    found = set(rows)
    for name, words in query.sections:
        column = (SECTION_FIELDS[name],)
        if (expression := words.expression()) is not None:
            found &= table.matching(conn, column_filter(column, expression))
        elif (negative := words.negative()) is not None:
            found -= table.matching(conn, column_filter(column, negative))
    return sorted(found)


def _ordered(
    conn: Connection,
    index: TrialIndex,
    mask: Mask,
    order: Order,
    positive: str | None,
    km: npt.NDArray[np.float32] | None,
) -> tuple[npt.NDArray[np.int32], npt.NDArray[np.float32]]:
    no_scores = np.empty(0, np.float32)
    if order == "relevance" and positive is not None:
        ids = np.flatnonzero(mask).astype(np.int32)
        newest = ids[::-1][:SEARCH_CANDIDATES]
        rows = conn.exec_driver_sql(
            # ``+rowid``: offered to FTS5 as a constraint, the ids would each run the query.
            "SELECT rowid, rank FROM trials_fts WHERE trials_fts MATCH ? "
            "AND +rowid IN (SELECT value FROM json_each(?)) ORDER BY rank, rowid DESC",
            (positive, json.dumps(newest.tolist())),
        ).all()
        ranked = np.fromiter((row[0] for row in rows), np.int32, len(rows))
        scores = np.fromiter((-row[1] for row in rows), np.float32, len(rows))
        rest = newest[~np.isin(newest, ranked)]
        older = ids[::-1][SEARCH_CANDIDATES:]
        return np.concatenate([ranked, rest, older]), scores
    if order == "distance" and km is not None:
        ids = np.flatnonzero(mask).astype(np.int32)
        return ids[np.lexsort((-ids.astype(np.int64), km[ids]))], no_scores
    sort = order if isinstance(order, Sort) else Sort()
    return index.ordered(mask, sort), no_scores


def describe(
    reader: SQLiteReader,
    found: Found,
    query: AdvancedQuery,
    table: TextTable,
    *,
    offset: int,
    limit: int,
) -> list[Hit]:
    """Hits for a page of ``found``: each trial's row, its snippets and nearest site."""
    ids = [int(i) for i in found.ids[offset : offset + limit]]
    if not ids:
        return []
    summaries = {summary.id: summary for summary in reader.summaries(ids)}
    snippets: dict[int, list[Snippet]] = {trial_id: [] for trial_id in ids}
    fields = [
        (name, expression)
        for name, words in query.text
        if name in SNIPPET_COLUMNS and (expression := words.positive()) is not None
    ]
    if fields:
        texts, names = reader.texts(ids), reader.names(ids)
        conn = table.load({i: text_row(text, names.get(i)) for i, text in texts.items()})
        for name, expression in fields:
            matched = table.snippets(conn, column_filter(SNIPPET_COLUMNS[name], expression))
            for trial_id, parts in matched.items():
                snippets[trial_id].append(Snippet(name, parts))
    nearest = {} if query.near is None else nearest_sites(reader.connection, query.near, ids)
    return [
        Hit(
            summaries[trial_id],
            float(found.scores[position]) if position < found.ranked else None,
            tuple(snippets[trial_id]),
            nearest.get(trial_id),
        )
        for position, trial_id in enumerate(ids, start=offset)
        if trial_id in summaries
    ]
