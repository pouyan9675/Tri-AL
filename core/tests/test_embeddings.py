from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import pytest
from sqlalchemy import Connection, func, insert, select, text

from tri_al import embeddings
from tri_al.embeddings import (
    DEFAULT_MODEL,
    EmbeddingError,
    SentenceTransformerEngine,
    Vectors,
    create_engine,
    load_texts,
    model_for,
    store,
    trial_embedding_text,
    vectors_of,
)
from tri_al.pipeline import Pipeline, PipelineError, Progress
from tri_al.schema import Intervention
from tri_al.stats import Chart, ChartContext, Derived, Rows
from tri_al.storage import SQLiteStorage, docs
from tri_al.storage import tables as t
from tri_al.testing import FakeEmbeddingEngine as FakeEngine
from tri_al.testing import FakeSource, fake_study
from tri_al.testing.fixtures import minimal_trial


class BrokenEngine(FakeEngine):
    def encode(self, texts: Sequence[str]) -> Vectors:
        raise EmbeddingError("could not load the embedding model 'tiny': no network")


def pipeline_for(tmp_path: Path, engine: Any, *studies: bytes, **fields: Any) -> Pipeline:
    return Pipeline(
        data_dir=tmp_path / "data",
        sources=[FakeSource(studies=studies or (fake_study("F1"), fake_study("F2")))],
        workers=0,
        embedder=engine,
        facets=(),
        **fields,
    )


def stored(pipeline: Pipeline) -> dict[str, tuple[int, bytes]]:
    """source_id: (model_id, vector) for every stored vector."""
    with SQLiteStorage.open(pipeline.trials_db) as storage, storage.engine.connect() as conn:
        rows = conn.execute(
            select(t.trials.c.source_id, t.trial_embeddings.c.model_id, t.trial_embeddings.c.vector)
            .join(t.trial_embeddings)
            .order_by(t.trials.c.source_id)
        ).all()
    return {source_id: (model_id, bytes(vector)) for source_id, model_id, vector in rows}


def data_version(pipeline: Pipeline) -> int:
    with SQLiteStorage.open(pipeline.trials_db) as storage, storage.read() as reader:
        return reader.data_version()


# --- text and engines ------------------------------------------------------------------------


def test_the_text_puts_short_telling_fields_first() -> None:
    trial = replace(
        minimal_trial(),
        official_title="The official title",
        conditions=["Alzheimer Disease", "Dementia"],
        interventions=[Intervention("Drug A", other_names=("Alias A",))],
        brief_summary="A short summary.",
        description="A long description that is not embedded.",
    )

    assert trial_embedding_text(trial) == (
        "Title: Café Study of Sleep\n"
        "Official title: The official title\n"
        "Conditions: Alzheimer Disease; Dementia\n"
        "Interventions: Drug A / Alias A\n"
        "Summary: A short summary."
    )


def test_stored_text_matches_the_records_text(tmp_path: Path) -> None:
    trial = replace(
        minimal_trial(),
        conditions=["Condition A"],
        interventions=[Intervention("Drug A", other_names=("Alias A",))],
        brief_summary="Summary A",
    )
    with SQLiteStorage.open(tmp_path / "trials.db") as storage:
        [trial_id] = storage.upsert_batch([trial])
        with storage.engine.connect() as conn:
            [loaded] = load_texts(conn, [trial_id, 999], docs.Decoder())
            content_hash = conn.execute(select(t.trials.c.content_hash)).scalar_one()

    assert loaded.trial_id == trial_id
    assert loaded.text == trial_embedding_text(trial)
    assert loaded.content_hash == content_hash


def test_engines() -> None:
    engine = create_engine("sentence-transformers", DEFAULT_MODEL, max_tokens=32, float16=False)
    assert isinstance(engine, SentenceTransformerEngine)
    assert (engine.model, engine.max_tokens, engine.float16) == (DEFAULT_MODEL, 32, False)
    assert engine.encode([]).shape == (0, 0)  # without loading the model
    with pytest.raises(EmbeddingError, match="unknown embedding engine 'mlx'"):
        create_engine("mlx", DEFAULT_MODEL)
    with pytest.raises(EmbeddingError, match="cross-encoder: it scores query and document"):
        SentenceTransformerEngine(model="cross-encoder/ms-marco-TinyBERT-L2-v2")


def test_vectors_must_be_usable() -> None:
    np.testing.assert_allclose(embeddings.validated([[3, 4]], 1), [[0.6, 0.8]], rtol=1e-6)
    with pytest.raises(EmbeddingError, match=r"shape \(1, 2\); expected \(2, n\)"):
        embeddings.validated([[3, 4]], 2)
    with pytest.raises(EmbeddingError, match="NaN"):
        embeddings.validated([[np.nan, 1]], 1)
    with pytest.raises(EmbeddingError, match="all-zero"):
        embeddings.validated([[0, 0]], 1)


# --- storage ---------------------------------------------------------------------------------


def test_vectors_round_trip_as_float16(tmp_path: Path) -> None:
    engine = FakeEngine()
    with SQLiteStorage.open(tmp_path / "trials.db") as storage:
        ids = storage.upsert_batch(
            [replace(minimal_trial(), source_id=f"NCT{i}", title=f"Trial {i}") for i in range(3)]
        )
        vectors = engine.encode([f"Trial {i}" for i in range(3)])
        with storage.transaction() as tx:
            assert embeddings.active_model(tx.connection) is None
            model = model_for(tx.connection, engine, 3)
            store(tx.connection, model, ids, vectors)
            assert model_for(tx.connection, engine, 3) == model
            with pytest.raises(EmbeddingError, match="made 4-dimension vectors"):
                model_for(tx.connection, engine, 4)
        with storage.read() as reader:
            conn = reader.connection
            assert embeddings.active_model(conn) == model
            got_ids, got = vectors_of(conn, model)
            some_ids, _ = vectors_of(conn, model, select(t.trials.c.id).where(t.trials.c.id > 1))
            size = conn.execute(select(func.length(t.trial_embeddings.c.vector))).scalars().first()

    assert (model.engine, model.model, model.max_tokens, model.dtype) == (
        "fake",
        "tiny",
        64,
        "float16",
    )
    assert got_ids == ids
    assert some_ids == ids[1:]
    np.testing.assert_allclose(got, vectors, atol=1e-3)
    assert size == 3 * 2  # three float16 values


def test_a_new_model_makes_old_vectors_stale(tmp_path: Path) -> None:
    with SQLiteStorage.open(tmp_path / "trials.db") as storage:
        ids = storage.upsert_batch(
            [replace(minimal_trial(), source_id=f"NCT{i}", title=f"Trial {i}") for i in range(2)]
        )
        old, new = FakeEngine(model="old"), FakeEngine(model="new")
        with storage.transaction() as tx:
            store(tx.connection, model_for(tx.connection, old, 3), ids, old.encode(["a", "b"]))
            model = model_for(tx.connection, new, 3)
        with storage.read() as reader:
            assert embeddings.stale_trials(reader.connection, model) == sorted(ids, reverse=True)
            assert embeddings.active_model(reader.connection) == model


# --- the backfill ----------------------------------------------------------------------------


def embedded_count(ctx: ChartContext, _filter: Any) -> Rows:
    count = ctx.conn.execute(select(func.count()).select_from(t.trial_embeddings)).scalar_one()
    return [{"label": "Embedded", "value": count}]


def test_the_backfill_embeds_resumes_and_redoes(tmp_path: Path) -> None:
    engine = FakeEngine()
    chart = Chart(id="embedded", title="Embedded", widget="stat", query=embedded_count)
    pipeline = pipeline_for(
        tmp_path,
        engine,
        fake_study("F1"),
        fake_study("F2"),
        fake_study("F3"),
        charts=[chart],
    )
    pipeline.run_install()
    installed = data_version(pipeline)
    reports: list[Progress] = []

    first = pipeline.run_embedding_backfill(reports.append, batch_size=2)

    assert (first.trials, first.skipped, first.model) == (3, 0, "tiny")
    assert first.data_version == installed + 1
    assert engine.calls == [1, 2, 1]  # the warm-up, then batches of two
    assert [r.stage for r in reports] == ["model", "embed", "embed", "embed", "stats"]
    assert reports[-2] == Progress("embed", 3, 3, "trials")
    assert set(stored(pipeline)) == {"F1", "F2", "F3"}
    with SQLiteStorage.open(pipeline.trials_db) as storage, storage.engine.connect() as conn:
        payload = conn.execute(
            select(t.stats.c.payload, t.stats.c.data_version).where(
                t.stats.c.chart_id == "embedded"
            )
        ).one()
    assert orjson.loads(payload.payload) == [{"label": "Embedded", "value": 3}]
    assert payload.data_version == installed + 1

    again = pipeline.run_embedding_backfill()
    assert (again.trials, again.data_version) == (0, installed + 1)  # nothing new: no new version

    forced = pipeline.run_embedding_backfill(force=True)
    assert (forced.trials, forced.data_version) == (3, installed + 2)


def test_the_backfill_leaves_trials_that_changed_meanwhile(tmp_path: Path) -> None:
    pipeline = pipeline_for(tmp_path, None)
    pipeline.run_install()

    def change_f1(call: int) -> None:
        if call == 2:  # while the first batch is being embedded, an update rewrites F1
            with SQLiteStorage.open(pipeline.trials_db) as storage, storage.transaction() as tx:
                tx.connection.execute(
                    text("UPDATE trials SET content_hash = x'00' WHERE source_id = 'F1'")
                )

    pipeline = replace(pipeline, embedder=FakeEngine(during=change_f1))
    summary = pipeline.run_embedding_backfill()

    assert (summary.trials, summary.skipped) == (1, 1)
    assert set(stored(pipeline)) == {"F2"}


def test_the_backfill_needs_embeddings_and_a_database(tmp_path: Path) -> None:
    with pytest.raises(PipelineError, match="embeddings are off"):
        pipeline_for(tmp_path, None).run_embedding_backfill()
    with pytest.raises(PipelineError, match="run `tri-al install` first"):
        pipeline_for(tmp_path, FakeEngine()).run_embedding_backfill()


def test_a_stopped_backfill_keeps_its_finished_batches(tmp_path: Path) -> None:
    pipeline = pipeline_for(tmp_path, FakeEngine())
    pipeline.run_install()

    def stop(progress: Progress) -> None:
        if progress.stage == "embed" and progress.done == 1:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        pipeline.run_embedding_backfill(stop, batch_size=1)

    assert len(stored(pipeline)) == 1
    assert pipeline.run_embedding_backfill().trials == 1


# --- updates ---------------------------------------------------------------------------------


def test_an_update_embeds_the_changed_trials(tmp_path: Path) -> None:
    source = FakeSource(studies=(fake_study("F1"), fake_study("F2")))
    pipeline = replace(pipeline_for(tmp_path, FakeEngine()), sources=[source])
    pipeline.run_install()
    pipeline.run_embedding_backfill()
    before = stored(pipeline)
    changed = fake_study("F2", "A changed title", updated="2026-10-16")
    new = fake_study("F3", "A new trial", updated="2026-10-16")

    summary = replace(pipeline, sources=[replace(source, changed=(changed, new))]).run_update()

    after = stored(pipeline)
    assert "embeddings" not in summary.notes
    assert set(after) == {"F1", "F2", "F3"}
    assert after["F1"] == before["F1"]
    assert after["F2"] != before["F2"]


def test_an_update_survives_a_broken_model(tmp_path: Path) -> None:
    source = FakeSource(studies=(fake_study("F1"), fake_study("F2")))
    pipeline = replace(pipeline_for(tmp_path, FakeEngine()), sources=[source])
    pipeline.run_install()
    pipeline.run_embedding_backfill()
    changed = fake_study("F2", "A changed title", updated="2026-10-16")
    broken = replace(
        pipeline, embedder=BrokenEngine(), sources=[replace(source, changed=(changed,))]
    )

    summary = broken.run_update()

    assert summary.updated == 1
    assert summary.notes["embeddings"] == {
        "error": "EmbeddingError: could not load the embedding model 'tiny': no network",
        "trials": 1,
        "fix": "run `tri-al embeddings generate`",
    }
    assert set(stored(pipeline)) == {"F1"}  # F2 waits for the next backfill
    assert pipeline.run_embedding_backfill().trials == 1


# --- derived tables --------------------------------------------------------------------------


def test_derived_tables_are_built_before_the_charts(tmp_path: Path) -> None:
    built: list[int] = []

    def build(conn: Connection, version: int) -> None:
        built.append(version)
        conn.execute(insert(t.meta).values(key="derived", value=str(version)))

    def broken(conn: Connection, version: int) -> None:
        conn.execute(insert(t.meta).values(key="half-done", value="x"))
        raise RuntimeError("no map")

    def reads(ctx: ChartContext, _filter: Any) -> Rows:
        value = ctx.conn.execute(select(t.meta.c.value).where(t.meta.c.key == "derived"))
        return [{"label": "Derived", "value": int(value.scalar_one())}]

    pipeline = pipeline_for(
        tmp_path,
        None,
        derived=[Derived(name="ok", build=build), Derived(name="broken", build=broken)],
        charts=[Chart(id="reads", title="Reads", widget="stat", query=reads)],
    )

    summary = pipeline.run_install()

    assert built == [summary.data_version]
    assert summary.stats_errors == ["broken: RuntimeError('no map')"]
    with SQLiteStorage.open(pipeline.trials_db) as storage, storage.engine.connect() as conn:
        keys = set(conn.execute(select(t.meta.c.key)).scalars())
        payload = conn.execute(
            select(t.stats.c.payload).where(t.stats.c.chart_id == "reads")
        ).scalar_one()
    assert "half-done" not in keys  # the broken builder's writes rolled back
    assert orjson.loads(payload) == [{"label": "Derived", "value": summary.data_version}]


def test_run_stats_rebuilds_without_new_data(tmp_path: Path) -> None:
    builds: list[int] = []
    pipeline = pipeline_for(
        tmp_path, None, derived=[Derived(name="map", build=lambda conn, v: builds.append(v))]
    )
    installed = pipeline.run_install().data_version
    reports: list[Progress] = []

    summary = pipeline.run_stats(reports.append)

    assert summary.data_version == installed + 1 == data_version(pipeline)
    assert builds == [installed, installed + 1]
    assert summary.stats_errors == []
    assert reports == [Progress("stats")]


def test_run_stats_needs_a_database(tmp_path: Path) -> None:
    with pytest.raises(PipelineError, match="run `tri-al install` first"):
        pipeline_for(tmp_path, None).run_stats()
