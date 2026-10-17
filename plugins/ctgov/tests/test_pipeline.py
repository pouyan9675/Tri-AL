"""Install and update end to end: the core pipeline with the ClinicalTrials.gov source, offline."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import orjson
import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from tri_al.cli import create_app
from tri_al.pipeline import Pipeline
from tri_al.storage import SQLiteStorage
from tri_al_ctgov import CtgovSource
from tri_al_ctgov.normalize import normalize

if TYPE_CHECKING:
    from tests.conftest import StudyLoader


def serving(*studies: dict[str, Any]) -> CtgovSource:
    """A source whose API answers every page request with ``studies``."""

    def answer(request: httpx.Request) -> httpx.Response:
        page = {"totalCount": len(studies), "studies": list(studies)}
        return httpx.Response(200, content=orjson.dumps(page))

    return CtgovSource(transport=httpx.MockTransport(answer), sleep=lambda _: None)


def new_release(study: dict[str, Any], **status: Any) -> dict[str, Any]:
    """``study`` as the next data release shows it, with ``status`` module changes."""
    changed = copy.deepcopy(study)
    changed["derivedSection"]["miscInfoModule"]["versionHolder"] = "2026-10-19"
    changed["protocolSection"]["statusModule"].update(status)
    return changed


@pytest.fixture
def installed(tmp_path: Path, bulk_zip: Path) -> Pipeline:
    pipeline = Pipeline(data_dir=tmp_path / "data", sources=[CtgovSource()], workers=0)
    pipeline.run_install(from_file=bulk_zip)
    return pipeline


def query(pipeline: Pipeline, sql: str) -> list[tuple[Any, ...]]:
    with SQLiteStorage.open(pipeline.trials_db) as storage, storage.engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql))]


def test_install_from_the_bulk_file(installed: Pipeline, samples: list[bytes]) -> None:
    with SQLiteStorage.open(installed.trials_db) as storage:
        assert storage.count_trials() == 6
        for raw in samples:
            expected = normalize(orjson.loads(raw))
            stored = storage.find_trial("ctgov", expected.source_id)
            assert stored is not None
            assert stored.raw == raw
            assert stored.title == expected.title
            assert stored.locations == expected.locations
        assert [hit.source_id for hit in storage.search("donanemab")] == ["NCT05026866"]
        assert [hit.name for hit in storage.lookup_names("florbeta")] == ["florbetapir (18F)"]
    meta = dict(query(installed, "SELECT key, value FROM meta"))
    assert meta == {"data_version": "1", "cursor.ctgov": "2026-07-29"}


def test_trials_get_ids_in_nct_order(installed: Pipeline) -> None:
    rows = query(installed, "SELECT source_id FROM trials ORDER BY id")

    assert [source_id for (source_id,) in rows] == sorted(source_id for (source_id,) in rows)


def test_an_update_skips_studies_that_only_have_a_new_release_date(
    installed: Pipeline, load_study: StudyLoader
) -> None:
    source = serving(new_release(load_study("NCT01662882")))

    summary = Pipeline(data_dir=installed.data_dir, sources=[source]).run_update()

    counts = summary.sources["ctgov"]
    assert (counts.fetched, counts.new, counts.updated, counts.unchanged) == (1, 0, 0, 1)
    assert summary.data_version == 1


def test_an_update_writes_changes_and_logs_them(
    installed: Pipeline, load_study: StudyLoader
) -> None:
    changed = new_release(
        load_study("NCT05026866"),
        overallStatus="COMPLETED",
        lastUpdatePostDateStruct={"date": "2026-10-17", "type": "ACTUAL"},
    )
    added = new_release(load_study("NCT01662882"))
    added["protocolSection"]["identificationModule"]["nctId"] = "NCT09999999"
    source = serving(changed, added)

    summary = Pipeline(data_dir=installed.data_dir, sources=[source]).run_update()

    counts = summary.sources["ctgov"]
    assert (counts.new, counts.updated, counts.unchanged) == (1, 1, 0)
    assert summary.data_version == 2
    assert summary.notes["ctgov"] == {"since": "2026-07-28", "data_date": "2026-10-19", "pages": 1}
    changes = query(
        installed,
        "SELECT t.source_id, c.field, c.old, c.new FROM trial_changes AS c "
        "JOIN trials AS t ON t.id = c.trial_id",
    )
    assert changes == [("NCT05026866", "status", '"ACTIVE_NOT_RECRUITING"', '"COMPLETED"')]
    meta = dict(query(installed, "SELECT key, value FROM meta"))
    assert meta == {"data_version": "2", "cursor.ctgov": "2026-10-17"}


def test_the_cli_installs_from_a_file(
    bulk_zip: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    for var in [var for var in os.environ if var.startswith("TRI_AL_")]:
        monkeypatch.delenv(var)

    result = CliRunner().invoke(
        create_app(), ["install", "--from-file", str(bulk_zip), "--workers", "0"]
    )

    assert result.exit_code == 0, result.output
    assert "load: 6 of 6 trials (100%)" in result.stdout
    assert "ctgov: 6 fetched, 6 new, 0 updated, 0 unchanged, 0 failed" in result.stdout
    assert (tmp_path / "data" / "trials.db").exists()
