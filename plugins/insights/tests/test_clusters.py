import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import numpy.typing as npt
import orjson
import pytest

from tri_al import embeddings
from tri_al.filters import DateRange, TrialFilter
from tri_al.pipeline import Pipeline
from tri_al.schema import MeshTerm, TrialRecord
from tri_al.stats import ChartContext, Derived, Rows, SqlCounts
from tri_al.storage import SQLiteStorage, docs
from tri_al.testing import FakeEmbeddingEngine, FakeSource, fake_study
from tri_al.testing.fixtures import minimal_trial
from tri_al_insights import Settings, charts
from tri_al_insights import clusters as landscape
from tri_al_insights.clusters import (
    MIGRATIONS,
    ClusterOptions,
    Projection,
    build_landscape,
    distinctive_labels,
    fitted,
    research_clusters,
    research_landscape_3d,
    sampled_indices,
)

CANCER = MeshTerm("D009369", "Neoplasms", "condition")
PAIN = MeshTerm("D010146", "Pain", "condition")
HEALTHY = MeshTerm("D000000", "Healthy Volunteers", "condition")


def test_clusters_are_named_after_their_most_distinctive_term() -> None:
    labels = np.array([0, 0, 0, 1, 1, -1], dtype=np.int32)
    terms = [
        {"Healthy Volunteers", "Neoplasms"},
        {"Healthy Volunteers", "Neoplasms"},
        {"Healthy Volunteers"},
        {"Healthy Volunteers", "Pain"},
        {"Healthy Volunteers", "Pain"},
        {"Other"},
    ]

    names, sizes = distinctive_labels(labels, terms)

    # "Healthy Volunteers" is in more trials of cluster 0, but in every cluster.
    assert names == {-1: "Unclustered", 0: "Neoplasms", 1: "Pain"}
    assert sizes == {0: 3, 1: 2, -1: 1}
    assert distinctive_labels(np.array([0, 0], dtype=np.int32), [set(), set()])[0][0] == (
        "Cluster 1"
    )


def test_sampling_is_bounded_and_keeps_clusters() -> None:
    labels = np.array([0] * 80 + [1] * 15 + [-1] * 5, dtype=np.int32)
    chosen = sampled_indices(labels, 20)

    assert len(chosen) == 20
    assert set(labels[chosen]) == {-1, 0, 1}
    assert chosen == sampled_indices(labels, 20)
    assert sampled_indices(labels[:10], 20) == list(range(10))


def trials() -> list[TrialRecord]:
    """Six recent trials, three on cancer and three on pain (two in France), and an old one."""
    base = minimal_trial()
    recent = [
        replace(
            base,
            source_id=f"NCT{i:08d}",
            title=f"{'Cancer' if i < 3 else 'Pain'} trial {i}",
            first_posted=date(2026, 9, 1 + i),
            mesh_terms=[CANCER if i < 3 else PAIN],
            countries=["FR"] if i >= 4 else ["US"],
        )
        for i in range(6)
    ]
    old = replace(base, source_id="NCT99999999", title="Old", first_posted=date(2020, 1, 1))
    return [*recent, old]


def fake_layout(matrix: npt.NDArray[np.float32], options: ClusterOptions) -> Projection:
    """Clusters by the first value (the text's length), placed along a line."""
    labels = (matrix[:, 0] > np.median(matrix[:, 0])).astype(np.int32)
    line = np.arange(len(matrix))
    return Projection(
        np.column_stack([line, labels]).astype(np.float64),
        np.column_stack([line, labels, -line]).astype(np.float64) if options.solid else None,
        labels,
    )


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(landscape, "project_and_cluster", fake_layout)
    with SQLiteStorage.open(
        tmp_path / "trials.db", plugin_migrations={"insights": MIGRATIONS}
    ) as storage:
        yield storage


def embed(storage: SQLiteStorage, engine: FakeEmbeddingEngine, trial_ids: list[int]) -> None:
    with storage.engine.connect() as conn:
        texts = embeddings.load_texts(conn, trial_ids, docs.Decoder())
    vectors = engine.encode([text.text for text in texts])
    with storage.transaction() as tx:
        model = embeddings.model_for(tx.connection, engine, vectors.shape[1])
        embeddings.store(tx.connection, model, trial_ids, vectors)


def chart(storage: SQLiteStorage, filter: TrialFilter, **options: Any) -> Rows:
    with storage.read() as reader:
        conn = reader.connection
        ctx = ChartContext(conn, lambda f: SqlCounts(conn, f))
        return research_clusters(ctx, filter, ClusterOptions(**options))


def build(storage: SQLiteStorage, version: int = 1, **options: Any) -> None:
    with storage.transaction() as tx:
        build_landscape(tx.connection, version, ClusterOptions(**options))


def chart_3d(storage: SQLiteStorage, filter: TrialFilter, **options: Any) -> Rows:
    with storage.read() as reader:
        conn = reader.connection
        ctx = ChartContext(conn, lambda f: SqlCounts(conn, f))
        return research_landscape_3d(ctx, filter, ClusterOptions(**options))


def kinds(rows: Rows) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """The summary, cluster and point rows of the 3-D chart."""
    summary, *rest = rows
    assert summary["type"] == "summary"
    return (
        summary,
        [row for row in rest if row["type"] == "cluster"],
        [row for row in rest if row["type"] == "point"],
    )


def test_the_map_is_built_once_and_read_by_the_chart(storage: SQLiteStorage) -> None:
    ids = storage.upsert_batch(trials())
    embed(storage, FakeEmbeddingEngine(), ids)

    build(storage, version=7)
    rows = chart(storage, TrialFilter())

    summary, *points = rows
    assert summary == {
        "type": "summary",
        "status": "ready",
        "windows": [
            {"months": 3, "since": "2026-06-06"},
            {"months": 6, "since": "2026-03-06"},
            {"months": 12, "since": "2025-09-06"},
        ],
        "total_trials": 6,
        "embedded_trials": 6,
        "plotted_trials": 6,
        "clusters": 2,
        "noise_trials": 0,
        "since": "2025-09-06",
        "until": "2026-09-06",
        "model": "tiny",
        "dimensions": 3,
        "data_version": 7,
    }
    assert {point["source_id"] for point in points} == {f"NCT{i:08d}" for i in range(6)}
    names = {point["cluster_label"] for point in points}
    assert names == {"Neoplasms", "Pain"}
    assert {point["cluster_size"] for point in points} == {3}


def test_a_filter_shows_its_trials_on_the_same_map(storage: SQLiteStorage) -> None:
    ids = storage.upsert_batch(trials())
    embed(storage, FakeEmbeddingEngine(), ids)
    build(storage)
    everything = {point["source_id"]: point for point in chart(storage, TrialFilter())[1:]}

    summary, *points = chart(storage, TrialFilter(countries=("FR",)))

    assert (summary["total_trials"], summary["embedded_trials"], summary["clusters"]) == (2, 2, 1)
    assert [point["source_id"] for point in points] == ["NCT00000004", "NCT00000005"]
    for point in points:
        assert (point["x"], point["y"]) == (
            everything[point["source_id"]]["x"],
            everything[point["source_id"]]["y"],
        )
        assert point["cluster_size"] == 2  # within the filter
    assert len(chart(storage, TrialFilter(), max_points=4)) == 1 + 4


def test_the_map_says_what_it_needs(storage: SQLiteStorage) -> None:
    assert chart(storage, TrialFilter())[0]["status"] == "missing_embeddings"  # not built yet

    build(storage)
    assert chart(storage, TrialFilter())[0]["status"] == "no_trials"

    ids = storage.upsert_batch(trials())
    build(storage)
    [summary] = chart(storage, TrialFilter())
    assert (summary["status"], summary["total_trials"]) == ("missing_embeddings", 6)

    embed(storage, FakeEmbeddingEngine(), ids[:2])
    build(storage)
    [summary] = chart(storage, TrialFilter())
    assert (summary["status"], summary["embedded_trials"]) == ("insufficient_data", 2)


def test_the_backfill_rebuilds_the_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(landscape, "project_and_cluster", fake_layout)
    settings = Settings()
    options = settings.cluster_options()
    studies = [fake_study(f"F{i}", first_posted=f"2026-09-0{i + 1}") for i in range(4)]
    pipeline = Pipeline(
        data_dir=tmp_path / "data",
        sources=[FakeSource(studies=tuple(studies))],
        workers=0,
        embedder=FakeEmbeddingEngine(),
        trials_migrations={"insights": MIGRATIONS},
        derived=[Derived(name="landscape", build=lambda c, v: build_landscape(c, v, options))],
        charts=charts(settings),
        facets=(),
    )
    pipeline.run_install()

    summary = pipeline.run_embedding_backfill()

    assert summary.stats_errors == []
    with SQLiteStorage.open(pipeline.trials_db) as storage, storage.read() as reader:
        stored = reader.stored_stats("research_clusters")
    assert stored is not None
    assert stored.data_version == summary.data_version
    head = orjson.loads(stored.payload)[0]
    assert (head["status"], head["embedded_trials"]) == ("ready", 4)


def test_only_the_largest_clusters_get_a_colour(
    storage: SQLiteStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = storage.upsert_batch(trials())
    embed(storage, FakeEmbeddingEngine(), ids)
    build(storage)
    with storage.transaction() as tx:  # make "Pain" the larger cluster on the whole map
        tx.connection.execute(
            landscape.clusters.update().where(landscape.clusters.c.label == "Pain").values(size=100)
        )
    monkeypatch.setattr(landscape, "COLORED", 1)

    colours = {p["cluster_label"]: p["color"] for p in chart(storage, TrialFilter())[1:]}
    us_only = {
        p["cluster_label"]: p["color"] for p in chart(storage, TrialFilter(countries=("US",)))[1:]
    }

    assert colours == {"Pain": 0, "Neoplasms": None}
    # In the US, cancer trials outnumber pain trials, but colours follow the whole map.
    assert us_only == {"Pain": 0, "Neoplasms": None}


def test_the_defaults_make_about_forty_clusters_a_year() -> None:
    defaults = ClusterOptions()
    assert (defaults.min_cluster_size, defaults.min_samples, defaults.dimensions) == (350, 25, 10)
    options = Settings().cluster_options()
    assert (options.min_cluster_size, options.min_samples, options.dimensions) == (350, 25, 10)
    assert Settings(cluster_dimensions=5).cluster_options().dimensions == 5


def test_clusters_come_from_their_own_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    """HDBSCAN clusters the 10-D layout, not the map, and keeps groups "eom" would merge."""
    layouts: list[dict[str, Any]] = []
    groups = np.repeat(np.arange(4), 100)

    class FakeUMAP:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            layouts.append(kwargs)

        def fit_transform(self, matrix: npt.NDArray[np.float32]) -> npt.NDArray[np.float64]:
            components = self.kwargs["n_components"]
            if components == 2:  # the map: one long line, no groups
                return np.column_stack([np.arange(len(matrix)), np.zeros(len(matrix))])
            # Two far-apart pairs of close groups: "eom" finds 2 clusters, "leaf" 4.
            rng = np.random.default_rng(0)
            centres = np.array([0.0, 1.25, 50.0, 51.25])[groups]
            return rng.normal(centres[:, None], 0.5, size=(len(matrix), components))

    fake_umap = ModuleType("umap")
    fake_umap.UMAP = FakeUMAP  # type: ignore[attr-defined]
    fake_umap_ = ModuleType("umap.umap_")
    fake_umap_.nearest_neighbors = None  # type: ignore[attr-defined]  # 400 trials: exact
    monkeypatch.setitem(sys.modules, "umap", fake_umap)
    monkeypatch.setitem(sys.modules, "umap.umap_", fake_umap_)
    matrix = np.ones((len(groups), 8), np.float32)

    projection = landscape.project_and_cluster(
        matrix, ClusterOptions(min_cluster_size=50, min_samples=5)
    )

    assert [(f["n_components"], f["min_dist"]) for f in layouts] == [(2, 0.1), (10, 0.0), (3, 0.1)]
    assert projection.flat.shape == (400, 2)
    assert projection.solid is not None
    assert projection.solid.shape == (400, 3)
    labels = projection.labels
    assert labels.max() + 1 == 4
    # Each group is (nearly all) one cluster of its own.
    members = [labels[groups == g] for g in range(4)]
    majority = [np.bincount(m[m >= 0]).argmax() for m in members]
    assert len(set(majority)) == 4
    assert all((m == c).mean() > 0.9 for m, c in zip(members, majority, strict=True))


def test_the_windows_follow_the_settings(storage: SQLiteStorage) -> None:
    ids = storage.upsert_batch(trials())
    embed(storage, FakeEmbeddingEngine(), ids)
    build(storage)

    [summary, *_] = chart(storage, TrialFilter(), windows=(1, 12, 24))

    # 12 and 24 aren't shorter than the map's 12 months; the whole map comes last.
    assert summary["windows"] == [
        {"months": 1, "since": "2026-08-06"},
        {"months": 12, "since": "2025-09-06"},
    ]
    assert (
        chart(storage, TrialFilter(first_posted=DateRange.parse("2026-09-04..")))[0][
            "embedded_trials"
        ]
        == 3
    )


def test_the_3d_map_has_the_flat_maps_clusters(storage: SQLiteStorage) -> None:
    ids = storage.upsert_batch(trials())
    embed(storage, FakeEmbeddingEngine(), ids)
    build(storage, version=5)
    flat = {point["source_id"]: point for point in chart(storage, TrialFilter())[1:]}

    summary, clusters, points = kinds(chart_3d(storage, TrialFilter()))

    assert (summary["status"], summary["data_version"]) == ("ready", 5)
    assert (summary["embedded_trials"], summary["plotted_trials"], summary["clusters"]) == (6, 6, 2)
    assert summary["windows"][-1]["months"] == 12
    # Coloured clusters in colour order, the same colours as the flat map's.
    assert [c["color"] for c in clusters] == [0, 1]
    assert {c["label"] for c in clusters} == {"Neoplasms", "Pain"}
    assert [c["size"] for c in clusters] == [3, 3]
    assert {p["source_id"] for p in points} == set(flat)
    for point in points:
        assert set(point) == {"type", "x", "y", "z", "cluster", "title", "source_id"}
        assert point["cluster"] == flat[point["source_id"]]["cluster"]
    # Centred, and scaled so 99% of the trials are within 1.
    coordinates = np.array([[p["x"], p["y"], p["z"]] for p in points])
    assert np.allclose(np.median(coordinates, axis=0), 0, atol=1e-3)
    assert np.percentile(np.linalg.norm(coordinates, axis=1), 99) == pytest.approx(1, abs=1e-3)


def test_a_filter_shows_its_trials_in_the_same_places_in_3d(storage: SQLiteStorage) -> None:
    ids = storage.upsert_batch(trials())
    embed(storage, FakeEmbeddingEngine(), ids)
    build(storage)
    _, all_clusters, everything = kinds(chart_3d(storage, TrialFilter()))
    places = {p["source_id"]: (p["x"], p["y"], p["z"]) for p in everything}
    colours = {c["cluster"]: c["color"] for c in all_clusters}

    summary, clusters, points = kinds(chart_3d(storage, TrialFilter(countries=("FR",))))

    assert (summary["total_trials"], summary["embedded_trials"], summary["clusters"]) == (2, 2, 1)
    assert [p["source_id"] for p in points] == ["NCT00000004", "NCT00000005"]
    assert all((p["x"], p["y"], p["z"]) == places[p["source_id"]] for p in points)
    [cluster] = clusters
    assert (cluster["size"], cluster["color"]) == (2, colours[cluster["cluster"]])
    _, _, sampled = kinds(chart_3d(storage, TrialFilter(), max_points_3d=4))
    assert len(sampled) == 4


def test_grey_clusters_come_after_the_coloured_and_no_cluster_last(
    storage: SQLiteStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def layout(matrix: npt.NDArray[np.float32], options: ClusterOptions) -> Projection:
        projection = fake_layout(matrix, options)
        labels = projection.labels.copy()
        labels[0] = -1
        return Projection(projection.flat, projection.solid, labels)

    monkeypatch.setattr(landscape, "project_and_cluster", layout)
    monkeypatch.setattr(landscape, "COLORED", 1)
    ids = storage.upsert_batch(trials())
    embed(storage, FakeEmbeddingEngine(), ids)
    build(storage)

    _, clusters, points = kinds(chart_3d(storage, TrialFilter()))

    assert [(c["cluster"] >= 0, c["color"]) for c in clusters] == [
        (True, 0),
        (True, None),
        (False, None),
    ]
    assert clusters[-1]["label"] == "Unclustered"
    assert sum(c["size"] for c in clusters) == len(points) == 6


def test_the_3d_map_says_what_it_needs(storage: SQLiteStorage) -> None:
    assert chart_3d(storage, TrialFilter())[0]["status"] == "missing_embeddings"
    ids = storage.upsert_batch(trials())
    embed(storage, FakeEmbeddingEngine(), ids)

    build(storage, solid=False)

    [summary] = chart_3d(storage, TrialFilter(), solid=False)
    assert summary["status"] == "disabled"
    # A map laid out before the 3-D one existed: the stats need rebuilding.
    [summary] = chart_3d(storage, TrialFilter())
    assert summary["status"] == "missing_layout"
    assert chart(storage, TrialFilter())[0]["status"] == "ready"  # the flat map is still there
    build(storage)
    assert chart_3d(storage, TrialFilter())[0]["status"] == "ready"


def test_fitting_centres_and_ignores_a_few_far_off_trials() -> None:
    rng = np.random.default_rng(1)
    points = np.vstack([rng.normal(5, 2, size=(995, 3)), np.full((5, 3), 500.0)])

    result = fitted(points)

    assert np.allclose(np.median(result, axis=0), 0, atol=0.05)
    norms = np.linalg.norm(result, axis=1)
    assert np.percentile(norms, 99) == pytest.approx(1)
    assert np.median(norms) > 0.3  # not squashed by the far-off five
    assert np.array_equal(fitted(np.ones((4, 3))), np.zeros((4, 3)))  # all in one place
