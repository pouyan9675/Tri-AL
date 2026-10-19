"""What a term goes with: related terms by lift, their network, and the pipeline by phase."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import numpy.typing as npt

from tri_al.schema import MeshKind, labels
from tri_al.stats.index import NULL_DAY, Mask, from_day_number
from tri_al.stats.methods import Confidence, confidence, excess_p, false_discovery, smoothed_ratio
from tri_al.terms.scope import ACTIVE, DIMENSION, OTHER_KIND, STOPPED, Scope, term_names

MIN_SHARED = 3
"""Trials a term must share with the scope's term to be tested as related."""

PRIOR = 10.0
"""Trials added to smooth lift: small counts move toward no difference."""

TOP = 15
"""Related terms listed per kind."""

NETWORK_EACH = 10
"""Related terms of each kind in the network."""

MAX_EDGES = 60

MIN_EDGE_TRIALS = 2

_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True, slots=True)
class RelatedTerm:
    code: str
    term: str
    kind: MeshKind
    trials: int  # the scope's trials tagged with it
    share: float  # ... as a share of the scope's
    elsewhere: float  # share of the filter's other trials tagged with it
    lift: float  # how many times more common with the term than without it, smoothed
    p: float  # one-sided exact binomial test that it's more common with the term
    q: float  # p corrected for every term tested (Benjamini-Hochberg)
    confidence: Confidence


@dataclass(frozen=True, slots=True)
class NetworkNode:
    code: str
    term: str
    kind: MeshKind
    trials: int  # the scope's trials tagged with it (all of them for the center)
    lift: float | None  # None for the center
    group: int  # its community; the center is -1
    center: bool


@dataclass(frozen=True, slots=True)
class NetworkEdge:
    source: int  # node indexes
    target: int
    trials: int  # the scope's trials tagged with both
    jaccard: float  # trials with both over trials with either


@dataclass(frozen=True, slots=True)
class Related:
    trials: int  # the scope's
    others: int  # the filter's other trials, the baseline
    tested: int  # terms tested
    conditions: list[RelatedTerm]
    interventions: list[RelatedTerm]
    nodes: list[NetworkNode]
    edges: list[NetworkEdge]


@dataclass(slots=True)
class _Tested:
    kind: MeshKind
    key: int
    inside: int
    outside: int
    lift: float
    p: float
    q: float = 1.0


def related(scope: Scope, narrower: Sequence[int]) -> Related:
    """Terms tagged on the scope's trials more often than on the filter's other trials.

    Lift compares the two shares, smoothed with ``PRIOR`` trials as emerging trends are, so
    rare terms don't top the list on a few trials. Confidence is an exact binomial test (if a
    term had nothing to do with this one, each of its trials would be one of the scope's at
    the usual rate), corrected for the hundreds of terms tested at once. The term itself and
    its narrower terms are left out: they'd be related by definition.
    """
    n, others = scope.count, scope.others
    m = int(np.count_nonzero(others))
    if n == 0 or m == 0:
        return Related(n, m, 0, [], [], [], [])
    usual = n / (n + m)
    left_out = {scope.term_id, *narrower}
    tested: list[_Tested] = []
    for kind in ("condition", "intervention"):
        link = scope.index.link(DIMENSION[kind])
        inside = np.bincount(link.value[scope.trials[link.trial]], minlength=link.size)
        outside = np.bincount(link.value[others[link.trial]], minlength=link.size)
        for key in np.flatnonzero(inside >= MIN_SHARED):
            if kind == scope.ref.kind and int(key) in left_out:
                continue
            a, c = int(inside[key]), int(outside[key])
            tested.append(
                _Tested(
                    kind,
                    int(key),
                    a,
                    c,
                    smoothed_ratio(a, c, n, m, PRIOR),
                    excess_p(a, a + c, usual),
                )
            )
    for entry, q in zip(tested, false_discovery([e.p for e in tested]), strict=True):
        entry.q = q
    ranked = sorted(
        (entry for entry in tested if entry.lift > 1),
        key=lambda e: (_ORDER[confidence(e.q)], -e.lift, -e.inside, e.key),
    )
    by_kind = {
        kind: [entry for entry in ranked if entry.kind == kind][:TOP]
        for kind in ("condition", "intervention")
    }
    names = term_names(scope.conn, [e.key for entries in by_kind.values() for e in entries])

    def out(entry: _Tested) -> RelatedTerm:
        code, term = names[entry.key]
        return RelatedTerm(
            code=code,
            term=term,
            kind=entry.kind,
            trials=entry.inside,
            share=round(entry.inside / n, 5),
            elsewhere=round(entry.outside / m, 6),
            lift=round(entry.lift, 2),
            p=float(f"{entry.p:.2g}"),
            q=float(f"{entry.q:.2g}"),
            confidence=confidence(entry.q),
        )

    conditions = [out(entry) for entry in by_kind["condition"]]
    interventions = [out(entry) for entry in by_kind["intervention"]]
    nodes, edges = _network(
        scope,
        [*by_kind["condition"][:NETWORK_EACH], *by_kind["intervention"][:NETWORK_EACH]],
        names,
    )
    return Related(n, m, len(tested), conditions, interventions, nodes, edges)


def _network(
    scope: Scope, chosen: Sequence[_Tested], names: dict[int, tuple[str, str]]
) -> tuple[list[NetworkNode], list[NetworkEdge]]:
    """The term, its most related terms, and how often those go together in its trials."""
    center = NetworkNode(
        scope.ref.code, scope.ref.term, scope.ref.kind, scope.count, None, -1, True
    )
    if not chosen:
        return [center], []
    rows: list[npt.NDArray[np.int32]] = []
    columns: list[npt.NDArray[np.int64]] = []
    for i, entry in enumerate(chosen):
        link = scope.index.link(DIMENSION[entry.kind])
        trials = link.trial[(link.value == entry.key) & scope.trials[link.trial]]
        rows.append(trials)
        columns.append(np.full(len(trials), i, np.int64))
    trial_ids, place = np.unique(np.concatenate(rows), return_inverse=True)
    matrix = np.zeros((len(trial_ids), len(chosen)), np.int32)
    matrix[place, np.concatenate(columns)] = 1
    together = matrix.T @ matrix
    sizes = np.diag(together)
    candidates: list[tuple[float, int, int, int]] = []
    for i in range(len(chosen)):
        for j in range(i + 1, len(chosen)):
            both = int(together[i, j])
            if both >= MIN_EDGE_TRIALS:
                jaccard = both / int(sizes[i] + sizes[j] - both)
                candidates.append((jaccard, i, j, both))
    candidates.sort(key=lambda edge: (-edge[0], edge[1], edge[2]))
    kept = candidates[:MAX_EDGES]
    groups = communities(len(chosen), [(i, j, float(both)) for _, i, j, both in kept])
    nodes = [center] + [
        NetworkNode(
            *names[entry.key], entry.kind, entry.inside, round(entry.lift, 2), groups[i], False
        )
        for i, entry in enumerate(chosen)
    ]
    # Node 0 is the center, so the others move up one.
    edges = [NetworkEdge(i + 1, j + 1, both, round(jaccard, 4)) for jaccard, i, j, both in kept]
    return nodes, edges


def communities(size: int, edges: Sequence[tuple[int, int, float]]) -> list[int]:
    """Groups of nodes that go together, by greedy modularity (Clauset, Newman and Moore).

    Starting from one group per node, merge the two groups whose merging raises modularity
    most, until no merge does. Groups are numbered by size, largest first; ties by their
    first node. Deterministic, and quick for the few dozen nodes of a term's network.
    """
    total = sum(weight for _, _, weight in edges)
    group = list(range(size))
    if total <= 0:
        return group
    degree = [0.0] * size
    between: dict[tuple[int, int], float] = {}
    for i, j, weight in edges:
        degree[i] += weight
        degree[j] += weight
        key = (min(i, j), max(i, j))
        between[key] = between.get(key, 0.0) + weight
    members = {i: [i] for i in range(size)}
    while True:
        best: tuple[float, int, int] | None = None
        for (a, b), weight in sorted(between.items()):
            gain = weight / total - degree[a] * degree[b] / (2 * total * total)
            if gain > 1e-12 and (best is None or gain > best[0]):
                best = (gain, a, b)
        if best is None:
            break
        _, keep, gone = best
        members[keep] += members.pop(gone)
        degree[keep] += degree[gone]
        merged: dict[tuple[int, int], float] = {}
        for (a, b), weight in between.items():
            a, b = (keep if a == gone else a), (keep if b == gone else b)
            if a != b:
                key = (min(a, b), max(a, b))
                merged[key] = merged.get(key, 0.0) + weight
        between = merged
    ordered = sorted(members.values(), key=lambda nodes: (-len(nodes), min(nodes)))
    for number, nodes in enumerate(ordered):
        for node in nodes:
            group[node] = number
    return group


# --- the pipeline by phase ----------------------------------------------------------------

PIPELINE_PHASES: tuple[str, ...] = tuple(code for code in labels.PHASE if code != "NA")
"""The clinical phases, in order; trials without one aren't in a pipeline."""

PIPELINE_TOP = 40


@dataclass(frozen=True, slots=True)
class PipelineRow:
    code: str
    term: str
    kind: MeshKind
    trials: int  # the scope's trials tagged with it
    phases: list[int]  # ... in each of ``PIPELINE_PHASES``
    active: int
    highest: str | None  # the latest phase it has a trial in
    last_start: date | None


@dataclass(frozen=True, slots=True)
class FunnelRow:
    phase: str | None  # None: no phase
    trials: int
    active: int
    completed: int
    stopped: int
    unknown: int
    other: int


@dataclass(frozen=True, slots=True)
class Pipeline:
    kind: MeshKind  # of the rows: interventions for a condition, conditions for one
    phases: list[str]
    rows: list[PipelineRow]  # the ``PIPELINE_TOP`` with most trials
    funnel: list[FunnelRow]  # the scope's trials by phase and status


def pipeline(scope: Scope) -> Pipeline:
    index = scope.index
    phase = index.coded("phase")
    position = np.array(
        [PIPELINE_PHASES.index(code) if code in PIPELINE_PHASES else -1 for code in phase.codes]
        + [-1],
        np.int64,
    )[phase.values]
    kind = OTHER_KIND[scope.ref.kind]
    link = index.link(DIMENSION[kind])
    rows = scope.trials[link.trial]
    trials, values = link.trial[rows], link.value[rows]
    counts = np.bincount(values, minlength=link.size)
    top = np.flatnonzero(counts)
    top = top[np.lexsort((top, -counts[top]))][:PIPELINE_TOP]
    slot = np.full(link.size, -1, np.int64)
    slot[top] = np.arange(len(top))
    chosen = slot[values] >= 0
    trials, rows_of = trials[chosen], slot[values[chosen]]
    phases_of = position[trials]
    staged = phases_of >= 0
    width = len(PIPELINE_PHASES)
    by_phase = np.bincount(
        rows_of[staged] * width + phases_of[staged], minlength=len(top) * width
    ).reshape(-1, width)
    active = np.bincount(rows_of[scope.coded("status", ACTIVE)[trials]], minlength=len(top))
    starts = index.dates("start_date")[trials]
    last = np.full(len(top), NULL_DAY, np.int64)
    np.maximum.at(last, rows_of, starts)
    names = term_names(scope.conn, [int(key) for key in top])
    return Pipeline(
        kind=kind,
        phases=list(PIPELINE_PHASES),
        rows=[
            PipelineRow(
                *names[int(key)],
                kind,
                int(counts[key]),
                [int(n) for n in by_phase[i]],
                int(active[i]),
                _highest(by_phase[i]),
                None if last[i] == NULL_DAY else from_day_number(int(last[i])),
            )
            for i, key in enumerate(top)
        ],
        funnel=_funnel(scope),
    )


def _highest(counts: npt.NDArray[np.int64]) -> str | None:
    found = np.flatnonzero(counts)
    return PIPELINE_PHASES[int(found[-1])] if len(found) else None


def _funnel(scope: Scope) -> list[FunnelRow]:
    phase = scope.index.coded("phase")
    groups: dict[str, Mask] = {
        "active": scope.coded("status", ACTIVE),
        "completed": scope.coded("status", ("COMPLETED",)),
        "stopped": scope.coded("status", STOPPED),
        "unknown": scope.coded("status", ("UNKNOWN",)),
    }
    rows: list[FunnelRow] = []
    for code in (*labels.PHASE, None):
        place = -1 if code is None else phase.code_of(code)
        if place is None:
            continue
        here = scope.trials & (phase.values == place)
        trials = int(np.count_nonzero(here))
        if not trials:
            continue
        counts = {name: int(np.count_nonzero(here & mask)) for name, mask in groups.items()}
        rows.append(FunnelRow(code, trials, **counts, other=trials - sum(counts.values())))
    return rows
