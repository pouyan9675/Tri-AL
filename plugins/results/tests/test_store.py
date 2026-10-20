"""The plugin's tables and the charts that read them, on made-up studies with results."""

import hashlib
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import orjson
import pytest
from sqlalchemy import func, select, update

from tri_al.filters import TrialFilter
from tri_al.schema import TrialRecord
from tri_al.stats import ChartContext, Rows, SqlCounts
from tri_al.storage import SQLiteStorage
from tri_al_results import store
from tri_al_results.charts import (
    charts,
    composition,
    dropouts,
    organ_systems,
    people,
    race_by_phase,
    race_by_year,
    race_reporting,
    representation,
    safety,
    serious_by_phase,
    signals,
    top_serious,
)
from tri_al_results.parse import ETHNICITY, RACE
from tri_al_results.store import build_results

RACE_NAMES = {
    "white": "White",
    "black": "Black or African American",
    "asian": "Asian",
    "unknown": "Unknown or Not Reported",
}
ETHNICITY_NAMES = {"hispanic": "Hispanic or Latino", "not_hispanic": "Not Hispanic or Latino"}


def study(
    *,
    races: dict[str, int] | None = None,
    ethnicities: dict[str, int] | None = None,
    custom: bool = False,
    female: int = 60,
    male: int = 40,
    drug: tuple[int, int, int] = (50, 5, 1),  # at risk, serious, deaths
    placebo: tuple[int, int, int] | None = (50, 2, 0),
    events: tuple[tuple[str, bool, str, int, int], ...] = (
        ("Nausea", True, "Gastrointestinal disorders", 20, 2),
    ),
    started: int = 100,
    completed: int = 90,
    left: dict[str, int] | None = None,
) -> dict[str, Any]:
    """A ClinicalTrials.gov study with results: a drug arm, and a placebo arm unless None."""

    def total(counts: dict[str, int], names: dict[str, str], title: str) -> dict[str, Any]:
        return {
            "title": title,
            "paramType": "COUNT_OF_PARTICIPANTS",
            "classes": [
                {
                    "categories": [
                        {
                            "title": names[key],
                            "measurements": [{"groupId": "BG002", "value": str(n)}],
                        }
                        for key, n in counts.items()
                    ]
                }
            ],
        }

    races = {"white": 80, "black": 20} if races is None else races
    ethnicities = {"hispanic": 10, "not_hispanic": 90} if ethnicities is None else ethnicities
    measures = [
        total(
            {"female": female, "male": male},
            {"female": "Female", "male": "Male"},
            "Sex: Female, Male",
        )
    ]
    if custom:
        measures.append(total({"white": 1}, {"white": "Caucasian"}, "Race/Ethnicity, Customized"))
    else:
        measures.append(total(races, RACE_NAMES, "Race (NIH/OMB)"))
        measures.append(total(ethnicities, ETHNICITY_NAMES, "Ethnicity (NIH/OMB)"))
    arms = [("EG000", "Drug", drug)] + ([("EG001", "Placebo", placebo)] if placebo else [])
    return {
        "protocolSection": {
            "armsInterventionsModule": {
                "armGroups": [
                    {"label": "Drug", "type": "EXPERIMENTAL"},
                    {"label": "Placebo", "type": "PLACEBO_COMPARATOR"},
                ]
            }
        },
        "resultsSection": {
            "participantFlowModule": {
                "groups": [{"id": "FG000", "title": "Everyone"}],
                "periods": [
                    {
                        "title": "Overall Study",
                        "milestones": [
                            {
                                "type": "STARTED",
                                "achievements": [{"groupId": "FG000", "numSubjects": str(started)}],
                            },
                            {
                                "type": "COMPLETED",
                                "achievements": [
                                    {"groupId": "FG000", "numSubjects": str(completed)}
                                ],
                            },
                        ],
                        "dropWithdraws": [
                            {
                                "type": reason,
                                "reasons": [{"groupId": "FG000", "numSubjects": str(n)}],
                            }
                            for reason, n in (
                                left or {"Adverse Event": 6, "Withdrawal by Subject": 4}
                            ).items()
                        ],
                    }
                ],
            },
            "baselineCharacteristicsModule": {
                "groups": [
                    {"id": "BG000", "title": "Drug"},
                    {"id": "BG001", "title": "Placebo"},
                    {"id": "BG002", "title": "Total"},
                ],
                "denoms": [
                    {
                        "units": "Participants",
                        "counts": [{"groupId": "BG002", "value": str(female + male)}],
                    }
                ],
                "measures": measures,
            },
            "adverseEventsModule": {
                "frequencyThreshold": "0",
                "eventGroups": [
                    {
                        "id": group_id,
                        "title": title,
                        "seriousNumAtRisk": at_risk,
                        "seriousNumAffected": serious,
                        "deathsNumAtRisk": at_risk,
                        "deathsNumAffected": deaths,
                        "otherNumAtRisk": at_risk,
                        "otherNumAffected": 0,
                    }
                    for group_id, title, (at_risk, serious, deaths) in arms
                ],
                "seriousEvents" if True else "": [
                    {
                        "term": term,
                        "organSystem": organ,
                        "stats": [
                            {"groupId": "EG000", "numAffected": on_drug, "numAtRisk": drug[0]},
                            *(
                                [
                                    {
                                        "groupId": "EG001",
                                        "numAffected": on_placebo,
                                        "numAtRisk": placebo[0],
                                    }
                                ]
                                if placebo
                                else []
                            ),
                        ],
                    }
                    for term, serious, organ, on_drug, on_placebo in events
                    if serious
                ],
                "otherEvents": [
                    {
                        "term": term,
                        "organSystem": organ,
                        "stats": [
                            {"groupId": "EG000", "numAffected": on_drug, "numAtRisk": drug[0]}
                        ],
                    }
                    for term, serious, organ, on_drug, _ in events
                    if not serious
                ],
            },
        },
    }


def record(
    source_id: str,
    raw: dict[str, Any],
    *,
    phase: str | None = "PHASE3",
    start: date | None = date(2020, 1, 1),
    posted: date | None = date(2021, 6, 1),
    has_results: bool = True,
) -> TrialRecord:
    blob = orjson.dumps(raw)
    return TrialRecord(
        source="ctgov",
        source_id=source_id,
        title=f"Trial {source_id}",
        phase=phase,
        start_date=start,
        results_first_posted=posted,
        has_results=has_results,
        raw=blob,
        content_hash=hashlib.blake2b(blob, digest_size=16).digest(),
    )


def trials() -> list[TrialRecord]:
    """Six phase 3 trials alike, and a phase 2 trial with its own race categories."""
    return [
        *(record(f"NCT0000000{i}", study()) for i in range(6)),
        record(
            "NCT00000009",
            study(custom=True, placebo=None, events=()),
            phase="PHASE2",
            start=date(2019, 1, 1),
            posted=date(2020, 1, 1),
        ),
    ]


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[SQLiteStorage]:
    with SQLiteStorage.open(
        tmp_path / "trials.db", plugin_migrations={"results": store.MIGRATIONS}
    ) as storage:
        yield storage


def build(storage: SQLiteStorage) -> None:
    with storage.transaction() as tx:
        build_results(tx.connection, 1)


def chart(storage: SQLiteStorage, query: Any, filter: TrialFilter | None = None) -> Rows:
    with storage.read() as reader:
        conn = reader.connection
        ctx = ChartContext(conn, lambda f: SqlCounts(conn, f))
        rows: Rows = query(ctx, filter or TrialFilter())
        return rows


def count(storage: SQLiteStorage, table: Any) -> int:
    with storage.read() as reader:
        return int(reader.connection.execute(select(func.count()).select_from(table)).scalar_one())


def test_the_tables_hold_each_trials_numbers(storage: SQLiteStorage) -> None:
    ids = storage.upsert_batch(trials())
    build(storage)

    with storage.read() as reader:
        row = reader.connection.execute(
            select(store.trials).where(store.trials.c.trial_id == ids[0])
        ).one()
        custom = reader.connection.execute(
            select(store.trials.c.race, store.trials.c.ae_groups).where(
                store.trials.c.trial_id == ids[-1]
            )
        ).one()
    assert (row.participants, row.race, row.ethnicity, row.female, row.male) == (
        100,
        "standard",
        "standard",
        60,
        40,
    )
    assert (row.ae_groups, row.placebo_groups, row.at_risk, row.serious, row.deaths) == (
        2,
        1,
        100,
        7,
        1,
    )
    assert tuple(custom) == ("custom", 1)
    assert count(storage, store.demographics) == 6 * 4  # two races, two ethnicities
    assert count(storage, store.dropouts) == 7 * 2
    assert count(storage, store.events) == 6
    assert count(storage, store.terms) == 1


def test_only_changed_trials_are_read_again(storage: SQLiteStorage) -> None:
    ids = storage.upsert_batch(trials())
    build(storage)
    with storage.transaction() as tx:  # marks what a rebuild would overwrite
        tx.connection.execute(update(store.trials).values(participants=-1))

    build(storage)
    changed = record("NCT00000000", study(female=10, male=10))
    gone = record("NCT00000001", study(), has_results=False)
    storage.upsert_batch([changed, gone])
    build(storage)

    with storage.read() as reader:
        stored = dict(
            reader.connection.execute(
                select(store.trials.c.trial_id, store.trials.c.participants)
            ).all()
        )
    assert stored[ids[0]] == 20
    assert ids[1] not in stored
    assert stored[ids[2]] == -1  # unchanged, so not read again
    assert count(storage, store.events) == 5


def test_a_new_parser_version_reads_everything_again(
    storage: SQLiteStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage.upsert_batch(trials())
    build(storage)
    with storage.transaction() as tx:
        tx.connection.execute(update(store.trials).values(participants=-1))

    monkeypatch.setattr(store, "VERSION", store.VERSION + 1)
    build(storage)

    with storage.read() as reader:
        values = reader.connection.execute(select(store.trials.c.participants)).scalars().all()
    assert -1 not in values


def test_who_took_part(storage: SQLiteStorage) -> None:
    storage.upsert_batch(trials())
    build(storage)

    tiles = {row["key"]: row for row in chart(storage, people)}
    assert tiles["trials"]["value"] == 7
    assert tiles["participants"]["value"] == 6 * 100 + 100
    assert tiles["women"] == {"key": "women", "label": "Women", "value": 0.6, "format": "percent"}
    assert tiles["completed"]["value"] == pytest.approx(0.9)

    race = {row["key"]: row for row in chart(storage, composition("race", RACE))}
    assert race["black"]["participants"] == pytest.approx(0.2)
    assert race["black"]["average"] == pytest.approx(0.2)
    assert "other" not in race  # shown only when some trial has it
    assert chart(storage, composition("ethnicity", ETHNICITY))[0]["participants"] == 0.1

    assert chart(storage, race_reporting) == [
        {"year": "2020", "standard": 0, "custom": 1, "not_collected": 0, "none": 0},
        {"year": "2021", "standard": 6, "custom": 0, "not_collected": 0, "none": 0},
    ]
    (year,) = chart(storage, race_by_year)
    assert (year["year"], year["trials"]) == ("2020", 6)
    assert (year["black"], year["asian"], year["hispanic"]) == pytest.approx((0.2, 0, 0.1))
    by_phase = chart(storage, race_by_phase)
    assert [row["phase"] for row in by_phase] == ["Phase 3"]  # phase 2 has too few trials
    assert by_phase[0]["white"] == pytest.approx(0.8)
    no_one = {row["key"]: row["value"] for row in chart(storage, representation)}
    assert no_one == {"black": 0.0, "asian": 1.0, "aian": 1.0, "nhpi": 1.0, "hispanic": 0.0}


def test_the_average_trial_counts_each_trial_once(storage: SQLiteStorage) -> None:
    storage.upsert_batch(
        [
            record("NCT00000001", study(races={"white": 900, "black": 100}, female=500, male=500)),
            record("NCT00000002", study(races={"white": 5, "black": 5}, female=5, male=5)),
        ]
    )
    build(storage)

    black = next(row for row in chart(storage, composition("race", RACE)) if row["key"] == "black")
    assert black["participants"] == pytest.approx(105 / 1010)
    assert black["average"] == pytest.approx((0.1 + 0.5) / 2)
    assert black["count"] == 105


def test_safety(storage: SQLiteStorage) -> None:
    storage.upsert_batch(trials())
    build(storage)

    tiles = {row["key"]: row["value"] for row in chart(storage, safety)}
    assert tiles["trials"] == 7
    assert tiles["at_risk"] == 6 * 100 + 50
    assert tiles["serious"] == pytest.approx((6 * 7 + 5) / 650)
    assert tiles["deaths"] == pytest.approx(7 / 650)
    assert tiles["left"] == pytest.approx(0.06)

    assert chart(storage, serious_by_phase) == [
        {"key": "PHASE3", "label": "Phase 3", "serious": 0.07, "deaths": 0.01, "trials": 6}
    ]
    assert chart(storage, organ_systems) == [
        {"key": 7, "label": "Gastrointestinal", "value": pytest.approx(6 * 22 / 650)}
    ]
    assert chart(storage, top_serious(5)) == [
        {
            "event": "Nausea",
            "organ": "Gastrointestinal",
            "trials": 6,
            "participants": 6 * 22,
            "rate": pytest.approx(6 * 22 / 650),
        }
    ]
    left = {row["key"]: row["value"] for row in chart(storage, dropouts)}
    assert left == {"adverse_event": pytest.approx(0.06), "withdrawal": pytest.approx(0.04)}


def test_signals_pool_placebo_controlled_trials(storage: SQLiteStorage) -> None:
    storage.upsert_batch(trials())
    build(storage)

    (nausea,) = chart(storage, signals)

    assert (nausea["label"], nausea["detail"], nausea["trials"]) == ("Nausea", "Serious", 6)
    assert nausea["ratio"] == pytest.approx(10)
    assert nausea["low"] < 10 < nausea["high"]
    assert nausea["low"] > 1
    assert (nausea["active"], nausea["placebo"]) == (0.4, 0.04)
    assert nausea["q"] < 0.001


def test_rare_or_even_events_are_not_signals(storage: SQLiteStorage) -> None:
    even = study(events=(("Headache", True, "Nervous system disorders", 5, 5),))
    rare = study(events=(("Rash", True, "Skin and subcutaneous tissue disorders", 2, 0),))
    storage.upsert_batch(
        [*(record(f"NCT1000000{i}", even) for i in range(4)), record("NCT20000000", rare)]
    )
    build(storage)

    assert chart(storage, signals) == []


def test_charts_follow_the_filter(storage: SQLiteStorage) -> None:
    storage.upsert_batch(trials())
    build(storage)
    phase2 = TrialFilter(phase=("PHASE2",))

    assert {row["key"]: row["value"] for row in chart(storage, people, phase2)}["trials"] == 1
    assert chart(storage, composition("race", RACE), phase2) == []
    assert chart(storage, signals, phase2) == []
    assert chart(storage, organ_systems, phase2) == []
    assert {row["key"]: row["value"] for row in chart(storage, safety, phase2)}["at_risk"] == 50


def test_charts_with_no_results_at_all(storage: SQLiteStorage) -> None:
    build(storage)

    for spec in charts():
        rows = chart(storage, spec.query)
        if spec.widget == "stat":
            assert rows[0]["value"] == 0
        else:
            assert rows == [], spec.id


def test_an_event_takes_the_organ_system_most_trials_give(storage: SQLiteStorage) -> None:
    def fall(organ: str) -> dict[str, Any]:
        return study(events=(("Fall", True, organ, 2, 1),))

    storage.upsert_batch(
        [
            record("NCT00000001", fall("Nervous system disorders")),
            record("NCT00000002", fall("Injury, poisoning and procedural complications")),
            record("NCT00000003", fall("Injury, poisoning and procedural complications")),
        ]
    )
    build(storage)

    (row,) = chart(storage, top_serious(5))
    assert (row["event"], row["organ"], row["trials"]) == (
        "Fall",
        "Injury, poisoning and procedural",
        3,
    )
