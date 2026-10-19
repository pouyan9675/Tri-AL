"""Trial linking (design §9): the trials that share a trial's MeSH terms, by phase.

ClinicalTrials.gov tags each trial with MeSH terms for its conditions and interventions
(``trial_mesh``); they're the normalized names, where the registry's own are free text. A
trial is linked to another when it's tagged with at least one of the chosen condition terms
and at least one of the chosen intervention terms. Only terms a trial is tagged with
count, not their ancestors, and a kind with no terms chosen asks nothing. Linked trials
come in phases, in ``labels.PHASE`` order with trials without a phase last, each listed by
how many chosen terms it shares, then newest start first.
"""

from collections import Counter, defaultdict
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select, tuple_

from tri_al.filters import TrialFilter
from tri_al.schema import labels
from tri_al.storage import SQLiteReader, TrialSummary
from tri_al.storage import tables as t
from tri_al.storage.filtering import where

PHASES: tuple[str | None, ...] = (*labels.PHASE, None)


@dataclass(frozen=True, slots=True)
class LinkTerm:
    """One of the trial's own MeSH terms."""

    code: str
    term: str
    kind: str  # condition or intervention
    selected: bool
    trials: int  # linked trials that share it


@dataclass(frozen=True, slots=True)
class LinkedTrial:
    trial: TrialSummary
    shared: tuple[str, ...]  # the codes of the chosen terms it shares


@dataclass(frozen=True, slots=True)
class PhaseGroup:
    phase: str | None
    total: int
    trials: list[LinkedTrial]  # the first ``limit``


@dataclass(frozen=True, slots=True)
class Links:
    terms: list[LinkTerm]
    total: int = 0
    phases: list[PhaseGroup] = field(default_factory=list)


@dataclass(slots=True)
class _Match:
    phase: str | None
    start: date | None
    kinds: set[str] = field(default_factory=set)
    codes: list[str] = field(default_factory=list)


def linked_trials(
    reader: SQLiteReader,
    trial_id: int,
    *,
    terms: Collection[str] | None = None,
    filter: TrialFilter | None = None,
    limit: int = 100,
) -> Links:
    """The trials linked to ``trial_id`` by its terms in ``terms`` (codes; None: all of them).

    ``filter`` narrows the linked trials; each phase lists at most ``limit``.
    """
    tm, mt, tr = t.trial_mesh.c, t.mesh_terms.c, t.trials.c
    conn = reader.connection
    own = conn.execute(
        select(tm.mesh_term_id, tm.kind, mt.code, mt.term)
        .join_from(t.trial_mesh, t.mesh_terms)
        .where(tm.trial_id == trial_id, tm.ancestor.is_(False))
        .order_by(tm.kind, mt.term)
    ).all()
    chosen = [row for row in own if terms is None or row.code in terms]
    if not chosen:
        return Links([LinkTerm(r.code, r.term, r.kind, False, 0) for r in own])

    rows = conn.execute(
        select(tm.trial_id, tm.kind, mt.code, tr.phase, tr.start_date)
        .join_from(t.trial_mesh, t.mesh_terms)
        .join(t.trials, tr.id == tm.trial_id)
        .where(
            tuple_(tm.mesh_term_id, tm.kind).in_([(r.mesh_term_id, r.kind) for r in chosen]),
            tm.ancestor.is_(False),
            tm.trial_id != trial_id,
            *where(filter or TrialFilter()),
        )
    )
    matches: dict[int, _Match] = {}
    for row in rows:
        match = matches.setdefault(row.trial_id, _Match(row.phase, row.start_date))
        match.kinds.add(row.kind)
        match.codes.append(row.code)
    kinds = {row.kind for row in chosen}
    linked = {key: match for key, match in matches.items() if match.kinds >= kinds}

    by_phase: defaultdict[str | None, list[int]] = defaultdict(list)
    for key, match in linked.items():
        by_phase[match.phase].append(key)
    order = {phase: i for i, phase in enumerate(PHASES)}
    groups: list[tuple[str | None, int, list[int]]] = []
    for phase in sorted(by_phase, key=lambda p: order.get(p, len(PHASES))):
        keys = sorted(by_phase[phase], key=lambda key: _rank(key, linked[key]))
        groups.append((phase, len(keys), keys[:limit]))

    shown = [key for _, _, keys in groups for key in keys]
    summaries = {summary.id: summary for summary in reader.summaries(shown)}
    rank = {row.code: i for i, row in enumerate(chosen)}
    per_term = Counter(code for match in linked.values() for code in match.codes)
    return Links(
        terms=[
            LinkTerm(
                r.code, r.term, r.kind, r.code in rank, per_term[r.code] if r.code in rank else 0
            )
            for r in own
        ],
        total=len(linked),
        phases=[
            PhaseGroup(
                phase,
                total,
                [
                    LinkedTrial(
                        summaries[key],
                        tuple(sorted(set(linked[key].codes), key=rank.__getitem__)),
                    )
                    for key in keys
                    if key in summaries
                ],
            )
            for phase, total, keys in groups
        ],
    )


def _rank(key: int, match: _Match) -> tuple[int, bool, int, int]:
    """More shared terms first, then the newest start (none last), then the newest id."""
    start = -match.start.toordinal() if match.start is not None else 0
    return (-len(match.codes), match.start is None, start, -key)
