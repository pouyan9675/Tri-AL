import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from tri_al.pipeline import (
    Event,
    FetchContext,
    InstallFinished,
    Pipeline,
    PipelineError,
    Progress,
    Subscription,
    TrialsChanged,
    UpdateFinished,
    UpdateStarted,
    content_hash,
    prepare,
)
from tri_al.schema import Arm, TrialRecord
from tri_al.storage import SQLiteStorage, StorageError
from tri_al.testing import FakeSource, fake_study
from tri_al.testing.storage import source_ids

STUDIES = (
    fake_study("F1", "Donepezil in mild AD", updated="2026-09-01", status="RECRUITING"),
    fake_study("F2", "Aducanumab", updated="2026-10-14", enrollment=100, conditions=["AD"]),
    fake_study("F3", "Lecanemab", updated="2026-10-15", countries=["US", "JP"]),
)


def make_pipeline(data_dir: Path, source: FakeSource, **fields: Any) -> Pipeline:
    return Pipeline(data_dir=data_dir, sources=[source], **{"workers": 0, **fields})


@pytest.fixture
def source() -> FakeSource:
    return FakeSource(studies=STUDIES)


@pytest.fixture
def pipeline(tmp_path: Path, source: FakeSource) -> Pipeline:
    return make_pipeline(tmp_path / "data", source)


@pytest.fixture
def installed(pipeline: Pipeline) -> Pipeline:
    pipeline.run_install()
    return pipeline


def query_db(path: Path, sql: str) -> list[tuple[Any, ...]]:
    with SQLiteStorage.open(path) as storage, storage.engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql))]


def query(pipeline: Pipeline, sql: str) -> list[tuple[Any, ...]]:
    return query_db(pipeline.trials_db, sql)


def meta(pipeline: Pipeline) -> dict[str, str]:
    return dict(query(pipeline, "SELECT key, value FROM meta"))


def titles(pipeline: Pipeline) -> dict[str, str]:
    return dict(query(pipeline, "SELECT source_id, title FROM trials"))


def recorder() -> tuple[list[Event], dict[str, list[Subscription]]]:
    events: list[Event] = []
    subscriptions = {
        name: [Subscription("test", events.append)]
        for name in ("update.started", "trials.changed", "update.finished", "install.finished")
    }
    return events, subscriptions


def fail_at(stage: str, after: int = 0) -> Callable[[Progress], None]:
    """A progress callback that raises at the ``after``-th report from ``stage``."""
    seen = 0

    def progress(report: Progress) -> None:
        nonlocal seen
        if report.stage == stage:
            if seen == after:
                raise RuntimeError(f"stop at {stage}")
            seen += 1

    return progress


# --- prepare --------------------------------------------------------------------------------


def test_prepare_parses_hashes_and_normalizes(source: FakeSource) -> None:
    result = prepare(source, STUDIES[1])

    assert result.error is None
    assert result.record is not None
    assert result.record.source_id == "F2"
    assert result.record.raw == STUDIES[1]
    assert result.record.content_hash == content_hash(source, json.loads(STUDIES[1]))
    assert len(result.record.content_hash) == 16


def test_the_hash_ignores_key_order_and_what_hashable_drops(source: FakeSource) -> None:
    study = json.loads(STUDIES[0])
    reordered = dict(reversed(study.items()))
    new_snapshot = study | {"snapshot": "2026-10-19"}

    assert content_hash(source, reordered) == content_hash(source, study)
    assert content_hash(source, new_snapshot) == content_hash(source, study)
    assert content_hash(source, study | {"status": "COMPLETED"}) != content_hash(source, study)


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        (b"{nope", "JSONDecodeError"),
        (b"[1, 2]", "expected a JSON object, got list"),
        (fake_study("F9", broken=True), "ValueError: F9: this study is broken"),
    ],
)
def test_prepare_returns_errors(source: FakeSource, raw: bytes, error: str) -> None:
    result = prepare(source, raw)

    assert result.record is None
    assert result.error is not None
    assert error in result.error


# --- install --------------------------------------------------------------------------------


def test_install_loads_every_trial(pipeline: Pipeline) -> None:
    summary = pipeline.run_install()

    assert titles(pipeline) == {"F1": "Donepezil in mild AD", "F2": "Aducanumab", "F3": "Lecanemab"}
    counts = summary.sources["fake"]
    assert (counts.fetched, counts.new, counts.updated, counts.unchanged) == (3, 3, 0, 0)
    assert summary.data_version == 1
    assert summary.notes == {"fake": {"studies": 3}}
    assert set(summary.stages) == {"load", "index", "enrich", "stats", "check", "swap"}
    assert meta(pipeline) == {"data_version": "1", "cursor.fake": "2026-10-15"}


def test_install_swaps_the_new_database_in(pipeline: Pipeline) -> None:
    pipeline.run_install()

    files = sorted(path.name for path in pipeline.data_dir.iterdir())
    assert files == ["app.db", "trials.db"]


def test_install_records_its_run(pipeline: Pipeline) -> None:
    summary = pipeline.run_install()

    [(run_id, kind, status, checkpoint, stored)] = query(
        pipeline, "SELECT id, kind, status, checkpoint, summary FROM runs"
    )
    assert (run_id, kind, status) == (summary.run_id, "install", "finished")
    assert set(json.loads(checkpoint)["stages"]) == {"load", "index", "enrich", "stats", "check"}
    assert json.loads(stored)["sources"]["fake"]["new"] == 3


def test_install_fires_install_finished(tmp_path: Path, source: FakeSource) -> None:
    events, subscriptions = recorder()

    summary = make_pipeline(tmp_path, source, subscriptions=subscriptions).run_install()

    assert events == [InstallFinished(summary)]


def test_install_reports_progress(pipeline: Pipeline) -> None:
    reports: list[Progress] = []

    pipeline.run_install(reports.append)

    assert [r.stage for r in reports if r.done == 0] == [
        "load",
        "index",
        "enrich",
        "stats",
        "check",
        "swap",
    ]
    assert Progress("load", 3, 3, "trials") in reports


def test_install_writes_in_batches(tmp_path: Path, source: FakeSource) -> None:
    reports: list[Progress] = []

    make_pipeline(tmp_path, source, batch_size=2).run_install(reports.append)

    assert [r.done for r in reports if r.stage == "load" and r.done] == [2, 3]


def test_install_skips_studies_it_cant_read(tmp_path: Path) -> None:
    source = FakeSource(studies=(*STUDIES, b"{nope", fake_study("F4", broken=True)))
    pipeline = make_pipeline(tmp_path, source)

    summary = pipeline.run_install()

    assert sorted(titles(pipeline)) == ["F1", "F2", "F3"]
    assert summary.sources["fake"].failed == 2
    assert summary.failures[1] == "fake: ValueError: F4: this study is broken"


def test_install_normalizes_in_worker_processes(tmp_path: Path, source: FakeSource) -> None:
    pipeline = make_pipeline(tmp_path, source, workers=2)

    summary = pipeline.run_install()

    assert summary.sources["fake"].new == 3
    assert sorted(titles(pipeline)) == ["F1", "F2", "F3"]


def test_install_refuses_to_replace_a_database(installed: Pipeline) -> None:
    with pytest.raises(PipelineError, match="already exists"):
        installed.run_install()


def test_a_forced_install_rebuilds_and_bumps_the_data_version(
    installed: Pipeline, source: FakeSource
) -> None:
    rebuilt = replace(installed, sources=[replace(source, studies=STUDIES[:2])])

    summary = rebuilt.run_install(force=True)

    assert summary.data_version == 2
    assert sorted(titles(rebuilt)) == ["F1", "F2"]
    assert not rebuilt.new_db.exists()


def test_install_with_nothing_to_load_stops_before_the_swap(tmp_path: Path) -> None:
    pipeline = make_pipeline(tmp_path, FakeSource())

    with pytest.raises(PipelineError, match="loaded no trials"):
        pipeline.run_install()

    assert not pipeline.trials_db.exists()


def test_an_interrupted_install_resumes_where_it_stopped(
    tmp_path: Path, source: FakeSource
) -> None:
    pipeline = make_pipeline(tmp_path, source, batch_size=2)
    with pytest.raises(RuntimeError, match="stop at load"):
        pipeline.run_install(fail_at("load", after=1))  # after the first batch is written

    assert not pipeline.trials_db.exists()
    assert query_db(pipeline.new_db, "SELECT status FROM runs") == [("failed",)]

    summary = pipeline.run_install()

    counts = summary.sources["fake"]
    assert (counts.new, counts.unchanged) == (1, 2)
    assert summary.notes["resumed"] is True
    assert sorted(titles(pipeline)) == ["F1", "F2", "F3"]
    assert query(pipeline, "SELECT status FROM runs") == [("finished",)]


def test_a_resumed_install_skips_finished_stages(tmp_path: Path, source: FakeSource) -> None:
    pipeline = make_pipeline(tmp_path, source)
    with pytest.raises(RuntimeError, match="stop at check"):
        pipeline.run_install(fail_at("check"))
    reports: list[Progress] = []

    summary = pipeline.run_install(reports.append)

    assert [r.stage for r in reports if r.done == 0] == ["check", "swap"]
    assert summary.sources == {}
    assert sorted(titles(pipeline)) == ["F1", "F2", "F3"]


def test_a_failed_install_leaves_the_old_database_alone(
    installed: Pipeline, source: FakeSource
) -> None:
    rebuilt = replace(installed, sources=[replace(source, studies=STUDIES[:1])])

    with pytest.raises(RuntimeError, match="stop at check"):
        rebuilt.run_install(fail_at("check"), force=True)

    assert sorted(titles(installed)) == ["F1", "F2", "F3"]
    assert rebuilt.new_db.exists()


def test_install_starts_over_if_the_new_database_is_not_one(
    tmp_path: Path, source: FakeSource
) -> None:
    pipeline = make_pipeline(tmp_path, source)
    tmp_path.mkdir(exist_ok=True)
    pipeline.new_db.write_bytes(b"not a database")

    summary = pipeline.run_install()

    assert summary.sources["fake"].new == 3


def test_install_needs_a_source(tmp_path: Path) -> None:
    with pytest.raises(PipelineError, match="no source plugin"):
        Pipeline(data_dir=tmp_path, sources=[]).run_install()


def test_a_bulk_file_needs_exactly_one_source(tmp_path: Path) -> None:
    pipeline = Pipeline(data_dir=tmp_path, sources=[FakeSource(), FakeSource(name="other")])
    bulk = tmp_path / "bulk.zip"
    bulk.write_bytes(b"")

    with pytest.raises(PipelineError, match="exactly one source"):
        pipeline.run_install(from_file=bulk)


def test_the_bulk_file_reaches_the_source(tmp_path: Path) -> None:
    seen: list[FetchContext] = []

    class Recording(FakeSource):
        def fetch_all(self, ctx: FetchContext) -> Iterator[bytes]:
            seen.append(ctx)
            return super().fetch_all(ctx)

    bulk = tmp_path / "bulk.zip"
    bulk.write_bytes(b"")
    make_pipeline(tmp_path / "data", Recording(studies=STUDIES)).run_install(from_file=bulk)

    assert seen[0].from_file == bulk
    assert seen[0].downloads == tmp_path / "data" / "downloads"
    assert seen[0].reuse_download is False


# --- update ---------------------------------------------------------------------------------


def updated(pipeline: Pipeline, *changed: bytes, **fields: Any) -> Pipeline:
    """``pipeline`` with its source's API now returning ``changed``."""
    [source] = pipeline.sources
    assert isinstance(source, FakeSource)
    return replace(pipeline, sources=[replace(source, changed=changed)], **fields)


def test_update_before_install(pipeline: Pipeline) -> None:
    with pytest.raises(PipelineError, match="run `tri-al install` first"):
        pipeline.run_update()


def test_update_with_nothing_changed(installed: Pipeline) -> None:
    summary = updated(installed, *STUDIES).run_update()

    counts = summary.sources["fake"]
    # The cursor is 2026-10-15, so the update asks for studies updated since the 14th.
    assert (counts.fetched, counts.new, counts.updated, counts.unchanged) == (2, 0, 0, 2)
    assert summary.data_version == 1
    assert meta(installed) == {"data_version": "1", "cursor.fake": "2026-10-15"}
    assert summary.notes == {"fake": {"since": "2026-10-14"}}


def test_a_new_snapshot_of_an_unchanged_study_is_unchanged(installed: Pipeline) -> None:
    resent = fake_study("F3", "Lecanemab", updated="2026-10-15", countries=["US", "JP"])
    resent_later = resent.replace(b"2026-10-16", b"2026-10-19")

    summary = updated(installed, resent_later).run_update()

    assert summary.sources["fake"].unchanged == 1


def test_update_writes_new_and_changed_trials(installed: Pipeline) -> None:
    changed = fake_study(
        "F2", "Aducanumab", updated="2026-10-16", enrollment=120, conditions=["AD"]
    )
    new = fake_study("F4", "Remternetug", updated="2026-10-16")

    summary = updated(installed, changed, new, STUDIES[2]).run_update()

    counts = summary.sources["fake"]
    assert (counts.new, counts.updated, counts.unchanged) == (1, 1, 1)
    assert summary.data_version == 2
    assert meta(installed) == {"data_version": "2", "cursor.fake": "2026-10-16"}
    assert titles(installed)["F4"] == "Remternetug"
    assert set(summary.stages) == {"fetch", "write", "enrich", "stats", "commit"}


def test_update_logs_changes_to_tracked_fields(installed: Pipeline) -> None:
    changed = fake_study(
        "F2", "Aducanumab (EMERGE)", updated="2026-10-16", enrollment=120, conditions=["AD"]
    )

    summary = updated(installed, changed).run_update()

    rows = query(
        installed,
        "SELECT t.source_id, c.run_id, c.field, c.old, c.new FROM trial_changes AS c "
        "JOIN trials AS t ON t.id = c.trial_id ORDER BY c.id",
    )
    assert rows == [
        ("F2", summary.run_id, "title", '"Aducanumab"', '"Aducanumab (EMERGE)"'),
        ("F2", summary.run_id, "enrollment", "100", "120"),
    ]


def test_update_fires_events(installed: Pipeline) -> None:
    events, subscriptions = recorder()
    changed = fake_study("F2", "Aducanumab", updated="2026-10-16")
    new = fake_study("F4", "Remternetug", updated="2026-10-16")

    summary = updated(installed, changed, new, subscriptions=subscriptions).run_update()

    ids = dict(query(installed, "SELECT source_id, id FROM trials"))
    assert events == [
        UpdateStarted(summary.run_id),
        TrialsChanged(summary.run_id, (ids["F4"],), "new"),
        TrialsChanged(summary.run_id, (ids["F2"],), "updated"),
        UpdateFinished(summary),
    ]


def test_update_records_its_run(installed: Pipeline) -> None:
    summary = updated(installed, fake_study("F4", updated="2026-10-16")).run_update()

    [(kind, status, stored)] = query(
        installed, f"SELECT kind, status, summary FROM runs WHERE id = {summary.run_id}"
    )
    assert (kind, status) == ("update", "finished")
    assert json.loads(stored)["sources"]["fake"]["new"] == 1


def test_a_failed_update_writes_nothing(installed: Pipeline) -> None:
    good = fake_study("F4", updated="2026-10-16")
    bad = fake_study("F5", updated="2026-10-16", countries=["ZZ"])  # storage rejects it

    with pytest.raises(ValueError, match="unknown country codes"):
        updated(installed, good, bad).run_update()

    assert sorted(titles(installed)) == ["F1", "F2", "F3"]
    assert meta(installed)["data_version"] == "1"
    [(status, stored)] = query(installed, "SELECT status, summary FROM runs WHERE kind = 'update'")
    assert status == "failed"
    assert "unknown country codes" in json.loads(stored)["error"]


def test_a_failing_handler_doesnt_stop_the_update(installed: Pipeline) -> None:
    def broken(event: object) -> None:
        raise RuntimeError("handler bug")

    subscriptions = {"trials.changed": [Subscription("buggy", broken)]}
    new = fake_study("F4", updated="2026-10-16")

    summary = updated(installed, new, subscriptions=subscriptions).run_update()

    assert summary.sources["fake"].new == 1
    assert summary.handler_errors == [
        "buggy: trials.changed handler failed: RuntimeError('handler bug')"
    ]
    [(stored,)] = query(installed, f"SELECT summary FROM runs WHERE id = {summary.run_id}")
    assert json.loads(stored)["handler_errors"] == summary.handler_errors


def test_update_reports_progress(installed: Pipeline) -> None:
    reports: list[Progress] = []

    updated(installed, fake_study("F4", updated="2026-10-16")).run_update(reports.append)

    assert [r.stage for r in reports if r.done == 0] == [
        "fetch",
        "write",
        "enrich",
        "stats",
        "commit",
    ]


def test_update_needs_the_sources_cursor(installed: Pipeline) -> None:
    other = replace(installed, sources=[FakeSource(name="other")])

    with pytest.raises(PipelineError, match="no update cursor"):
        other.run_update()


def test_update_cursor_never_moves_back(installed: Pipeline) -> None:
    older = fake_study("F1", "Donepezil in mild AD (v2)", updated="2026-10-14")

    updated(installed, older).run_update()

    assert meta(installed)["cursor.fake"] == "2026-10-15"
    assert titles(installed)["F1"] == "Donepezil in mild AD (v2)"


def test_update_counts_failures(installed: Pipeline) -> None:
    summary = updated(installed, fake_study("F9", updated="2026-10-16", broken=True)).run_update()

    assert summary.sources["fake"].failed == 1
    assert summary.data_version == 1


def test_storage_errors_are_raised(installed: Pipeline) -> None:
    with SQLiteStorage.open(installed.trials_db) as storage, storage.engine.begin() as conn:
        conn.execute(text("INSERT INTO meta VALUES ('bulk_load_started', 'then')"))

    with pytest.raises(StorageError, match="bulk load"):
        updated(installed, fake_study("F4", updated="2026-10-16")).run_update()


def test_from_plugins_uses_what_plugins_registered(tmp_path: Path) -> None:
    from tri_al.config import Config
    from tri_al.plugins import LoadedPlugins

    plugins = LoadedPlugins()
    plugins.contributions.sources["fake"] = FakeSource()
    subscription = Subscription("p", print)
    plugins.contributions.subscriptions["update.finished"] = [subscription]

    pipeline = Pipeline.from_plugins(Config(), plugins, data_dir=tmp_path, workers=3)

    assert pipeline.sources == [FakeSource()]
    assert pipeline.subscriptions == {"update.finished": [subscription]}
    assert (pipeline.data_dir, pipeline.workers) == (tmp_path, 3)
    assert Pipeline.from_plugins(Config(), plugins).data_dir == Path("data")


def test_update_overlaps_the_cursor_by_a_day(installed: Pipeline) -> None:
    seen: list[date] = []

    class Recording(FakeSource):
        def fetch_changed(self, since: date, ctx: FetchContext) -> Iterator[bytes]:
            seen.append(since)
            return super().fetch_changed(since, ctx)

    replace(installed, sources=[Recording()]).run_update()

    assert seen == [date(2026, 10, 14)]


# --- renormalize ----------------------------------------------------------------------------


class _ReadsMore(FakeSource):
    """The fake source after it learned to read the design and arms of its studies."""

    def normalize(self, raw: dict[str, Any]) -> TrialRecord:
        return replace(
            super().normalize(raw),
            allocation="RANDOMIZED",
            arms=[Arm("Treatment", "EXPERIMENTAL", f"{raw['title']} for 12 weeks")],
        )


class _Retitles(FakeSource):
    def normalize(self, raw: dict[str, Any]) -> TrialRecord:
        return replace(super().normalize(raw), title=f"{raw['title']} (renamed)")


def test_renormalize_adds_new_fields_in_place(installed: Pipeline, tmp_path: Path) -> None:
    version = installed.current_data_version()
    before = query(installed, "SELECT id, ingested_at FROM trials ORDER BY id")
    pipeline = replace(installed, sources=[_ReadsMore(studies=STUDIES)])
    reports: list[Progress] = []

    summary = pipeline.run_renormalize(reports.append)

    assert (summary.trials, summary.rewritten, summary.unchanged, summary.replaced) == (3, 3, 0, 0)
    assert summary.data_version == version + 1
    assert reports[-1].stage == "stats"
    with SQLiteStorage.open(pipeline.trials_db) as storage:
        record = storage.find_trial("fake", "F3")
        assert record is not None
        assert record.allocation == "RANDOMIZED"
        assert record.arms == [Arm("Treatment", "EXPERIMENTAL", "Lecanemab for 12 weeks")]
        assert source_ids(storage.search("lecanemab").hits) == ["F3"]
    assert query(pipeline, "SELECT id, ingested_at FROM trials ORDER BY id") == before
    assert query(pipeline, "SELECT count(*) FROM trial_changes") == [(0,)]


def test_renormalize_again_finds_nothing_to_do(installed: Pipeline) -> None:
    pipeline = replace(installed, sources=[_ReadsMore(studies=STUDIES)])
    pipeline.run_renormalize()
    version = pipeline.current_data_version()

    summary = pipeline.run_renormalize()

    assert (summary.unchanged, summary.rewritten, summary.replaced) == (3, 0, 0)
    assert summary.data_version == version
    assert "stats" not in summary.stages


def test_renormalize_replaces_trials_whose_searchable_text_changed(installed: Pipeline) -> None:
    pipeline = replace(installed, sources=[_Retitles(studies=STUDIES)])

    summary = pipeline.run_renormalize()

    assert summary.replaced == 3
    assert titles(pipeline)["F2"] == "Aducanumab (renamed)"
    with SQLiteStorage.open(pipeline.trials_db) as storage:
        assert source_ids(storage.search("renamed aducanumab").hits) == ["F2"]
        record = storage.find_trial("fake", "F2")
        assert record is not None
        assert record.raw == STUDIES[1]


def test_renormalize_skips_other_sources_and_counts_failures(installed: Pipeline) -> None:
    class Breaks(FakeSource):
        def normalize(self, raw: dict[str, Any]) -> TrialRecord:
            if raw["id"] == "F2":
                raise ValueError("F2: can't read it")
            return super().normalize(raw)

    summary = replace(installed, sources=[Breaks(studies=STUDIES)]).run_renormalize()
    assert (summary.unchanged, summary.failed) == (2, 1)
    assert summary.failures == ["fake/F2: ValueError: F2: can't read it"]

    other = replace(installed, sources=[FakeSource(name="other")]).run_renormalize()
    assert (other.trials, other.skipped, other.unchanged) == (3, 3, 0)


def test_renormalize_needs_a_database(pipeline: Pipeline) -> None:
    with pytest.raises(PipelineError, match="tri-al install"):
        pipeline.run_renormalize()
