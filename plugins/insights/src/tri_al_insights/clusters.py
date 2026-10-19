"""The clinical research landscape: a map of recent trials by what they're about.

The trials first posted in the last ``months`` months are laid out from their vectors
(``tri_al.embeddings``): UMAP finds each trial's nearest neighbours by cosine and places
them in 2-D for the map. HDBSCAN finds the dense groups in a second UMAP layout over the
same neighbours, in 10-D, and each group is named after its most distinctive MeSH term
(common in it, rare elsewhere). A third places them in 3-D for the analysis page, with the
same clusters. That takes about a minute for 50,000 trials, so it's done once per data
version, as ``Derived`` tables the pipeline rebuilds before the charts; the charts only read
them. With a filter, the charts show the matching trials where they sit on the same map.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import numpy.typing as npt
import orjson
from sqlalchemy import (
    Column,
    Connection,
    Float,
    Integer,
    MetaData,
    Table,
    Text,
    delete,
    func,
    insert,
    select,
)

from tri_al import embeddings
from tri_al.filters import TrialFilter
from tri_al.stats import ChartContext, Rows
from tri_al.storage import Migration, filtering
from tri_al.storage import tables as t
from tri_al_insights.trends import months_before

MIGRATIONS = (
    Migration(
        1,
        "landscape of recent trials",
        """\
CREATE TABLE insights_landscape (
    trial_id INTEGER NOT NULL PRIMARY KEY REFERENCES trials (id) ON DELETE CASCADE,
    x REAL NOT NULL,
    y REAL NOT NULL,
    cluster INTEGER NOT NULL
);
CREATE TABLE insights_clusters (
    cluster INTEGER NOT NULL PRIMARY KEY,
    label TEXT NOT NULL,
    size INTEGER NOT NULL
);
CREATE TABLE insights_landscape_info (
    id INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
    info TEXT NOT NULL
);
""",
    ),
    Migration(
        2,
        "landscape in three dimensions",
        """\
CREATE TABLE insights_landscape_3d (
    trial_id INTEGER NOT NULL PRIMARY KEY REFERENCES trials (id) ON DELETE CASCADE,
    x REAL NOT NULL,
    y REAL NOT NULL,
    z REAL NOT NULL
);
""",
    ),
)

_metadata = MetaData()
landscape = Table(
    "insights_landscape",
    _metadata,
    Column("trial_id", Integer, primary_key=True),
    Column("x", Float, nullable=False),
    Column("y", Float, nullable=False),
    Column("cluster", Integer, nullable=False),  # -1: in no cluster
)
clusters = Table(
    "insights_clusters",
    _metadata,
    Column("cluster", Integer, primary_key=True),
    Column("label", Text, nullable=False),
    Column("size", Integer, nullable=False),
)
info_table = Table(
    "insights_landscape_info",
    _metadata,
    Column("id", Integer, primary_key=True),
    Column("info", Text, nullable=False),  # JSON: what the summary row says
)
landscape_3d = Table(
    "insights_landscape_3d",
    _metadata,
    Column("trial_id", Integer, primary_key=True),
    Column("x", Float, nullable=False),  # centred, and scaled so most trials are within 1
    Column("y", Float, nullable=False),
    Column("z", Float, nullable=False),
)


COLORED = 8
"""Clusters that get a colour, the largest on the whole map: the categorical palette's size."""


SMALL_DATA = 4_096
"""UMAP finds neighbours approximately from this many rows on (``umap.umap_``)."""


@dataclass(frozen=True, slots=True)
class ClusterOptions:
    months: int = 12
    # 38 to 44 clusters for the 51k trials of a year, over every random state and update tried.
    min_cluster_size: int = 350
    min_samples: int = 25
    dimensions: int = 10  # of the layout HDBSCAN clusters
    neighbors: int = 15
    min_dist: float = 0.1
    max_points: int = 3_000
    windows: tuple[int, ...] = (3, 6)  # months the chart can narrow the map to
    random_state: int = 42
    solid: bool = True  # also lay the trials out in 3-D, for the analysis page
    max_points_3d: int = 20_000


@dataclass(frozen=True, slots=True)
class Projection:
    flat: npt.NDArray[np.float64]  # one row (x, y) per trial: the dashboard's map
    solid: npt.NDArray[np.float64] | None  # (x, y, z) per trial, for the analysis page; None: off
    labels: npt.NDArray[np.int32]  # HDBSCAN clusters, one per trial; -1: in none


# --- building the map, once per data version -------------------------------------------------


def build_landscape(conn: Connection, data_version: int, options: ClusterOptions) -> None:
    """Lay out the recent trials that have vectors, replacing the previous map."""
    for table in (landscape, landscape_3d, clusters, info_table):
        conn.execute(delete(table))
    info: dict[str, Any] = {"data_version": data_version, "computed_at": _now()}
    latest = conn.execute(select(func.max(t.trials.c.first_posted))).scalar_one()
    if latest is None:
        _write_info(conn, {**info, "status": "no_trials"})
        return
    assert isinstance(latest, date)
    since = months_before(latest, options.months)
    window = select(t.trials.c.id).where(
        t.trials.c.first_posted >= since, t.trials.c.first_posted <= latest
    )
    info |= {
        "since": since.isoformat(),
        "until": latest.isoformat(),
        "total_trials": conn.execute(
            select(func.count()).select_from(window.subquery())
        ).scalar_one(),
    }
    model = embeddings.active_model(conn)
    if model is None:
        _write_info(conn, {**info, "status": "missing_embeddings"})
        return
    ids, matrix = embeddings.vectors_of(conn, model, window)
    info |= {"model": model.model, "dimensions": model.dimensions, "embedded_trials": len(ids)}
    if len(ids) < 3:
        status = "missing_embeddings" if not ids else "insufficient_data"
        _write_info(conn, {**info, "status": status})
        return

    projection = project_and_cluster(matrix, options)
    labels = projection.labels
    names, sizes = distinctive_labels(labels, _trial_terms(conn, ids))
    conn.execute(
        insert(landscape),
        [
            {"trial_id": trial_id, "x": float(x), "y": float(y), "cluster": int(label)}
            for trial_id, (x, y), label in zip(ids, projection.flat, labels, strict=True)
        ],
    )
    if projection.solid is not None:
        conn.execute(
            insert(landscape_3d),
            [
                {"trial_id": trial_id, "x": float(x), "y": float(y), "z": float(z)}
                for trial_id, (x, y, z) in zip(ids, fitted(projection.solid), strict=True)
            ],
        )
    conn.execute(
        insert(clusters),
        [{"cluster": c, "label": names[c], "size": size} for c, size in sizes.items()],
    )
    _write_info(
        conn,
        {
            **info,
            "status": "ready",
            "clusters": sum(1 for c in sizes if c >= 0),
            "noise_trials": sizes.get(-1, 0),
            "solid": projection.solid is not None,
        },
    )


def project_and_cluster(matrix: npt.NDArray[np.float32], options: ClusterOptions) -> Projection:
    """UMAP layouts over cosine neighbours, in 2-D, ``options.dimensions`` and 3-D, and
    HDBSCAN clusters of the second.

    The nearest neighbours are found once, for every layout, from the random state the 2-D
    layout then goes on with, so the 2-D map is exactly what UMAP makes by itself. The
    clusters come from a layout of their own, packed tight (``min_dist`` 0, as BERTopic does),
    with HDBSCAN's "leaf" selection. Its usual "eom" on the 2-D map found anywhere from 2 to 47
    clusters for the 50,920 trials of a year as the random state changed or 2% of the trials
    went, since it sometimes keeps the map's first split; this way, 38 to 44, and two runs
    put trials together much the same way (adjusted Rand index 0.70, against 0.14). The 3-D
    layout runs half UMAP's usual 200 epochs: it still keeps more of each trial's ten nearest
    neighbours (24%, against 26% at 200) than the 2-D map does (17%).
    """
    from sklearn.cluster import HDBSCAN  # type: ignore[import-untyped]
    from umap import UMAP  # type: ignore[import-untyped]
    from umap.umap_ import nearest_neighbors  # type: ignore[import-untyped]

    count = len(matrix)
    neighbors = min(options.neighbors, count - 1)
    random_state = np.random.RandomState(options.random_state)
    # Under 4,096 rows UMAP uses exact distances instead; then each layout finds its own.
    knn = (
        nearest_neighbors(
            matrix, neighbors, "cosine", {}, False, random_state, low_memory=True, n_jobs=1
        )
        if count >= SMALL_DATA
        else (None, None, None)
    )

    def layout(
        components: int,
        random_state: np.random.RandomState,
        min_dist: float,
        epochs: int | None = None,
    ) -> npt.NDArray[np.float64]:
        coordinates = UMAP(
            n_components=components,
            n_epochs=epochs,
            n_neighbors=neighbors,
            min_dist=min_dist,
            metric="cosine",
            init="random",
            random_state=random_state,
            n_jobs=1,
            precomputed_knn=knn,
        ).fit_transform(matrix)
        return np.asarray(coordinates, np.float64)

    flat = layout(2, random_state, options.min_dist)
    grouped = layout(options.dimensions, np.random.RandomState(options.random_state), 0.0)
    labels = HDBSCAN(
        min_cluster_size=min(options.min_cluster_size, count),
        min_samples=min(options.min_samples, count - 1),
        metric="euclidean",
        cluster_selection_method="leaf",
        copy=False,
    ).fit_predict(grouped)
    solid = (
        layout(3, np.random.RandomState(options.random_state), options.min_dist, epochs=100)
        if options.solid
        else None
    )
    return Projection(flat, solid, np.asarray(labels, np.int32))


def fitted(coordinates: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """``coordinates`` centred on their median, and scaled so 99% of them are within 1.

    UMAP's units mean nothing, and a few far-off trials shouldn't shrink the rest.
    """
    centred = coordinates - np.median(coordinates, axis=0)
    radius = float(np.percentile(np.linalg.norm(centred, axis=1), 99))
    return centred / radius if radius > 0 else centred


def distinctive_labels(
    labels: npt.NDArray[np.int32], terms: Sequence[set[str]]
) -> tuple[dict[int, str], dict[int, int]]:
    """Each cluster's name and size.

    The name is the term that best sets the cluster apart: frequent in it and rare in the
    rest (count in the cluster times log(trials / trials with the term), as c-TF-IDF does),
    so a term every cluster has, such as "Healthy Volunteers", doesn't name them all.
    """
    sizes = Counter(int(label) for label in labels)
    overall: Counter[str] = Counter()
    by_cluster: dict[int, Counter[str]] = defaultdict(Counter)
    for label, trial_terms in zip(labels, terms, strict=True):
        overall.update(trial_terms)
        by_cluster[int(label)].update(trial_terms)
    total = len(labels)
    names: dict[int, str] = {-1: "Unclustered"}
    for label in sorted(sizes):
        if label < 0:
            continue
        scored = [
            (count * math.log(total / overall[term]), term)
            for term, count in by_cluster[label].items()
        ]
        best = max(scored, key=lambda item: (item[0], -len(item[1]), item[1]), default=None)
        names[label] = best[1] if best is not None and best[0] > 0 else f"Cluster {label + 1}"
    return names, dict(sizes)


def _trial_terms(conn: Connection, trial_ids: Sequence[int]) -> list[set[str]]:
    """Each trial's direct MeSH terms (conditions and interventions), in ``trial_ids`` order."""
    tm = t.trial_mesh
    by_id: dict[int, set[str]] = defaultdict(set)
    for start in range(0, len(trial_ids), 10_000):
        chunk = list(trial_ids[start : start + 10_000])
        for trial_id, term in conn.execute(
            select(tm.c.trial_id, t.mesh_terms.c.term)
            .join(t.mesh_terms)
            .where(tm.c.trial_id.in_(chunk), tm.c.ancestor.is_(False))
        ):
            by_id[trial_id].add(term)
    return [by_id[trial_id] for trial_id in trial_ids]


def _write_info(conn: Connection, info: dict[str, Any]) -> None:
    conn.execute(insert(info_table).values(id=1, info=orjson.dumps(info).decode()))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --- the chart -------------------------------------------------------------------------------


def research_clusters(ctx: ChartContext, filter: TrialFilter, options: ClusterOptions) -> Rows:
    """The map's summary row and up to ``max_points`` of its trials that ``filter`` matches."""
    stored = ctx.conn.execute(select(info_table.c.info)).scalar_one_or_none()
    if stored is None:
        return [_summary({"status": "missing_embeddings"})]
    info = orjson.loads(stored)
    if info["status"] != "ready":
        return [_summary(info)]
    matching = filtering.where(filter)
    total = ctx.conn.execute(
        select(func.count())
        .select_from(t.trials)
        .where(
            t.trials.c.first_posted >= date.fromisoformat(info["since"]),
            t.trials.c.first_posted <= date.fromisoformat(info["until"]),
            *matching,
        )
    ).scalar_one()
    points = ctx.conn.execute(
        select(
            landscape.c.x,
            landscape.c.y,
            landscape.c.cluster,
            t.trials.c.source_id,
            t.trials.c.title,
        )
        .join(t.trials, t.trials.c.id == landscape.c.trial_id)
        .where(*matching)
        .order_by(landscape.c.trial_id)
    ).all()
    stored_clusters = ctx.conn.execute(
        select(clusters.c.cluster, clusters.c.label, clusters.c.size)
    ).all()
    names = {row.cluster: row.label for row in stored_clusters}
    # Ranked on the whole map, so a cluster keeps its colour under every filter.
    largest = sorted(
        (row for row in stored_clusters if row.cluster >= 0), key=lambda r: (-r.size, r.cluster)
    )
    colors = {row.cluster: i for i, row in enumerate(largest[:COLORED])}
    labels = np.array([point.cluster for point in points], dtype=np.int32)
    sizes = Counter(int(label) for label in labels)
    chosen = sampled_indices(labels, options.max_points)
    rows: Rows = [
        _summary(
            info,
            windows=_windows(info, options),
            total_trials=total,
            embedded_trials=len(points),
            plotted_trials=len(chosen),
            clusters=sum(1 for c in sizes if c >= 0),
            noise_trials=sizes.get(-1, 0),
        )
    ]
    for index in chosen:
        point = points[index]
        rows.append(
            {
                "type": "point",
                "x": round(point.x, 4),
                "y": round(point.y, 4),
                "cluster": point.cluster,
                "cluster_label": names.get(point.cluster, f"Cluster {point.cluster + 1}"),
                "cluster_size": sizes[point.cluster],
                "color": colors.get(point.cluster),  # 0 to 7, or None: grey
                "title": point.title,
                "source_id": point.source_id,
            }
        )
    return rows


def research_landscape_3d(ctx: ChartContext, filter: TrialFilter, options: ClusterOptions) -> Rows:
    """The map's summary row, a row per cluster, and up to ``max_points_3d`` of its trials
    that ``filter`` matches, placed in 3-D."""
    stored = ctx.conn.execute(select(info_table.c.info)).scalar_one_or_none()
    if stored is None:
        return [_summary({"status": "missing_embeddings"})]
    info = orjson.loads(stored)
    if info["status"] != "ready":
        return [_summary(info)]
    if not info.get("solid"):
        # Laid out before the 3-D map existed, or with it turned off.
        return [_summary({**info, "status": "missing_layout" if options.solid else "disabled"})]
    matching = filtering.where(filter)
    total = ctx.conn.execute(
        select(func.count())
        .select_from(t.trials)
        .where(
            t.trials.c.first_posted >= date.fromisoformat(info["since"]),
            t.trials.c.first_posted <= date.fromisoformat(info["until"]),
            *matching,
        )
    ).scalar_one()
    points = ctx.conn.execute(
        select(
            landscape_3d.c.x,
            landscape_3d.c.y,
            landscape_3d.c.z,
            landscape.c.cluster,
            t.trials.c.source_id,
            t.trials.c.title,
        )
        .join(landscape, landscape.c.trial_id == landscape_3d.c.trial_id)
        .join(t.trials, t.trials.c.id == landscape_3d.c.trial_id)
        .where(*matching)
        .order_by(landscape_3d.c.trial_id)
    ).all()
    stored_clusters = ctx.conn.execute(
        select(clusters.c.cluster, clusters.c.label, clusters.c.size)
    ).all()
    names = {row.cluster: row.label for row in stored_clusters}
    # The same colours as the dashboard's map: ranked on the whole map, under every filter.
    largest = sorted(
        (row for row in stored_clusters if row.cluster >= 0), key=lambda r: (-r.size, r.cluster)
    )
    colors = {row.cluster: i for i, row in enumerate(largest[:COLORED])}
    labels = np.array([point.cluster for point in points], dtype=np.int32)
    sizes = Counter(int(label) for label in labels)
    chosen = sampled_indices(labels, options.max_points_3d)
    rows: Rows = [
        _summary(
            info,
            windows=_windows(info, options),
            total_trials=total,
            embedded_trials=len(points),
            plotted_trials=len(chosen),
            clusters=sum(1 for c in sizes if c >= 0),
            noise_trials=sizes.get(-1, 0),
        )
    ]
    # Coloured clusters in colour order, then the rest by size, then the trials in none.
    for cluster in sorted(
        sizes,
        key=lambda c: (c < 0, colors.get(c, COLORED), -sizes[c], c),
    ):
        rows.append(
            {
                "type": "cluster",
                "cluster": cluster,
                "label": names.get(cluster, f"Cluster {cluster + 1}"),
                "size": sizes[cluster],
                "color": colors.get(cluster),  # 0 to 7, or None: grey
            }
        )
    for index in chosen:
        point = points[index]
        rows.append(
            {
                "type": "point",
                "x": round(point.x, 4),
                "y": round(point.y, 4),
                "z": round(point.z, 4),
                "cluster": point.cluster,
                "title": point.title,
                "source_id": point.source_id,
            }
        )
    return rows


def sampled_indices(labels: npt.NDArray[np.int32], maximum: int) -> list[int]:
    """Up to ``maximum`` indexes, spread over every cluster in proportion; deterministic."""
    if len(labels) <= maximum:
        return list(range(len(labels)))
    groups: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        groups[int(label)].append(index)
    chosen: set[int] = set()
    for indexes in groups.values():
        share = min(len(indexes), max(1, round(maximum * len(indexes) / len(labels))))
        for position in np.linspace(0, len(indexes) - 1, share, dtype=int):
            chosen.add(indexes[int(position)])
    if len(chosen) < maximum:
        chosen.update(i for i in range(len(labels)) if i not in chosen)
    return sorted(chosen)[:maximum]


def _windows(info: dict[str, Any], options: ClusterOptions) -> list[dict[str, Any]]:
    """The recent windows the map can be narrowed to, then the whole map, shortest first.

    A window's ``since`` is the ``first_posted`` filter that shows its trials.
    """
    until = date.fromisoformat(info["until"])
    windows = [
        {"months": months, "since": months_before(until, months).isoformat()}
        for months in sorted(set(options.windows))
        if months < options.months
    ]
    return [*windows, {"months": options.months, "since": info["since"]}]


def _summary(
    info: dict[str, Any], *, windows: list[dict[str, Any]] | None = None, **counts: int
) -> dict[str, Any]:
    return {
        "type": "summary",
        "status": info["status"],
        "windows": windows or [],
        "total_trials": counts.get("total_trials", info.get("total_trials", 0)),
        "embedded_trials": counts.get("embedded_trials", info.get("embedded_trials", 0)),
        "plotted_trials": counts.get("plotted_trials", 0),
        "clusters": counts.get("clusters", info.get("clusters", 0)),
        "noise_trials": counts.get("noise_trials", info.get("noise_trials", 0)),
        "since": info.get("since"),
        "until": info.get("until"),
        "model": info.get("model"),
        "dimensions": info.get("dimensions"),
        "data_version": info.get("data_version"),
    }


__all__ = [
    "MIGRATIONS",
    "ClusterOptions",
    "Projection",
    "build_landscape",
    "distinctive_labels",
    "fitted",
    "project_and_cluster",
    "research_clusters",
    "research_landscape_3d",
    "sampled_indices",
]
