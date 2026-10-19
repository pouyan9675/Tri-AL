"""A term seen through its trials' text: its sub-themes, and terms whose trials read alike.

Both use the trial vectors (``tri_al.embeddings``), with numpy alone. **Sub-themes** cluster
the term's trials (spherical k-means, more clusters for more trials), lay them
out in two dimensions along the directions that separate the clusters most, and name each
by the words of its titles that set it apart (a class-based TF-IDF). **Similar terms** come
from each term's average vector: the mean of its trials' vectors, less the mean of every
trial's, so what all trials share doesn't make every term look alike. These are built once
per data version in each API worker (``TermVectors``, a few seconds, ~15 MB).
"""

import itertools
import math
import re
import threading
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from sqlalchemy import Connection

from tri_al import embeddings
from tri_al.schema import MeshKind
from tri_al.stats import TrialIndex
from tri_al.stats.index import NULL_DAY, day_number
from tri_al.stats.methods import (
    Confidence,
    confidence,
    months_before,
    smoothed_ratio,
    two_sided_p,
)
from tri_al.terms.scope import DIMENSION, Scope, term_names

type Matrix = npt.NDArray[np.float32]

_CHUNK = 32_768

# --- similar terms ------------------------------------------------------------------------

MIN_TERM_TRIALS = 5
"""Trials with a vector a term needs for an average vector: fewer make a noisy one."""

QUERY_TRIALS = 20_000
"""Trials of the scope's term averaged at most (spread evenly over them)."""

SIMILAR = 12


@dataclass(frozen=True, slots=True)
class _KindVectors:
    keys: npt.NDArray[np.int64]  # mesh_terms.id
    trials: npt.NDArray[np.int64]  # trials with a vector, of each
    vectors: Matrix  # centred and normalized


@dataclass(frozen=True, slots=True)
class TermVectors:
    """Each term's average vector, as of one data version and embedding model."""

    data_version: int
    model_id: int
    dimensions: int
    mean: npt.NDArray[np.float64]  # every trial's
    kinds: dict[str, _KindVectors]

    @property
    def nbytes(self) -> int:
        return sum(kind.vectors.nbytes for kind in self.kinds.values())

    @classmethod
    def build(
        cls, conn: Connection, index: TrialIndex, model: embeddings.EmbeddingModel
    ) -> "TermVectors":
        """Read every vector once, in chunks, adding each to the terms of its trial."""
        raw = conn.connection.driver_connection
        has = np.zeros(index.size, np.bool_)
        for (trial_id,) in raw.execute(  # type: ignore[union-attr]
            "SELECT trial_id FROM trial_embeddings WHERE model_id = ?", (model.id,)
        ):
            if trial_id < index.size:
                has[trial_id] = True
        plans: dict[str, tuple[npt.NDArray[np.int64], npt.NDArray[np.int64], Matrix]] = {}
        for kind, dimension in DIMENSION.items():
            link = index.link(dimension)
            counts = np.bincount(link.value[has[link.trial]], minlength=link.size)
            keys = np.flatnonzero(counts >= MIN_TERM_TRIALS)
            slot = np.full(link.size, -1, np.int64)
            slot[keys] = np.arange(len(keys))
            plans[kind] = (keys, slot, np.zeros((len(keys), model.dimensions), np.float32))
        total = np.zeros(model.dimensions, np.float64)
        seen = 0
        position = np.full(index.size, -1, np.int64)
        cursor = raw.execute(  # type: ignore[union-attr]
            "SELECT trial_id, vector FROM trial_embeddings WHERE model_id = ?", (model.id,)
        )
        while rows := cursor.fetchmany(_CHUNK):
            ids = np.fromiter((row[0] for row in rows), np.int64, len(rows))
            vectors = _vectors([row[1] for row in rows], model.dimensions)
            inside = ids < index.size
            ids, vectors = ids[inside], vectors[inside]
            total += vectors.sum(axis=0, dtype=np.float64)
            seen += len(ids)
            position[ids] = np.arange(len(ids))
            for kind, dimension in DIMENSION.items():
                link = index.link(dimension)
                _, slot, sums = plans[kind]
                rows_of = position[link.trial]
                chosen = (rows_of >= 0) & (slot[link.value] >= 0)
                slots, places = slot[link.value[chosen]], rows_of[chosen]
                order = np.argsort(slots, kind="stable")
                slots, places = slots[order], places[order]
                if len(slots):
                    starts = np.flatnonzero(np.r_[True, slots[1:] != slots[:-1]])
                    sums[slots[starts]] += np.add.reduceat(vectors[places], starts, axis=0)
            position[ids] = -1
        mean = total / max(seen, 1)
        kinds: dict[str, _KindVectors] = {}
        for kind, dimension in DIMENSION.items():
            keys, _, sums = plans[kind]
            link = index.link(dimension)
            counts = np.bincount(link.value[has[link.trial]], minlength=link.size)[keys]
            centred = sums / np.maximum(counts, 1)[:, None] - mean.astype(np.float32)
            kinds[kind] = _KindVectors(keys, counts, _normalized(centred.astype(np.float32)))
        return cls(index.data_version, model.id, model.dimensions, mean, kinds)


class TermVectorCache:
    """One worker's ``TermVectors``, built on first use for each data version.

    Building takes a few seconds; requests that need it meanwhile wait for the one build.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._vectors: TermVectors | None = None

    def get(self, conn: Connection, index: TrialIndex) -> TermVectors | None:
        """The vectors for ``index``'s data version; None if no trial has one."""
        model = embeddings.active_model(conn)
        if model is None:
            return None
        with self._lock:
            vectors = self._vectors
            if (
                vectors is None
                or vectors.data_version != index.data_version
                or vectors.model_id != model.id
            ):
                vectors = self._vectors = TermVectors.build(conn, index, model)
            return vectors


@dataclass(frozen=True, slots=True)
class SimilarTerm:
    code: str
    term: str
    kind: MeshKind
    similarity: float  # cosine of the average vectors
    trials: int  # tagged with it (with a vector)
    shared: int  # ... that are also the scope's term's: 0 means never tagged together


@dataclass(frozen=True, slots=True)
class Similar:
    embedded: int  # the term's trials with a vector, averaged (at most ``QUERY_TRIALS``)
    same: list[SimilarTerm]  # terms of its own kind
    other: list[SimilarTerm]  # terms of the other kind


def similar(scope: Scope, vectors: TermVectors | None, narrower: Sequence[int]) -> Similar:
    """The terms whose average vector is nearest the term's, across the whole registry.

    The filter doesn't apply: average vectors are made once for every trial. The term
    itself and its narrower terms are left out.
    """
    if vectors is None:
        return Similar(0, [], [])
    ids = np.flatnonzero(scope.everywhere)
    if len(ids) > QUERY_TRIALS:
        ids = ids[np.linspace(0, len(ids) - 1, QUERY_TRIALS).round().astype(np.int64)]
    found, matrix = _read_vectors(scope.conn, vectors.model_id, vectors.dimensions, ids)
    if not found:
        return Similar(0, [], [])
    query = _normalized((matrix.mean(axis=0) - vectors.mean)[None, :].astype(np.float32))[0]
    left_out = {scope.term_id, *narrower}
    lists: dict[str, list[tuple[int, float, int]]] = {}
    for kind in DIMENSION:
        kind_vectors = vectors.kinds[kind]
        scores = kind_vectors.vectors @ query
        order = np.argsort(-scores, kind="stable")
        chosen: list[tuple[int, float, int]] = []
        for i in order:
            key = int(kind_vectors.keys[i])
            if kind == scope.ref.kind and key in left_out:
                continue
            chosen.append((key, float(scores[i]), int(kind_vectors.trials[i])))
            if len(chosen) == SIMILAR:
                break
        lists[kind] = chosen
    names = term_names(scope.conn, [key for chosen in lists.values() for key, _, _ in chosen])

    def out(kind: MeshKind) -> list[SimilarTerm]:
        link = scope.index.link(DIMENSION[kind])
        shared = np.bincount(link.value[scope.everywhere[link.trial]], minlength=link.size)
        return [
            SimilarTerm(*names[key], kind, round(score, 4), trials, int(shared[key]))
            for key, score, trials in lists[kind]
        ]

    other: MeshKind = "intervention" if scope.ref.kind == "condition" else "condition"
    return Similar(len(found), out(scope.ref.kind), out(other))


# --- sub-themes ---------------------------------------------------------------------------

SAMPLE = 4_000
"""Trials clustered at most (spread evenly over the term's)."""

POINTS = 2_000
"""Trials drawn at most."""

MIN_TRIALS = 30
"""Trials with a vector a term needs for sub-themes."""

MAX_THEMES = 8

SILHOUETTE_SAMPLE = 1_000

RECENT_MONTHS = 36
"""A theme's momentum compares its trials started in the last three years with earlier ones."""

PRIOR = 10.0

WORDS = 4

_WORD = re.compile(r"[a-z][a-z0-9]*(?:[-'][a-z0-9]+)*")

STOPWORDS = frozenset(
    """
    a about after against all also among an and any are as at be been before between both
    but by can compared comparing comparison could during each effect effects efficacy for
    from has have how in into is it its more of on or other over per safety study studies
    than that the their these this those through to trial trials under up use used using
    versus vs was were what when which while who will with within without patients patient
    subjects participants people persons individuals adults adult randomized randomised
    controlled control placebo double-blind single-blind blind open-label open label phase
    multicenter multi-center multicentre pilot prospective retrospective evaluate evaluation
    evaluating assess assessment assessing investigate investigating investigation determine
    clinical treatment treatments treated therapy therapies dose doses dosing healthy
    volunteers group groups program programme intervention interventions outcome outcomes
    effectiveness feasibility observational cohort case new novel ii iii iv one two three
    disease diseases disorder disorders syndrome condition conditions
    """.split()  # noqa: SIM905
)


@dataclass(frozen=True, slots=True)
class ThemeTrial:
    source_id: str
    title: str


@dataclass(frozen=True, slots=True)
class ThemeTerm:
    code: str
    term: str
    kind: MeshKind


@dataclass(frozen=True, slots=True)
class Theme:
    cluster: int
    label: str  # its most distinctive words
    words: list[str]
    terms: list[ThemeTerm]  # MeSH terms more common in it than in the term's other trials
    size: int  # sampled trials in it
    share: float  # ... of the sampled
    growth: float  # its share of trials started in the last 3 years over its share before
    confidence: Confidence
    examples: list[ThemeTrial]  # nearest its centre


@dataclass(frozen=True, slots=True)
class ThemePoint:
    x: float
    y: float
    cluster: int
    source_id: str
    title: str


@dataclass(frozen=True, slots=True)
class Themes:
    trials: int  # the scope's
    embedded: int  # ... with a vector
    sampled: int  # ... clustered
    silhouette: float | None  # how well the clusters separate, -1 to 1 (text: about 0.1)
    themes: list[Theme]  # largest first
    points: list[ThemePoint]


def themes(scope: Scope, narrower: Sequence[int]) -> Themes:
    model = embeddings.active_model(scope.conn)
    ids = np.flatnonzero(scope.trials)
    if model is None:
        return Themes(len(ids), 0, 0, None, [], [])
    sample = ids if len(ids) <= SAMPLE else _spread(ids, SAMPLE)
    found, matrix = _read_vectors(scope.conn, model.id, model.dimensions, sample)
    embedded = _embedded(scope.conn, model.id, ids) if len(ids) > SAMPLE else len(found)
    if len(found) < MIN_TRIALS:
        return Themes(len(ids), embedded, len(found), None, [], [])
    trial_ids = np.asarray(found, np.int64)
    points = _normalized((matrix - matrix.mean(axis=0)).astype(np.float32))
    labels, centres, silhouette = _cluster(points)
    order = np.argsort(-np.bincount(labels, minlength=len(centres)), kind="stable")
    rank = np.empty(len(order), np.int64)
    rank[order] = np.arange(len(order))
    labels, centres = rank[labels], centres[order]

    info = _titles(scope.conn, trial_ids)
    titles = [info.get(int(i), ("", ""))[1] for i in trial_ids]
    words = _distinctive_words(titles, labels, len(centres), scope.ref.term)
    terms = _distinctive_terms(scope, trial_ids, labels, len(centres), narrower)
    started = scope.index.dates("start_date")[trial_ids]
    today = day_number(scope.as_of)
    since = day_number(months_before(scope.as_of, RECENT_MONTHS))
    known = (started != NULL_DAY) & (started <= today)
    recent = known & (started >= since)
    total_recent = int(recent.sum())
    total_older = int((known & ~recent).sum())

    result: list[Theme] = []
    for c in range(len(centres)):
        members = np.flatnonzero(labels == c)
        nearest = members[np.argsort(-(points[members] @ centres[c]), kind="stable")[:3]]
        r = int(recent[members].sum())
        o = int((known & ~recent)[members].sum())
        if total_recent and total_older:
            growth = smoothed_ratio(r, o, total_recent, total_older, PRIOR)
            p = two_sided_p(r, r + o, total_recent / (total_recent + total_older))
        else:
            growth, p = 1.0, 1.0
        chosen = words[c]
        result.append(
            Theme(
                cluster=c,
                label=" · ".join(chosen[:3]) or f"Theme {c + 1}",
                words=chosen,
                terms=terms[c],
                size=len(members),
                share=round(len(members) / len(labels), 4),
                growth=round(growth, 3),
                confidence=confidence(p),
                examples=[ThemeTrial(*info.get(int(trial_ids[i]), ("", ""))) for i in nearest],
            )
        )

    xy = _layout(points, labels, centres)
    drawn = _spread(np.arange(len(trial_ids)), POINTS)
    return Themes(
        trials=len(ids),
        embedded=embedded,
        sampled=len(found),
        silhouette=None if silhouette is None else round(silhouette, 3),
        themes=result,
        points=[
            ThemePoint(
                round(float(xy[i, 0]), 4),
                round(float(xy[i, 1]), 4),
                int(labels[i]),
                info.get(int(trial_ids[i]), ("", ""))[0],
                titles[i][:120],
            )
            for i in drawn
        ],
    )


def _cluster(points: Matrix) -> tuple[npt.NDArray[np.int64], Matrix, float]:
    """Spherical k-means with ``theme_count`` clusters, and its silhouette."""
    n = len(points)
    labels, centres = kmeans(points, theme_count(n), seed=0)
    rng = np.random.default_rng(0)
    probe = np.sort(rng.choice(n, min(n, SILHOUETTE_SAMPLE), replace=False))
    return labels, centres, silhouette(points[probe], labels[probe])


def theme_count(trials: int) -> int:
    """Clusters for ``trials``: √(trials / 50), from 2 to ``MAX_THEMES``.

    Trial vectors don't fall into clean clusters, so the silhouette hardly changes with the
    number (about 0.09 from 2 to 12 for Alzheimer's 3,869 trials) and can't choose it.
    """
    return max(2, min(MAX_THEMES, round(math.sqrt(trials / 50))))


def kmeans(
    points: Matrix, k: int, *, seed: int = 0, tries: int = 3, iterations: int = 50
) -> tuple[npt.NDArray[np.int64], Matrix]:
    """Spherical k-means on unit vectors: clusters by cosine similarity.

    Seeded k-means++, ``tries`` times, keeping the clustering with the highest total
    similarity to the centres. Deterministic for a given ``seed``.
    """
    rng = np.random.default_rng(seed)
    n = len(points)
    best: tuple[float, npt.NDArray[np.int64], Matrix] | None = None
    for _ in range(tries):
        centres = np.empty((k, points.shape[1]), np.float32)
        centres[0] = points[rng.integers(n)]
        distance = 1 - points @ centres[0]
        for i in range(1, k):
            weights = np.maximum(distance, 0) ** 2
            total = weights.sum()
            pick = rng.choice(n, p=weights / total) if total > 0 else rng.integers(n)
            centres[i] = points[pick]
            distance = np.minimum(distance, 1 - points @ centres[i])
        labels = np.zeros(n, np.int64)
        for step in range(iterations):
            similarity = points @ centres.T
            new = similarity.argmax(axis=1)
            if step and np.array_equal(new, labels):
                break
            labels = new
            for i in range(k):
                members = points[labels == i]
                if len(members):
                    centres[i] = _normalized(members.sum(axis=0)[None, :])[0]
                else:  # an empty cluster takes the point furthest from its centre
                    far = int(np.argmin(similarity[np.arange(n), labels]))
                    centres[i] = points[far]
                    labels[far] = i
        fit = float((points * centres[labels]).sum())
        if best is None or fit > best[0]:
            best = (fit, labels.copy(), centres.copy())
    assert best is not None
    return best[1], best[2]


def silhouette(points: Matrix, labels: npt.NDArray[np.int64]) -> float:
    """The mean silhouette by cosine distance: near 1, tight separate clusters; near 0,
    overlapping ones."""
    clusters = np.unique(labels)
    if len(clusters) < 2:
        return 0.0
    distance = 1 - points @ points.T
    sizes = np.array([np.count_nonzero(labels == c) for c in clusters], np.float64)
    sums = np.stack([distance[:, labels == c].sum(axis=1) for c in clusters], axis=1)
    own = np.searchsorted(clusters, labels)
    own_size = sizes[own] - 1
    a = np.where(own_size > 0, sums[np.arange(len(labels)), own] / np.maximum(own_size, 1), 0)
    means = sums / sizes
    means[np.arange(len(labels)), own] = np.inf
    b = means.min(axis=1)
    score = np.where(own_size > 0, (b - a) / np.maximum(np.maximum(a, b), 1e-12), 0)
    return float(score.mean())


def _layout(points: Matrix, labels: npt.NDArray[np.int64], centres: Matrix) -> Matrix:
    """Two dimensions along which the clusters differ most (the leading directions of the
    between-cluster scatter), topped up by the main direction within clusters for two
    clusters; scaled so nearly every point is within 1."""
    sizes = np.bincount(labels, minlength=len(centres)).astype(np.float64)
    mean = points.mean(axis=0)
    spread = (centres - mean) * np.sqrt(sizes / sizes.sum())[:, None]
    _, values, vectors = np.linalg.svd(spread, full_matrices=False)
    axes = [vectors[i] for i in range(len(values)) if values[i] > 1e-6][:2]
    if len(axes) < 2:
        rest = points - mean
        for axis in axes:
            rest = rest - np.outer(rest @ axis, axis)
        _, _, more = np.linalg.svd(rest[: min(len(rest), 2_000)], full_matrices=False)
        axes += [more[i] for i in range(2 - len(axes))]
    xy = (points - mean) @ np.stack(axes, axis=1)
    scale = np.percentile(np.abs(xy), 99, axis=0)
    result: Matrix = (xy / np.where(scale > 0, scale, 1)).astype(np.float32)
    return result


def _distinctive_words(
    titles: Sequence[str], labels: npt.NDArray[np.int64], k: int, term: str
) -> list[list[str]]:
    """Each cluster's words and two-word phrases, most distinctive first.

    A class-based TF-IDF: how common a word is in the cluster's titles, times how much more
    common than in all of them (the log of the ratio). Words of the term's own name are
    left out, since every title has them.
    """
    own = set(_WORD.findall(term.lower()))
    documents = [_tokens(title, own) for title in titles]
    overall: Counter[str] = Counter()
    per_cluster: list[Counter[str]] = [Counter() for _ in range(k)]
    for tokens, label in zip(documents, labels, strict=True):
        overall.update(tokens)
        per_cluster[int(label)].update(tokens)
    sizes = np.bincount(labels, minlength=k)
    n = len(titles)
    result: list[list[str]] = []
    for c in range(k):
        scored = []
        for word, count in per_cluster[c].items():
            if count < 3:
                continue
            here, everywhere = count / sizes[c], overall[word] / n
            if here > everywhere:
                scored.append((here * math.log(here / everywhere), word))
        scored.sort(key=lambda item: (-item[0], item[1]))
        chosen: list[str] = []
        for _, word in scored:
            # A word inside a chosen phrase, or a phrase of chosen words, adds nothing.
            if any(word in other.split() or other in word.split() for other in chosen):
                continue
            chosen.append(word)
            if len(chosen) == WORDS:
                break
        result.append(chosen)
    return result


def _tokens(title: str, own: set[str]) -> set[str]:
    words = [w.removesuffix("'s") for w in _WORD.findall(title.lower())]
    words = [w for w in words if w not in STOPWORDS and w not in own]
    words = [w for w in words if len(w) > 2 or any(ch.isdigit() for ch in w)]
    return set(words) | {f"{a} {b}" for a, b in itertools.pairwise(words)}


def _distinctive_terms(
    scope: Scope,
    trial_ids: npt.NDArray[np.int64],
    labels: npt.NDArray[np.int64],
    k: int,
    narrower: Sequence[int],
) -> list[list[ThemeTerm]]:
    """Each cluster's MeSH terms (of either kind) most over-represented in it."""
    place = np.full(scope.index.size, -1, np.int64)
    place[trial_ids] = np.arange(len(trial_ids))
    sizes = np.bincount(labels, minlength=k)
    n = len(trial_ids)
    left_out = {scope.term_id, *narrower}
    scored: list[list[tuple[float, str, int]]] = [[] for _ in range(k)]
    for kind, dimension in DIMENSION.items():
        link = scope.index.link(dimension)
        rows = place[link.trial]
        chosen = rows >= 0
        values, clusters = link.value[chosen], labels[rows[chosen]]
        total = np.bincount(values, minlength=link.size)
        for c in range(k):
            here = np.bincount(values[clusters == c], minlength=link.size)
            for key in np.flatnonzero(here >= 3):
                if kind == scope.ref.kind and int(key) in left_out:
                    continue
                inside, outside = int(here[key]), int(total[key] - here[key])
                if n - sizes[c] <= 0:
                    continue
                lift = smoothed_ratio(inside, outside, int(sizes[c]), n - int(sizes[c]), PRIOR)
                if lift > 1.5:
                    scored[c].append((lift, kind, int(key)))
    best = [sorted(items, key=lambda item: (-item[0], item[2]))[:3] for items in scored]
    names = term_names(scope.conn, [key for items in best for _, _, key in items])
    return [
        [ThemeTerm(*names[key], kind) for _, kind, key in items]  # type: ignore[arg-type]
        for items in best
    ]


# --- shared -------------------------------------------------------------------------------


def _spread(ids: npt.NDArray[np.int64], count: int) -> npt.NDArray[np.int64]:
    """At most ``count`` of ``ids``, evenly spread, so a sample covers old and new trials."""
    if len(ids) <= count:
        return ids
    result: npt.NDArray[np.int64] = ids[np.linspace(0, len(ids) - 1, count).round().astype(int)]
    return result


def _read_vectors(
    conn: Connection, model_id: int, dimensions: int, ids: npt.NDArray[np.int64]
) -> tuple[list[int], Matrix]:
    raw = conn.connection.driver_connection
    rows = raw.execute(  # type: ignore[union-attr]
        "SELECT trial_id, vector FROM trial_embeddings WHERE model_id = ?"
        " AND trial_id IN (SELECT value FROM json_each(?)) ORDER BY trial_id",
        (model_id, _json_ids(ids)),
    ).fetchall()
    return [row[0] for row in rows], _vectors([row[1] for row in rows], dimensions)


def _embedded(conn: Connection, model_id: int, ids: npt.NDArray[np.int64]) -> int:
    raw = conn.connection.driver_connection
    (count,) = raw.execute(  # type: ignore[union-attr]
        "SELECT count(*) FROM trial_embeddings WHERE model_id = ?"
        " AND trial_id IN (SELECT value FROM json_each(?))",
        (model_id, _json_ids(ids)),
    ).fetchone()
    return int(count)


def _titles(conn: Connection, ids: npt.NDArray[np.int64]) -> dict[int, tuple[str, str]]:
    raw = conn.connection.driver_connection
    rows = raw.execute(  # type: ignore[union-attr]
        "SELECT id, source_id, title FROM trials WHERE id IN (SELECT value FROM json_each(?))",
        (_json_ids(ids),),
    )
    return {key: (source_id, title) for key, source_id, title in rows}


def _json_ids(ids: npt.NDArray[np.int64]) -> str:
    return "[" + ",".join(str(int(i)) for i in ids) + "]"


def _vectors(blobs: Sequence[bytes], dimensions: int) -> Matrix:
    if not blobs:
        return np.empty((0, dimensions), np.float32)
    flat = np.frombuffer(b"".join(blobs), dtype="<f2")
    result: Matrix = flat.reshape(len(blobs), dimensions).astype(np.float32)
    return result


def _normalized(matrix: Matrix) -> Matrix:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    result: Matrix = (matrix / np.where(norms > 0, norms, 1)).astype(np.float32)
    return result
