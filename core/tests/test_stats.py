import random
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import orjson
import pytest
from sqlalchemy import text

from tri_al.filters import DateRange, IntRange, TrialFilter
from tri_al.pipeline import Pipeline
from tri_al.schema import Intervention, MeshTerm, Sponsor, TrialRecord
from tri_al.stats import (
    CORE_FACETS,
    Chart,
    ChartContext,
    Rows,
    SqlCounts,
    StatsEngine,
    TrialIndex,
    UnknownChart,
    precompute,
)
from tri_al.stats.engine import ResultCache
from tri_al.storage import SORT_KEYS, Sort, SQLiteStorage
from tri_al.testing import FakeSource, fake_study

STATUSES = ["RECRUITING", "COMPLETED", "TERMINATED", "WITHDRAWN", None]
PHASES = ["PHASE1", "PHASE2", "PHASE3", "PHASE2_PHASE3", "NA", None]
CONDITIONS = ["Alzheimer Disease", "Dementia", "Aging", "Sleep", "Depression", "Pain"]
COUNTRIES = ["US", "DE", "FR", "JP", "BR", "CA"]
TYPES = ["DRUG", "BEHAVIORAL", "DEVICE", None]


def varied(count: int, seed: int = 7) -> list[TrialRecord]:
    """Trials with every filterable field spread out, missing values included."""
    rng = random.Random(seed)

    def maybe_date() -> date | None:
        return (
            None if rng.random() < 0.15 else date(2015, 1, 1) + timedelta(days=rng.randrange(4000))
        )

    records = []
    for i in range(count):
        drugs = rng.sample(
            ["Donepezil", "Placebo", "Lecanemab", "Walking", "Music"], rng.randrange(3)
        )
        records.append(
            TrialRecord(
                source="ctgov",
                source_id=f"NCT{i:08d}",
                title=f"Trial {i} of "
                + " ".join(rng.sample(["memory", "sleep", "tau", "pain"], 2)),
                status=rng.choice(STATUSES),
                phase=rng.choice(PHASES),
                study_type=rng.choice(["INTERVENTIONAL", "OBSERVATIONAL", None]),
                start_date=maybe_date(),
                completion_date=maybe_date(),
                first_posted=maybe_date(),
                last_update=maybe_date(),
                enrollment=None if rng.random() < 0.1 else rng.randrange(2000),
                has_results=rng.random() < 0.3,
                conditions=rng.sample(CONDITIONS, rng.randrange(1, 3)),
                mesh_terms=[MeshTerm("D003704", "Dementia", "condition", ancestor=True)]
                if rng.random() < 0.3
                else [],
                interventions=[Intervention(name, rng.choice(TYPES)) for name in drugs],
                sponsors=[
                    Sponsor(
                        rng.choice(["Pharma A", "NIA", "Uni B"]),
                        "lead",
                        rng.choice(["INDUSTRY", "NIH", None]),
                    )
                ],
                countries=rng.sample(COUNTRIES, rng.randrange(3)),
            )
        )
    return records


FILTERS = [
    TrialFilter(),
    TrialFilter(status=("COMPLETED",)),
    TrialFilter(status=("RECRUITING", "TERMINATED"), phase=("PHASE3",)),
    TrialFilter(study_type=("OBSERVATIONAL",)),
    TrialFilter(conditions=("Alzheimer Disease", "Sleep")),
    TrialFilter(conditions=("Nobody has this",)),
    TrialFilter(mesh=("D003704",)),
    TrialFilter(interventions=("Donepezil",)),
    TrialFilter(intervention_types=("DRUG",)),
    TrialFilter(sponsors=("NIA",), sponsor_class=("NIH",)),
    TrialFilter(countries=("US", "JP")),
    TrialFilter(countries=("ZZ",)),
    TrialFilter(start=DateRange.parse("2018..2020")),
    TrialFilter(completion=DateRange.parse("2021..")),
    TrialFilter(first_posted=DateRange.parse("..2016")),
    TrialFilter(last_update=DateRange.parse("2019-06")),
    TrialFilter(enrollment=IntRange.parse("100..900")),
    TrialFilter(has_results=True),
    TrialFilter(q="memory"),
    TrialFilter(q="memory tau", status=("COMPLETED",), countries=("DE",)),
    TrialFilter(phase=("NOT_A_PHASE",)),
]


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SQLiteStorage]:
    path = tmp_path_factory.mktemp("stats") / "trials.db"
    with SQLiteStorage.open(path) as storage:
        storage.upsert_batch(varied(400))
        yield storage


@pytest.fixture(scope="module")
def index(storage: SQLiteStorage) -> TrialIndex:
    with storage.read() as reader:
        return TrialIndex.build(reader.connection, reader.data_version())


def answers(counts: Any) -> dict[str, Any]:
    return {
        "total": counts.total(),
        **{
            f"by {field}": counts.by(field)
            for field in ("status", "phase", "study_type", "sponsor_class", "has_results")
        },
        **{
            f"top {d}": counts.top(d, 4)
            for d in ("conditions", "interventions", "sponsors", "countries")
        },
        "types": counts.intervention_types(),
        **{
            f"distinct {d}": counts.distinct(d)
            for d in ("conditions", "interventions", "sponsors", "countries")
        },
        "drugs": counts.distinct("interventions", intervention_type="DRUG"),
        "latest": counts.latest("last_update"),
        "per day": counts.per_day("start_date", date(2016, 1, 1), date(2018, 12, 31)),
    }


@pytest.mark.parametrize("filter", FILTERS, ids=lambda f: "+".join(f.active) or "all")
def test_the_index_counts_like_sqlite(
    storage: SQLiteStorage, index: TrialIndex, filter: TrialFilter
) -> None:
    with storage.read() as reader:
        conn = reader.connection
        from_index = answers(index.counts(conn, index.mask(conn, filter)))
        from_sql = answers(SqlCounts(conn, filter))

    assert from_index == from_sql
    assert from_index["total"] == storage.count_trials(filter)


@pytest.mark.parametrize("sort", [*SORT_KEYS, *(f"-{key}" for key in SORT_KEYS)])
@pytest.mark.parametrize(
    "filter",
    [TrialFilter(), TrialFilter(status=("COMPLETED",)), TrialFilter(countries=("FR",))],
    ids=["all", "completed", "france"],
)
def test_the_index_pages_like_sqlite(
    storage: SQLiteStorage, index: TrialIndex, sort: str, filter: TrialFilter
) -> None:
    order = Sort.parse(sort)
    with storage.read() as reader:
        mask = index.mask(reader.connection, filter)
        whole = [s.id for s in reader.query_trials(filter, sort=order, limit=1000).items]
        assert index.page(mask, order, None, 1000) == (whole, None)
        paged: list[int] = []
        after = None
        while True:
            ids, from_index = index.page(mask, order, after, 37)
            page = reader.query_trials(filter, sort=order, after=after, limit=37)
            assert ids == [s.id for s in page.items]
            assert from_index == page.next
            paged += ids
            if from_index is None:
                break
            after = from_index
    assert paged == whole


def test_the_index_size(index: TrialIndex) -> None:
    assert index.trials == 400
    assert 0 < index.nbytes < 200_000


# --- precomputing -------------------------------------------------------------------------


def broken(ctx: ChartContext, filter: TrialFilter) -> Rows:
    raise RuntimeError("bad chart")


def totals(ctx: ChartContext, filter: TrialFilter) -> Rows:
    return [{"label": "Trials", "value": ctx.counts(filter).total()}]


CHARTS = [
    Chart(id="totals", title="Totals", widget="stat", query=totals),
    Chart(id="broken", title="Broken", widget="bar", query=broken),
    Chart(id="live", title="Live", widget="bar", query=totals, precompute=False),
]


def stored(storage: SQLiteStorage) -> dict[str, tuple[int, Any]]:
    with storage.engine.connect() as conn:
        rows = conn.execute(text("SELECT chart_id, data_version, payload FROM stats"))
        return {chart_id: (version, orjson.loads(payload)) for chart_id, version, payload in rows}


def test_precompute_stores_charts_and_facets(tmp_path: Path) -> None:
    with SQLiteStorage.open(tmp_path / "trials.db") as storage:
        storage.upsert_batch(varied(20))
        with storage.engine.begin() as conn:
            errors = precompute(conn, CHARTS, CORE_FACETS, 4)

        rows = stored(storage)
    assert errors == ["broken: RuntimeError('bad chart')"]
    assert set(rows) == {"totals"} | {f"facet:{facet.field}" for facet in CORE_FACETS}
    assert rows["totals"] == (4, [{"label": "Trials", "value": 20}])
    version, statuses = rows["facet:status"]
    assert version == 4
    assert sum(item["count"] for item in statuses) == 20
    assert {"value", "label", "count"} == set(statuses[0])


def test_install_and_update_precompute(tmp_path: Path) -> None:
    source = FakeSource(
        studies=(fake_study("F1", status="RECRUITING", conditions=["AD"]),),
        changed=(fake_study("F2", updated="2026-10-03", status="COMPLETED"),),
    )
    pipeline = Pipeline(data_dir=tmp_path / "data", sources=[source], workers=0, charts=CHARTS[:1])
    pipeline.run_install()
    with SQLiteStorage.open(pipeline.trials_db) as storage:
        assert stored(storage)["totals"] == (1, [{"label": "Trials", "value": 1}])

    summary = pipeline.run_update()

    assert summary.data_version == 2
    assert "stats" in summary.stages
    with SQLiteStorage.open(pipeline.trials_db) as storage:
        assert stored(storage)["totals"] == (2, [{"label": "Trials", "value": 2}])
    again = pipeline.run_update()  # nothing changed: the stats are current
    assert again.data_version == 2
    assert "stats" not in again.stages


def test_an_update_fills_missing_stats(tmp_path: Path) -> None:
    source = FakeSource(studies=(fake_study("F1"),))
    pipeline = Pipeline(data_dir=tmp_path / "data", sources=[source], workers=0)
    pipeline.run_install()
    with SQLiteStorage.open(pipeline.trials_db) as storage, storage.engine.begin() as conn:
        conn.execute(text("DELETE FROM stats"))

    summary = pipeline.run_update()

    assert "stats" in summary.stages
    with SQLiteStorage.open(pipeline.trials_db) as storage:
        assert "facet:status" in stored(storage)


# --- serving ------------------------------------------------------------------------------


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[StatsEngine]:
    with SQLiteStorage.open(tmp_path / "trials.db") as storage:
        storage.upsert_batch(varied(60))
        with storage.engine.begin() as conn:
            precompute(conn, CHARTS, CORE_FACETS, 0)
        engine = StatsEngine(storage, CHARTS, CORE_FACETS)
        yield engine
        engine.close()


@pytest.mark.parametrize("use_index", [False, True], ids=["sql", "index"])
def test_charts_precomputed_computed_then_cached(engine: StatsEngine, use_index: bool) -> None:
    engine.use_index = use_index
    with engine.storage.read() as reader:
        if use_index:
            engine.wait_for_index(reader.data_version())
        plain = engine.chart(reader, "totals", TrialFilter())
        filtered = engine.chart(reader, "totals", TrialFilter(status=("COMPLETED",)))
        again = engine.chart(reader, "totals", TrialFilter(status=("COMPLETED",)))
        live = engine.chart(reader, "live", TrialFilter())
        with pytest.raises(UnknownChart):
            engine.chart(reader, "nope", TrialFilter())

    assert (plain.source, plain.filtered) == ("precomputed", False)
    assert orjson.loads(plain.rows) == [{"label": "Trials", "value": 60}]
    assert (filtered.source, filtered.filtered, again.source) == ("computed", True, "cached")
    assert orjson.loads(again.rows) == orjson.loads(filtered.rows)
    assert live.source == "computed"


def test_a_new_data_version_empties_the_cache(engine: StatsEngine) -> None:
    filter = TrialFilter(status=("COMPLETED",))
    with engine.storage.read() as reader:
        engine.chart(reader, "totals", filter)
    with engine.storage.engine.begin() as conn:
        conn.execute(text("UPDATE meta SET value = '5' WHERE key = 'data_version'"))

    with engine.storage.read() as reader:
        assert engine.chart(reader, "totals", filter).source == "computed"
        # The stored chart is for version 0, so it isn't used for version 5 either.
        assert engine.chart(reader, "totals", TrialFilter()).source == "computed"


@pytest.mark.parametrize("use_index", [False, True], ids=["sql", "index"])
def test_a_facet_ignores_its_own_field(engine: StatsEngine, use_index: bool) -> None:
    engine.use_index = use_index
    filter = TrialFilter(status=("COMPLETED",), phase=("PHASE3",))
    with engine.storage.read() as reader:
        if use_index:
            engine.wait_for_index(reader.data_version())
        facets = engine.facet_counts(reader, ["status", "phase", "countries"], filter, 50)
        plain = engine.facet_counts(reader, ["status"], TrialFilter(), 3)

    by_phase_only = engine.storage.count_trials(TrialFilter(phase=("PHASE3",)))
    assert sum(item["count"] for item in facets["status"]) == by_phase_only
    completed = next(item for item in facets["status"] if item["value"] == "COMPLETED")
    assert completed["count"] == engine.storage.count_trials(filter)
    assert sum(item["count"] for item in facets["phase"]) == engine.storage.count_trials(
        TrialFilter(status=("COMPLETED",))
    )
    assert len(plain["status"]) == 3  # from the precomputed facet, cut to the limit


def test_trial_pages_from_the_index(engine: StatsEngine) -> None:
    filter = TrialFilter(countries=("US",))
    with engine.storage.read() as reader:
        engine.wait_for_index(reader.data_version())
        page = engine.trial_page(reader, filter, sort=Sort(), after=None, limit=10)
        expected = reader.query_trials(filter, sort=Sort(), limit=10)

    assert page == expected


def test_the_result_cache_is_bounded_by_bytes() -> None:
    cache = ResultCache(max_bytes=1000)

    for i in range(10):
        cache.get_or_make(i, lambda: b"x" * 200)

    assert len(cache) == 3  # 3 x (200 + 64 overhead) fits in 1000
    assert cache.get_or_make(9, lambda: b"new") == b"x" * 200
    assert cache.hits == 1
    cache.get_or_make("big", lambda: np.zeros(2000, np.bool_))
    assert "big" not in cache._items  # too big to keep


def test_the_index_skips_ids_beyond_it(index: TrialIndex) -> None:
    mask = index._ids_mask([1, 2, 10**6])

    assert mask.sum() == 2


def test_changed_trials_get_a_new_index(tmp_path: Path) -> None:
    with SQLiteStorage.open(tmp_path / "trials.db") as storage:
        storage.upsert_batch(varied(5))
        engine = StatsEngine(storage)
        with storage.read() as reader:
            first = engine.wait_for_index(reader.data_version())
        storage.upsert_batch([replace(varied(1)[0], source_id="NEW")])
        with storage.engine.begin() as conn:
            conn.execute(text("UPDATE meta SET value = '1' WHERE key = 'data_version'"))
        with storage.read() as reader:
            assert engine.index_for(1) is None  # building
            second = engine.wait_for_index(1)
        engine.close()
    assert first is not None
    assert second is not None
    assert (first.trials, second.trials, second.data_version) == (5, 6, 1)
