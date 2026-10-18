from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from tri_al.filters import TrialFilter
from tri_al.plugins import Registry
from tri_al.plugins.registry import Contributions
from tri_al.stats import ChartContext, Rows, SqlCounts, TrialIndex
from tri_al.storage import SQLiteReader, SQLiteStorage
from tri_al.testing.fixtures import minimal_trial, sample_trials
from tri_al_charts import Settings, charts, plugin


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[SQLiteStorage]:
    with SQLiteStorage.open(tmp_path / "trials.db") as storage:
        storage.upsert_batch(
            [
                *sample_trials(),
                replace(minimal_trial(), source_id="NCT5", last_update=date(2026, 9, 29)),
            ]
        )
        yield storage


def run(reader: SQLiteReader, chart_id: str, filter: TrialFilter, *, index: bool) -> Rows:
    [chart] = [chart for chart in charts(Settings(top=3)) if chart.id == chart_id]
    conn = reader.connection
    if index:
        built = TrialIndex.build(conn, reader.data_version())
        ctx = ChartContext(conn, lambda f: built.counts(conn, built.mask(conn, f)))
    else:
        ctx = ChartContext(conn, lambda f: SqlCounts(conn, f))
    return chart.query(ctx, filter)


def test_registers_every_chart() -> None:
    contributions = Contributions()

    plugin.register(Registry("charts", Settings(), contributions))

    assert list(contributions.charts) == [
        "totals",
        "trials_by_country",
        "top_countries",
        "trials_by_phase",
        "trials_by_status",
        "top_conditions",
        "recent_updates",
    ]
    assert {chart.plugin for chart in contributions.charts.values()} == {"charts"}


@pytest.mark.parametrize("index", [False, True], ids=["sql", "index"])
def test_totals(storage: SQLiteStorage, index: bool) -> None:
    with storage.read() as reader:
        rows = run(reader, "totals", TrialFilter(), index=index)
        alzheimer = run(
            reader, "totals", TrialFilter(conditions=("Alzheimer Disease",)), index=index
        )

    assert rows == [
        {"key": "trials", "label": "Trials", "value": 5},
        {"key": "interventions", "label": "Interventions", "value": 4},
        {"key": "drugs", "label": "Drugs", "value": 2},
        {"key": "conditions", "label": "Conditions", "value": 4},
        {"key": "countries", "label": "Countries", "value": 5},
    ]
    assert [row["value"] for row in alzheimer] == [2, 3, 2, 3, 3]


@pytest.mark.parametrize("index", [False, True], ids=["sql", "index"])
def test_phases_in_order_then_none(storage: SQLiteStorage, index: bool) -> None:
    with storage.read() as reader:
        rows = run(reader, "trials_by_phase", TrialFilter(), index=index)

    assert [(r["key"], r["value"]) for r in rows] == [
        ("EARLY_PHASE1", 0),
        ("PHASE1", 0),
        ("PHASE1_PHASE2", 0),
        ("PHASE2", 0),
        ("PHASE2_PHASE3", 1),
        ("PHASE3", 1),
        ("PHASE4", 0),
        ("NA", 1),
        (None, 2),
    ]


@pytest.mark.parametrize("index", [False, True], ids=["sql", "index"])
def test_top_conditions_and_countries(storage: SQLiteStorage, index: bool) -> None:
    with storage.read() as reader:
        conditions = run(reader, "top_conditions", TrialFilter(), index=index)
        countries = run(reader, "trials_by_country", TrialFilter(), index=index)

    assert conditions == [
        {"key": "Alzheimer Disease", "label": "Alzheimer Disease", "value": 2},
        # Ties go to the condition stored first; a batch stores new names in name order.
        {"key": "Aging", "label": "Aging", "value": 1},
        {"key": "Agitation", "label": "Agitation", "value": 1},
    ]
    assert [row["code"] for row in countries] == ["CA", "DE", "FR", "GB", "US"]
    assert countries[0] == {"code": "CA", "label": "Canada", "value": 1}


@pytest.mark.parametrize("index", [False, True], ids=["sql", "index"])
def test_recent_updates_cover_the_last_days_of_data(storage: SQLiteStorage, index: bool) -> None:
    with storage.read() as reader:
        rows = run(reader, "recent_updates", TrialFilter(), index=index)
        filtered = run(reader, "recent_updates", TrialFilter(status=("RECRUITING",)), index=index)

    assert len(rows) == 30
    assert rows[-1] == {"date": "2026-09-30", "value": 1}
    assert rows[-2] == {"date": "2026-09-29", "value": 1}
    assert rows[0]["date"] == "2026-09-01"
    assert [row["value"] for row in filtered][-2:] == [0, 1]


@pytest.mark.parametrize("index", [False, True], ids=["sql", "index"])
def test_status_most_trials_first(storage: SQLiteStorage, index: bool) -> None:
    with storage.read() as reader:
        rows = run(reader, "trials_by_status", TrialFilter(), index=index)

    assert [(r["key"], r["label"], r["value"]) for r in rows] == [
        (None, "Not given", 2),
        ("COMPLETED", "Completed", 1),
        ("RECRUITING", "Recruiting", 1),
        ("WITHDRAWN", "Withdrawn", 1),
    ]
