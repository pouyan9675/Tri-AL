from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tri_al.api import create_app
from tri_al.api import models as m
from tri_al.config import Config
from tri_al.filters import TrialFilter
from tri_al.linking import Links, linked_trials
from tri_al.plugins import LoadedPlugins
from tri_al.plugins.registry import Contributions
from tri_al.schema import MeshTerm, TrialRecord
from tri_al.storage import SQLiteStorage
from tri_al.testing.fixtures import minimal_trial

AD = MeshTerm("D000544", "Alzheimer Disease", "condition")
MCI = MeshTerm("D060825", "Cognitive Dysfunction", "condition")
DEMENTIA = MeshTerm("D003704", "Dementia", "condition", ancestor=True)
DONANEMAB = MeshTerm("C000729112", "donanemab", "intervention")


def trial(source_id: str, phase: str | None, start: str | None, *terms: MeshTerm) -> TrialRecord:
    return replace(
        minimal_trial(),
        source_id=source_id,
        title=f"Trial {source_id}",
        phase=phase,
        start_date=None if start is None else date.fromisoformat(start),
        mesh_terms=list(terms),
    )


TRIALS = [
    trial("NCT1", "PHASE3", "2020-06-01", AD, MCI, DONANEMAB),  # the one linked from
    trial("NCT2", "PHASE2", "2018-01-01", AD, DONANEMAB),
    trial("NCT3", "PHASE3", "2023-01-01", MCI, DONANEMAB),
    trial("NCT4", "PHASE3", "2021-01-01", AD, MCI, DONANEMAB),
    trial("NCT5", "PHASE1", "2016-01-01", AD),  # no intervention in common
    trial("NCT6", "PHASE2", "2019-01-01", DONANEMAB),  # no condition in common
    trial("NCT7", None, None, DEMENTIA, DONANEMAB),  # only an ancestor in common
    trial("NCT8", None, "2024-01-01", AD, DONANEMAB),
    trial("NCT9", "PHASE3", "2022-01-01"),  # no terms at all
]


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[SQLiteStorage]:
    with SQLiteStorage.open(tmp_path / "data" / "trials.db") as storage:
        storage.upsert_batch(TRIALS)
        yield storage


def links(
    storage: SQLiteStorage,
    source_id: str = "NCT1",
    *,
    terms: list[str] | None = None,
    filter: TrialFilter | None = None,
    limit: int = 100,
) -> Links:
    with storage.read() as reader:
        [(_, trial_id)] = reader.find_ids(source_id)
        return linked_trials(reader, trial_id, terms=terms, filter=filter, limit=limit)


def listed(found: Links) -> list[tuple[str | None, int, list[str]]]:
    return [
        (group.phase, group.total, [linked.trial.source_id for linked in group.trials])
        for group in found.phases
    ]


def test_trials_sharing_a_condition_and_an_intervention_by_phase(
    storage: SQLiteStorage,
) -> None:
    found = links(storage)
    assert found.total == 4
    # Phases in order, no phase last; most terms shared first, then the newest start.
    assert listed(found) == [
        ("PHASE2", 1, ["NCT2"]),
        ("PHASE3", 2, ["NCT4", "NCT3"]),
        (None, 1, ["NCT8"]),
    ]
    assert found.phases[1].trials[0].shared == ("D000544", "D060825", "C000729112")
    assert [(term.code, term.selected, term.trials) for term in found.terms] == [
        ("D000544", True, 3),
        ("D060825", True, 2),
        ("C000729112", True, 4),
    ]


def test_link_by_some_terms(storage: SQLiteStorage) -> None:
    found = links(storage, terms=["D000544", "C000729112"])
    assert listed(found) == [("PHASE2", 1, ["NCT2"]), ("PHASE3", 1, ["NCT4"]), (None, 1, ["NCT8"])]
    assert [(term.code, term.selected) for term in found.terms] == [
        ("D000544", True),
        ("D060825", False),
        ("C000729112", True),
    ]
    # With no intervention chosen, a condition is enough.
    by_condition = links(storage, terms=["D000544"])
    assert [trial for _, _, trials in listed(by_condition) for trial in trials] == [
        "NCT5",
        "NCT2",
        "NCT4",
        "NCT8",
    ]


def test_filter_and_limit(storage: SQLiteStorage) -> None:
    assert listed(links(storage, filter=TrialFilter(phase=("PHASE3",)))) == [
        ("PHASE3", 2, ["NCT4", "NCT3"])
    ]
    assert listed(links(storage, limit=1))[1] == ("PHASE3", 2, ["NCT4"])


def test_nothing_to_link_by(storage: SQLiteStorage) -> None:
    assert links(storage, "NCT9") == Links(terms=[])
    found = links(storage, terms=["D999999"])
    assert found.total == 0
    assert not any(term.selected for term in found.terms)


def test_the_linked_trials_endpoint(storage: SQLiteStorage, tmp_path: Path) -> None:
    config = Config.model_validate({"data": {"dir": str(tmp_path / "data")}})
    loaded = LoadedPlugins(plugins=[], settings={}, contributions=Contributions())
    app = create_app(config, loaded, config_file=tmp_path / "tri-al.toml", use_index=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.get(
            "/api/trials/NCT1/linked",
            params={"terms": ["D000544", "C000729112"], "phase": "PHASE3"},
        )
        assert response.status_code == 200, response.text
        out = m.LinkedTrialsOut.model_validate(response.json())
        assert out.trial.source_id == "NCT1"
        assert out.total == 1
        assert [(g.phase, [t.trial.source_id for t in g.trials]) for g in out.phases] == [
            ("PHASE3", ["NCT4"])
        ]
        assert out.phases[0].trials[0].shared == ["D000544", "C000729112"]
        assert client.get("/api/trials/NCT404/linked").status_code == 404
        assert client.get("/api/trials/NCT1/linked", params={"limit": 0}).status_code == 422
