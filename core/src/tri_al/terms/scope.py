"""The trials a term analysis is about, and finding terms (see ``tri_al.terms``)."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import numpy.typing as npt
from sqlalchemy import Connection, func, select

from tri_al.schema import MeshKind
from tri_al.stats import LinkDimension, TrialIndex
from tri_al.stats.index import NULL_DAY, Mask, from_day_number
from tri_al.storage import SQLiteReader
from tri_al.storage import tables as t

DIMENSION: dict[MeshKind, LinkDimension] = {
    "condition": "mesh_conditions",
    "intervention": "mesh_interventions",
}
"""The index's links of each kind of term: the terms trials are tagged with, not ancestors."""

OTHER_KIND: dict[MeshKind, MeshKind] = {"condition": "intervention", "intervention": "condition"}

PHASE_GROUPS: tuple[tuple[str, str], ...] = (
    ("phase1", "Phase 1"),
    ("phase2", "Phase 2"),
    ("phase3", "Phase 3"),
    ("phase4", "Phase 4"),
    ("other", "Other"),
)
"""Phases as analyses group them: a combined phase goes with the later one (Phase 1/2 is
Phase 2), early phase 1 with phase 1, and "Other" is not applicable or no phase."""

_PHASE_GROUP = {
    "EARLY_PHASE1": 0,
    "PHASE1": 0,
    "PHASE1_PHASE2": 1,
    "PHASE2": 1,
    "PHASE2_PHASE3": 2,
    "PHASE3": 2,
    "PHASE4": 3,
}
OTHER_PHASE = len(PHASE_GROUPS) - 1

ACTIVE = ("RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION", "ACTIVE_NOT_RECRUITING")
"""Statuses of a trial that is running or about to."""

STOPPED = ("TERMINATED", "WITHDRAWN", "SUSPENDED")
"""Statuses of a trial that stopped early (or, suspended, may resume)."""


@dataclass(frozen=True, slots=True)
class TermRef:
    """A MeSH term as a kind of term: the same code can be a condition and an intervention."""

    code: str
    term: str
    kind: MeshKind


@dataclass(frozen=True, slots=True)
class TermCount:
    code: str
    term: str
    trials: int


@dataclass(frozen=True, slots=True)
class Scope:
    """The trials one analysis is about.

    ``trials`` are the term's within the filter; ``within`` all the filter's, which the term's
    are compared with. A term's trials are those tagged with it or with a narrower term, as
    with the ``mesh`` filter. ``as_of`` is the data's today: the latest update of any trial,
    so an analysis gives the same answer for one data version whenever it's asked.
    """

    ref: TermRef
    term_id: int
    index: TrialIndex
    reader: SQLiteReader
    within: Mask
    trials: Mask
    everywhere: Mask  # the term's trials without the filter
    as_of: date

    @property
    def conn(self) -> Connection:
        return self.reader.connection

    @property
    def others(self) -> Mask:
        """The filter's trials without the term's: the baseline comparisons use."""
        result: Mask = self.within & ~self.trials
        return result

    @property
    def count(self) -> int:
        return int(np.count_nonzero(self.trials))

    def coded(self, name: str, values: Sequence[object]) -> Mask:
        """Trials whose ``name`` column has one of ``values``."""
        column = self.index.coded(name)
        codes = [i for i, code in enumerate(column.codes) if code in values]
        result: Mask = np.isin(column.values, codes)
        return result

    def phase_groups(self) -> npt.NDArray[np.int8]:
        """Each trial's place in ``PHASE_GROUPS``."""
        column = self.index.coded("phase")
        lookup = np.array(
            [_PHASE_GROUP.get(code, OTHER_PHASE) for code in column.codes] + [OTHER_PHASE],
            np.int8,
        )
        result: npt.NDArray[np.int8] = lookup[column.values]
        return result


def term_names(conn: Connection, keys: Sequence[int]) -> dict[int, tuple[str, str]]:
    """The code and name of each term id."""
    mt = t.mesh_terms.c
    rows = conn.execute(select(mt.id, mt.code, mt.term).where(mt.id.in_(list(keys))))
    return {key: (code, term) for key, code, term in rows}


def find_term(conn: Connection, kind: MeshKind, code: str) -> tuple[int, TermRef] | None:
    """The term with ``code`` if some trial is tagged with it as a ``kind`` (or narrower)."""
    mt, tm = t.mesh_terms.c, t.trial_mesh.c
    row = conn.execute(select(mt.id, mt.code, mt.term).where(mt.code == code)).one_or_none()
    if row is None:
        return None
    used = conn.execute(
        select(tm.trial_id).where(tm.mesh_term_id == row.id, tm.kind == kind).limit(1)
    ).first()
    return None if used is None else (row.id, TermRef(row.code, row.term, kind))


def term_mask(index: TrialIndex, conn: Connection, term_id: int, kind: MeshKind) -> Mask:
    """Trials tagged with the term as a ``kind``, or with a narrower term."""
    return index.select_mask(
        conn,
        "SELECT trial_id FROM trial_mesh WHERE mesh_term_id = ? AND kind = ?",
        (term_id, kind),
    )


NARROWER_INSIDE = 0.95
"""Share of a term's trials that must also have the broader term, for it to be narrower."""

NARROWER_ANCESTOR = 0.5
"""... and share where the broader term was added as an ancestor (not tagged itself)."""


def narrower_terms(scope: Scope) -> dict[int, TermCount]:
    """Terms of the scope's kind narrower than its term, by id, with their trials in scope.

    The registry adds a term's ancestors to each trial, so a term is narrower when nearly
    all its trials have the broader one, mostly as an ancestor. Mostly, since a trial may
    also be tagged with the broader term itself; requiring the ancestor keeps out terms that
    only ever appear beside it (a rare condition studied only with Alzheimer's). A trial has
    one row per term and kind, so the trials with the term only as an ancestor are its
    trials less those tagged with it, and this needs no query.
    """
    link = scope.index.link(DIMENSION[scope.ref.kind])
    tagged = np.zeros(scope.index.size, np.bool_)
    tagged[link.trial[link.value == scope.term_id]] = True
    ancestor = scope.everywhere & ~tagged
    total = np.bincount(link.value, minlength=link.size)
    inside = np.bincount(link.value[scope.everywhere[link.trial]], minlength=link.size)
    through = np.bincount(link.value[ancestor[link.trial]], minlength=link.size)
    found = np.flatnonzero(
        (total > 0) & (inside >= NARROWER_INSIDE * total) & (through >= NARROWER_ANCESTOR * total)
    )
    found = found[found != scope.term_id]
    if len(found) == 0:
        return {}
    here = np.bincount(link.value[scope.trials[link.trial]], minlength=link.size)
    names = term_names(scope.conn, [int(key) for key in found])
    return {key: TermCount(code, term, int(here[key])) for key, (code, term) in names.items()}


def scope_for(
    reader: SQLiteReader,
    index: TrialIndex,
    kind: MeshKind,
    code: str,
    within: Mask | None = None,
) -> Scope | None:
    """The scope of the term ``code`` within ``within`` (every trial if None); None if no
    trial is tagged with it as a ``kind``. The API caches the parts; this is for scripts."""
    found = find_term(reader.connection, kind, code)
    if found is None:
        return None
    term_id, ref = found
    everywhere = term_mask(index, reader.connection, term_id, kind)
    within = index.present if within is None else within
    return Scope(ref, term_id, index, reader, within, within & everywhere, everywhere, as_of(index))


def as_of(index: TrialIndex) -> date:
    days = index.dates("last_update")[index.present]
    days = days[days != NULL_DAY]
    return from_day_number(int(days.max())) if len(days) else date.today()


# --- finding terms ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TermTotals:
    """How many trials each term of one kind has, for ranking terms as they're looked up."""

    direct: dict[int, int]  # by mesh_terms.id: trials tagged with it
    total: dict[int, int]  # ... or with a narrower term

    @classmethod
    def read(cls, conn: Connection, index: TrialIndex, kind: MeshKind) -> "TermTotals":
        """Direct counts from the index; totals from the link table's covering index (about
        half a second at 607k trials, so callers cache them per data version)."""
        link = index.link(DIMENSION[kind])
        direct = np.bincount(link.value, minlength=link.size)
        tm = t.trial_mesh.c
        total: dict[int, int] = dict(
            conn.execute(
                select(tm.mesh_term_id, func.count())
                .where(tm.kind == kind)
                .group_by(tm.mesh_term_id)
            ).all()
        )
        return cls({int(key): int(direct[key]) for key in np.flatnonzero(direct)}, total)


_CODE = re.compile(r"^[CD]\d{6,9}$", re.IGNORECASE)


def lookup_terms(
    conn: Connection, totals: TermTotals, q: str | None, limit: int
) -> list[TermCount]:
    """Terms whose name contains ``q`` (or whose code is ``q``), best match first.

    An exact name comes first, then names that start with ``q``, then names with a word that
    does, then the rest, each by trials (counting narrower terms). With no ``q``, the terms
    trials are most often tagged with.
    """
    mt = t.mesh_terms.c
    if not q or not q.strip():
        top = sorted(totals.direct, key=lambda key: (-totals.direct[key], key))[:limit]
        rows = conn.execute(select(mt.id, mt.code, mt.term).where(mt.id.in_(top))).all()
        found = [TermCount(r.code, r.term, totals.total[r.id]) for r in rows]
        return sorted(found, key=lambda term: (-term.trials, term.term))
    text = q.strip()
    if _CODE.match(text):
        stmt = select(mt.id, mt.code, mt.term).where(mt.code == text.upper())
    else:
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = select(mt.id, mt.code, mt.term).where(mt.term.like(f"%{escaped}%", escape="\\"))
    needle = text.lower()

    def rank(row: tuple[int, str, str]) -> tuple[int, int, str]:
        term = row[2].lower()
        place = (
            0
            if term == needle
            else 1
            if term.startswith(needle)
            else 2
            if any(word.startswith(needle) for word in re.split(r"[\s,\-/()]+", term))
            else 3
        )
        return (place, -totals.total[row[0]], term)

    matches: list[tuple[int, str, str]] = [
        (row.id, row.code, row.term) for row in conn.execute(stmt) if row.id in totals.total
    ]
    best = sorted(matches, key=rank)[:limit]
    return [TermCount(code, term, totals.total[key]) for key, code, term in best]
