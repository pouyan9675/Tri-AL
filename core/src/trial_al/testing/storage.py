"""The storage contract suite (docs/design.md §5.6 and §11).

Every storage backend must pass it. Subclass ``StorageContract`` in a test module and
override the ``storage`` fixture to yield a new, empty, migrated storage:

    class TestMyStorage(StorageContract):
        @pytest.fixture
        def storage(self, tmp_path: Path) -> Iterator[Storage]:
            with MyStorage.open(tmp_path / "trials.db") as storage:
                yield storage
"""

from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol

import pytest

from trial_al.schema import Intervention, Location, MeshTerm, Outcome, Sponsor, TrialRecord
from trial_al.storage import Storage, StorageError, TrialQuery, TrialSummary
from trial_al.testing.fixtures import (
    completed_behavioral_trial,
    minimal_trial,
    other_registry_trial,
    phase3_trial,
    sample_trials,
)


def as_stored(record: TrialRecord, stored: TrialRecord | None) -> TrialRecord:
    """``record`` as storage should return it: with the id and ingested_at it was given."""
    assert stored is not None, f"{record.source_id} wasn't stored"
    assert stored.ingested_at is not None
    assert stored.ingested_at.tzinfo is not None
    return replace(record, id=stored.id, ingested_at=stored.ingested_at)


def assert_round_trips(
    storage: Storage, records: Sequence[TrialRecord], ids: Sequence[int]
) -> None:
    for record, trial_id in zip(records, ids, strict=True):
        stored = storage.get_trial(trial_id)
        assert stored == as_stored(record, stored)
        assert stored is not None
        assert stored.id == trial_id


class _HasSourceId(Protocol):
    @property
    def source_id(self) -> str: ...


def source_ids(items: Iterable[_HasSourceId]) -> list[str]:
    return [item.source_id for item in items]


class StorageContract:
    @pytest.fixture
    def storage(self) -> Storage:
        raise NotImplementedError("override the storage fixture")

    @pytest.fixture
    def ids(self, storage: Storage) -> list[int]:
        """The ids of ``sample_trials()``, stored."""
        return storage.upsert_batch(sample_trials())

    # --- writing and reading ----------------------------------------------------------------

    def test_new_trials_get_ids_and_round_trip(self, storage: Storage) -> None:
        records = sample_trials()

        ids = storage.upsert_batch(records)

        assert len(set(ids)) == len(records)
        assert_round_trips(storage, records, ids)

    def test_storage_sets_id_and_ingested_at(self, storage: Storage) -> None:
        then = datetime(2000, 1, 1, tzinfo=UTC)
        record = replace(minimal_trial(), id=12345, ingested_at=then)
        before = datetime.now(UTC)

        [trial_id] = storage.upsert_batch([record])

        stored = storage.get_trial(trial_id)
        assert stored is not None
        assert stored.id == trial_id
        assert stored.ingested_at is not None
        assert stored.ingested_at >= before

    def test_get_trial_returns_none_for_unknown_ids(self, storage: Storage, ids: list[int]) -> None:
        assert storage.get_trial(max(ids) + 1) is None

    def test_find_trial_by_source_and_source_id(self, storage: Storage, ids: list[int]) -> None:
        found = storage.find_trial("ctgov", "NCT90000002")

        assert found is not None
        assert found.id == ids[1]
        assert storage.find_trial("ctgov", "NCT00000000") is None
        assert storage.find_trial("isrctn", "NCT90000002") is None

    def test_source_ids_belong_to_their_source(self, storage: Storage) -> None:
        records = [minimal_trial(), replace(minimal_trial(), source="isrctn", title="Other")]

        ids = storage.upsert_batch(records)

        assert ids[0] != ids[1]
        assert_round_trips(storage, records, ids)

    def test_upsert_replaces_an_existing_trial(self, storage: Storage, ids: list[int]) -> None:
        changed = replace(
            phase3_trial(),
            title="Remternetug in Early Alzheimer's Disease",
            status="ACTIVE_NOT_RECRUITING",
            enrollment=1795,
            enrollment_type="ACTUAL",
            healthy_volunteers=None,
            description=None,
            outcomes=[Outcome("primary", "Change from baseline in iADRS")],
            conditions=["Alzheimer Disease"],
            mesh_terms=[MeshTerm("D000544", "Alzheimer Disease", "condition")],
            interventions=[Intervention("Remternetug", "BIOLOGICAL")],
            sponsors=[Sponsor("Tri-AL Test Pharma", "lead", "INDUSTRY")],
            countries=["US"],
            locations=[],
            raw=None,
            content_hash=None,
        )

        assert storage.upsert_batch([changed]) == [ids[0]]

        assert_round_trips(storage, [changed, completed_behavioral_trial()], ids[:2])
        assert storage.count_trials() == len(ids)

    def test_upsert_returns_ids_in_input_order(self, storage: Storage) -> None:
        first, second, third = phase3_trial(), completed_behavioral_trial(), minimal_trial()
        ids = storage.upsert_batch([first, second])

        again = storage.upsert_batch([third, replace(second, title="Renamed"), first])

        assert again[1:] == [ids[1], ids[0]]
        assert again[0] not in ids

    def test_empty_batch(self, storage: Storage) -> None:
        assert storage.upsert_batch([]) == []

    def test_upsert_rejects_two_records_for_one_trial(self, storage: Storage) -> None:
        with pytest.raises(ValueError, match="more than one record"):
            storage.upsert_batch([minimal_trial(), completed_behavioral_trial(), minimal_trial()])

        assert storage.count_trials() == 0

    @pytest.mark.parametrize(
        "record",
        [
            replace(minimal_trial(), countries=["US", "XX"]),
            replace(minimal_trial(), locations=[Location(city="Atlantis", country_code="ZZ")]),
        ],
        ids=["country", "location"],
    )
    def test_upsert_rejects_unknown_country_codes(
        self, storage: Storage, record: TrialRecord
    ) -> None:
        with pytest.raises(ValueError, match="unknown country codes"):
            storage.upsert_batch([phase3_trial(), record])

        assert storage.count_trials() == 0

    def test_repeated_list_items_keep_the_first(self, storage: Storage) -> None:
        record = replace(
            minimal_trial(),
            conditions=["Aging", "Dementia", "Aging"],
            mesh_terms=[
                MeshTerm("D003704", "Dementia", "condition"),
                MeshTerm("D003704", "Dementia", "condition", ancestor=True),
                MeshTerm("D003704", "Dementia", "intervention"),
            ],
            interventions=[
                Intervention("Placebo", "DRUG", ("Sugar pill", "Dummy", "Sugar pill")),
                Intervention("Placebo", "OTHER"),
            ],
            sponsors=[
                Sponsor("Tri-AL Test Pharma", "lead", "INDUSTRY"),
                Sponsor("Tri-AL Test Pharma", "collaborator", "INDUSTRY"),
            ],
            countries=["DE", "FR", "DE"],
        )

        [trial_id] = storage.upsert_batch([record])

        expected = replace(
            record,
            conditions=["Aging", "Dementia"],
            mesh_terms=[record.mesh_terms[0], record.mesh_terms[2]],
            interventions=[Intervention("Placebo", "DRUG", ("Sugar pill", "Dummy"))],
            sponsors=[record.sponsors[0]],
            countries=["DE", "FR"],
        )
        assert_round_trips(storage, [expected], [trial_id])

    def test_trials_share_conditions_and_sponsors(self, storage: Storage, ids: list[int]) -> None:
        assert [hit.name for hit in storage.lookup_names("Alzheimer", kind="condition")] == [
            "Alzheimer Disease"
        ]
        assert [hit.name for hit in storage.lookup_names("Institute on Aging")] == [
            "National Institute on Aging (NIA)"
        ]

    def test_a_mesh_code_has_the_latest_term(self, storage: Storage) -> None:
        renamed = MeshTerm("D000544", "Alzheimer's Disease", "condition")
        first, second = phase3_trial(), replace(minimal_trial(), mesh_terms=[renamed])

        ids = storage.upsert_batch([first])
        ids += storage.upsert_batch([second])

        stored = storage.get_trial(ids[0])
        assert stored is not None
        assert stored.mesh_terms[0] == renamed

    # --- queries ----------------------------------------------------------------------------

    def test_query_trials_lists_every_trial_in_id_order(
        self, storage: Storage, ids: list[int]
    ) -> None:
        summaries = storage.query_trials()

        assert [summary.id for summary in summaries] == sorted(ids)
        trial = phase3_trial()
        assert summaries[0] == TrialSummary(
            ids[0],
            trial.source,
            trial.source_id,
            trial.title,
            trial.status,
            trial.phase,
            trial.start_date,
            trial.last_update,
            trial.enrollment,
        )

    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            (TrialQuery(status=("RECRUITING",)), ["NCT90000001"]),
            (TrialQuery(status=("COMPLETED", "WITHDRAWN")), ["NCT90000002", "ISRCTN00000001"]),
            (TrialQuery(phase=("PHASE2_PHASE3",)), ["NCT90000002"]),
            (TrialQuery(phase=("PHASE3", "NA")), ["NCT90000001", "ISRCTN00000001"]),
            (TrialQuery(status=("COMPLETED",), phase=("PHASE2_PHASE3",)), ["NCT90000002"]),
            (TrialQuery(status=("RECRUITING",), phase=("PHASE2_PHASE3",)), []),
            (TrialQuery(status=()), []),
        ],
    )
    def test_query_trials_filters_by_status_and_phase(
        self, storage: Storage, ids: list[int], query: TrialQuery, expected: list[str]
    ) -> None:
        assert source_ids(storage.query_trials(query)) == expected
        assert storage.count_trials(query) == len(expected)

    def test_query_trials_pages_with_after_id(self, storage: Storage, ids: list[int]) -> None:
        first = storage.query_trials(TrialQuery(limit=3))
        second = storage.query_trials(TrialQuery(limit=3, after_id=first[-1].id))

        assert [summary.id for summary in first + second] == sorted(ids)
        assert storage.query_trials(TrialQuery(after_id=max(ids))) == []
        assert storage.count_trials(TrialQuery(limit=1, after_id=max(ids))) == len(ids)

    # --- full-text search -------------------------------------------------------------------

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Remternetug", "NCT90000001"),  # title
            ("double-blind", "NCT90000001"),  # official title
            ("mild cognitive impairment", "NCT90000001"),  # condition
            ("placebo", "NCT90000001"),  # intervention
            ("TAL-0451", "NCT90000001"),  # other name
            ("monthly infusions", "NCT90000001"),  # summary
            ("plaque clearance", "NCT90000001"),  # description
            ("MMSE", "NCT90000001"),  # eligibility
            ("CDR-SB", "NCT90000001"),  # outcome measure
            ("sum of boxes", "NCT90000001"),  # outcome description
            ("treadmill", "NCT90000002"),
            ("agitation", "ISRCTN00000001"),
            ("cafe", "NCT90000003"),  # accents are ignored
        ],
    )
    def test_search_finds_every_field(
        self, storage: Storage, ids: list[int], text: str, expected: str
    ) -> None:
        assert source_ids(storage.search(text)) == [expected]

    @pytest.mark.parametrize("text", ["infusion", "INFUSED", "randomizing"])
    def test_search_matches_other_forms_of_a_word(
        self, storage: Storage, ids: list[int], text: str
    ) -> None:
        assert source_ids(storage.search(text)) == ["NCT90000001"]

    def test_search_needs_every_word(self, storage: Storage, ids: list[int]) -> None:
        assert storage.search("amyloid treadmill") == []
        assert source_ids(storage.search("amyloid remternetug")) == ["NCT90000001"]

    def test_search_hits_identify_the_trial(self, storage: Storage, ids: list[int]) -> None:
        [hit] = storage.search("remternetug")

        trial = phase3_trial()
        assert (hit.id, hit.source, hit.source_id, hit.title) == (
            ids[0],
            trial.source,
            trial.source_id,
            trial.title,
        )

    def test_search_ranks_title_matches_first(self, storage: Storage) -> None:
        in_description = replace(
            minimal_trial(), source_id="NCT1", description="Exploratory zebrafish model."
        )
        in_title = replace(minimal_trial(), source_id="NCT2", title="Zebrafish models of tau")
        storage.upsert_batch([in_description, in_title])

        hits = storage.search("zebrafish")

        assert source_ids(hits) == ["NCT2", "NCT1"]
        assert hits[0].score > hits[1].score

    def test_search_limit(self, storage: Storage, ids: list[int]) -> None:
        assert len(storage.search("alzheimer")) == 2
        assert len(storage.search("alzheimer", limit=1)) == 1
        assert storage.search("alzheimer", limit=0) == []

    def test_search_follows_updates(self, storage: Storage, ids: list[int]) -> None:
        changed = replace(
            phase3_trial(),
            brief_summary="Enrollment closed early.",
            interventions=[Intervention("Lecanemab", "DRUG")],
        )

        storage.upsert_batch([changed])

        assert storage.search("infusions") == []
        assert storage.search("TAL-0451") == []
        assert source_ids(storage.search("enrollment closed")) == ["NCT90000001"]
        assert source_ids(storage.search("lecanemab")) == ["NCT90000001"]

    @pytest.mark.parametrize(
        "text",
        ['"', "NOT", "AND OR", "remternetug*", "(plaques", "title:x", "-", "^", "", "   "],
    )
    def test_search_treats_query_syntax_as_text(
        self, storage: Storage, ids: list[int], text: str
    ) -> None:
        assert isinstance(storage.search(text), list)

    def test_search_reads_quoted_words(self, storage: Storage, ids: list[int]) -> None:
        assert source_ids(storage.search('"remternetug')) == ["NCT90000001"]

    # --- name lookup ------------------------------------------------------------------------

    def test_lookup_names_matches_inside_names(self, storage: Storage, ids: list[int]) -> None:
        [hit] = storage.lookup_names("zheim")

        assert (hit.kind, hit.name) == ("condition", "Alzheimer Disease")

    def test_lookup_names_by_kind(self, storage: Storage, ids: list[int]) -> None:
        assert storage.lookup_names("placebo", kind="condition") == []
        assert [hit.kind for hit in storage.lookup_names("placebo", kind="intervention")] == [
            "intervention"
        ]

    def test_lookup_names_ignores_case_and_accents(self, storage: Storage, ids: list[int]) -> None:
        assert [hit.name for hit in storage.lookup_names("UNIVERSITE lyon")] == [
            "Université Claude Bernard Lyon 1"
        ]

    def test_lookup_names_puts_shorter_names_first(self, storage: Storage, ids: list[int]) -> None:
        hits = storage.lookup_names("aging")

        assert [(hit.kind, hit.name) for hit in hits] == [
            ("condition", "Aging"),
            ("sponsor", "National Institute on Aging (NIA)"),
        ]

    def test_lookup_names_short_text_matches_starts(self, storage: Storage, ids: list[int]) -> None:
        assert [hit.name for hit in storage.lookup_names("ag")] == ["Aging", "Agitation"]
        assert storage.lookup_names("%") == []
        assert storage.lookup_names("") == []

    def test_lookup_names_finds_new_names(self, storage: Storage, ids: list[int]) -> None:
        storage.upsert_batch([replace(minimal_trial(), conditions=["Frontotemporal Dementia"])])

        assert [hit.name for hit in storage.lookup_names("temporal")] == ["Frontotemporal Dementia"]

    # --- transactions -----------------------------------------------------------------------

    def test_transaction_commits_together(self, storage: Storage) -> None:
        with storage.transaction() as tx:
            ids = tx.upsert_batch([phase3_trial()])
            ids += tx.upsert_batch([minimal_trial()])
            assert tx.get_trial(ids[0]) == as_stored(phase3_trial(), tx.get_trial(ids[0]))
            found = tx.find_trial("ctgov", "NCT90000003")
            assert found is not None
            assert found.id == ids[1]

        assert_round_trips(storage, [phase3_trial(), minimal_trial()], ids)

    def test_transaction_rolls_back_on_error(self, storage: Storage) -> None:
        def write_then_fail() -> None:
            with storage.transaction() as tx:
                tx.upsert_batch(sample_trials())
                raise RuntimeError("stop")

        with pytest.raises(RuntimeError, match="stop"):
            write_then_fail()

        assert storage.count_trials() == 0
        assert storage.search("remternetug") == []
        assert storage.lookup_names("alzheimer") == []

    # --- bulk loads -------------------------------------------------------------------------

    def test_bulk_load_round_trips_and_indexes(self, storage: Storage) -> None:
        records = sample_trials()

        with storage.bulk_load() as load:
            ids = load.upsert_batch(records[:2]) + load.upsert_batch(records[2:])

        assert_round_trips(storage, records, ids)
        assert source_ids(storage.search("remternetug")) == ["NCT90000001"]
        assert [hit.name for hit in storage.lookup_names("zheim")] == ["Alzheimer Disease"]
        assert storage.count_trials(TrialQuery(status=("RECRUITING",))) == 1

    def test_bulk_load_replaces_existing_trials(self, storage: Storage, ids: list[int]) -> None:
        changed = replace(phase3_trial(), title="Renamed", brief_summary="Nothing to see.")

        with storage.bulk_load() as load:
            assert load.upsert_batch([changed]) == [ids[0]]

        assert_round_trips(storage, [changed], [ids[0]])
        assert storage.search("infusions") == []
        assert source_ids(storage.search("renamed")) == ["NCT90000001"]
        assert source_ids(storage.search("treadmill")) == ["NCT90000002"]

    def test_writes_after_a_bulk_load(self, storage: Storage) -> None:
        with storage.bulk_load() as load:
            load.upsert_batch([phase3_trial()])

        storage.upsert_batch([completed_behavioral_trial(), replace(phase3_trial(), title="New")])

        assert source_ids(storage.search("treadmill")) == ["NCT90000002"]
        assert source_ids(storage.search("new")) == ["NCT90000001"]
        assert storage.search("TRAIL") == []

    def test_a_rejected_bulk_batch_writes_nothing(self, storage: Storage) -> None:
        with storage.bulk_load() as load:
            with pytest.raises(ValueError, match="unknown country codes"):
                load.upsert_batch([phase3_trial(), replace(minimal_trial(), countries=["XX"])])
            load.upsert_batch([other_registry_trial()])

        assert source_ids(storage.query_trials()) == ["ISRCTN00000001"]
        assert storage.lookup_names("remternetug") == []

    def test_an_unfinished_bulk_load_blocks_writes(self, storage: Storage) -> None:
        def load_then_fail() -> None:
            with storage.bulk_load() as load:
                load.upsert_batch([phase3_trial()])
                raise RuntimeError("stop")

        with pytest.raises(RuntimeError, match="stop"):
            load_then_fail()

        with pytest.raises(StorageError, match="bulk load"):
            storage.upsert_batch([minimal_trial()])

        with storage.bulk_load() as load:
            load.upsert_batch([minimal_trial()])
        storage.upsert_batch([other_registry_trial()])
        assert source_ids(storage.search("remternetug")) == ["NCT90000001"]
        assert storage.count_trials() == 3
