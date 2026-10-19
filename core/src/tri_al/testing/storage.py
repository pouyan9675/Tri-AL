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
from datetime import UTC, date, datetime
from typing import Protocol

import pytest

from tri_al.filters import DateRange, IntRange, TrialFilter
from tri_al.schema import Arm, Intervention, Location, MeshTerm, Outcome, Sponsor, TrialRecord
from tri_al.storage import Sort, Storage, StorageError, TrialSummary
from tri_al.testing.fixtures import (
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


def hashed(records: Iterable[TrialRecord]) -> list[TrialRecord]:
    """``records``, each with a different content hash."""
    return [replace(record, content_hash=f"hash {i}".encode()) for i, record in enumerate(records)]


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

    def test_raw_documents_round_trip_exactly(self, storage: Storage) -> None:
        raw = '{ "title": "Köln \\u00f6",\n  "n": 2.50 }'.encode()

        [trial_id] = storage.upsert_batch([replace(minimal_trial(), raw=raw)])

        stored = storage.get_trial(trial_id)
        assert stored is not None
        assert stored.raw == raw

    # --- content hashes ---------------------------------------------------------------------

    def test_content_hashes_by_source(self, storage: Storage) -> None:
        records = hashed(sample_trials())
        storage.upsert_batch(records)
        ctgov = {r.source_id: r.content_hash for r in records if r.source == "ctgov"}

        assert storage.content_hashes("ctgov") == ctgov
        assert storage.content_hashes("isrctn") == {"ISRCTN00000001": records[-1].content_hash}
        assert storage.content_hashes("nobody") == {}

    def test_content_hashes_of_listed_trials(self, storage: Storage) -> None:
        records = hashed(sample_trials())
        storage.upsert_batch(
            [*records, replace(minimal_trial(), source_id="NCT1", content_hash=None)]
        )

        found = storage.content_hashes("ctgov", ["NCT90000002", "NCT1", "NCT404", "ISRCTN00000001"])

        assert found == {"NCT90000002": records[1].content_hash, "NCT1": None}

    def test_content_hashes_follow_writes(self, storage: Storage) -> None:
        [record] = hashed([phase3_trial()])
        with storage.transaction() as tx:
            tx.upsert_batch([record])
            assert tx.content_hashes("ctgov") == {"NCT90000001": record.content_hash}
            assert storage.content_hashes("ctgov") == {}  # not committed yet

        with storage.bulk_load() as load:
            load.upsert_batch([replace(record, content_hash=b"new")])
            assert load.content_hashes("ctgov", ["NCT90000001"]) == {"NCT90000001": b"new"}

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

    def test_query_trials_lists_every_trial(self, storage: Storage, ids: list[int]) -> None:
        page = storage.query_trials(sort=Sort("id", descending=False))

        assert [summary.id for summary in page.items] == sorted(ids)
        assert page.next is None
        trial = phase3_trial()
        assert page.items[0] == TrialSummary(
            ids[0],
            trial.source,
            trial.source_id,
            trial.title,
            trial.status,
            trial.phase,
            trial.study_type,
            trial.start_date,
            trial.completion_date,
            trial.last_update,
            trial.enrollment,
            trial.has_results,
            trial.num_sites,
            "Tri-AL Test Pharma",
            ("Alzheimer Disease", "Mild Cognitive Impairment"),
        )

    @pytest.mark.parametrize(
        ("filter", "expected"),
        [
            (TrialFilter(), ["NCT90000001", "NCT90000002", "NCT90000003", "ISRCTN00000001"]),
            (TrialFilter(status=("RECRUITING",)), ["NCT90000001"]),
            (TrialFilter(status=("COMPLETED", "WITHDRAWN")), ["NCT90000002", "ISRCTN00000001"]),
            (TrialFilter(phase=("PHASE2_PHASE3",)), ["NCT90000002"]),
            (TrialFilter(phase=("PHASE3", "NA")), ["NCT90000001", "ISRCTN00000001"]),
            (TrialFilter(status=("COMPLETED",), phase=("PHASE2_PHASE3",)), ["NCT90000002"]),
            (TrialFilter(status=("RECRUITING",), phase=("PHASE2_PHASE3",)), []),
            (
                TrialFilter(study_type=("INTERVENTIONAL",)),
                ["NCT90000001", "NCT90000002", "ISRCTN00000001"],
            ),
            (TrialFilter(conditions=("Alzheimer Disease",)), ["NCT90000001", "NCT90000002"]),
            (TrialFilter(conditions=("Aging", "Agitation")), ["NCT90000002", "ISRCTN00000001"]),
            (TrialFilter(mesh=("D003704",)), ["NCT90000001"]),  # an ancestor term
            (TrialFilter(interventions=("Placebo",)), ["NCT90000001"]),
            (TrialFilter(intervention_types=("BEHAVIORAL",)), ["NCT90000002", "ISRCTN00000001"]),
            (
                TrialFilter(sponsors=("National Institute on Aging (NIA)",)),
                ["NCT90000001", "NCT90000002"],
            ),
            (TrialFilter(sponsor_class=("NIH",)), ["NCT90000002"]),
            (TrialFilter(countries=("de",)), ["NCT90000001"]),
            (TrialFilter(countries=("FR", "CA")), ["NCT90000001", "ISRCTN00000001"]),
            (TrialFilter(start=DateRange.parse("2024")), ["NCT90000001"]),
            (TrialFilter(start=DateRange.parse("..2020-01")), ["NCT90000002"]),
            (
                TrialFilter(completion=DateRange(since=date(2023, 4, 1))),
                ["NCT90000001", "NCT90000002"],
            ),
            (TrialFilter(first_posted=DateRange.parse("2019-08..2019-08")), ["NCT90000002"]),
            (TrialFilter(last_update=DateRange.parse("2026..")), ["NCT90000001"]),
            (TrialFilter(enrollment=IntRange.parse("300..400")), ["NCT90000002"]),
            (TrialFilter(enrollment=IntRange.parse("1000..")), ["NCT90000001"]),
            (TrialFilter(has_results=True), ["NCT90000002"]),
            (TrialFilter(has_results=False), ["NCT90000001", "NCT90000003", "ISRCTN00000001"]),
            (TrialFilter(q="music"), ["ISRCTN00000001"]),
            (TrialFilter(q="alzheimer", status=("COMPLETED",)), ["NCT90000002"]),
            (TrialFilter(q="!!"), ["NCT90000001", "NCT90000002", "NCT90000003", "ISRCTN00000001"]),
            # Trial IDs, in any case and as a list, find those trials; the start of one doesn't.
            (TrialFilter(q="NCT90000003"), ["NCT90000003"]),
            (TrialFilter(q="isrctn00000001, (NCT90000002);"), ["NCT90000002", "ISRCTN00000001"]),
            (TrialFilter(q="NCT90000002", status=("RECRUITING",)), []),
            (TrialFilter(q="NCT9000000"), []),
        ],
    )
    def test_query_trials_filters(
        self, storage: Storage, ids: list[int], filter: TrialFilter, expected: list[str]
    ) -> None:
        page = storage.query_trials(filter, sort=Sort("id", descending=False))

        assert source_ids(page.items) == expected
        assert storage.count_trials(filter) == len(expected)

    def test_query_trials_pages_with_a_cursor(self, storage: Storage, ids: list[int]) -> None:
        by_id = Sort("id", descending=False)
        first = storage.query_trials(sort=by_id, limit=3)
        assert first.next is not None
        second = storage.query_trials(sort=by_id, limit=3, after=first.next)

        assert [summary.id for summary in first.items + second.items] == sorted(ids)
        assert second.next is None
        last = storage.query_trials(sort=by_id, limit=4)
        assert last.next is None  # exactly a page: no empty page after it

    @pytest.mark.parametrize(
        ("sort", "expected"),
        [
            # Trials without a value come last when descending, first when ascending.
            ("-last_update", ["NCT90000001", "NCT90000002", "ISRCTN00000001", "NCT90000003"]),
            ("last_update", ["NCT90000003", "ISRCTN00000001", "NCT90000002", "NCT90000001"]),
            ("-start_date", ["NCT90000001", "NCT90000002", "ISRCTN00000001", "NCT90000003"]),
            ("start_date", ["NCT90000003", "ISRCTN00000001", "NCT90000002", "NCT90000001"]),
            ("-enrollment", ["NCT90000001", "NCT90000002", "ISRCTN00000001", "NCT90000003"]),
            ("-id", ["ISRCTN00000001", "NCT90000003", "NCT90000002", "NCT90000001"]),
        ],
    )
    def test_query_trials_sorts_and_pages_one_at_a_time(
        self, storage: Storage, ids: list[int], sort: str, expected: list[str]
    ) -> None:
        whole = storage.query_trials(sort=Sort.parse(sort))
        assert source_ids(whole.items) == expected

        paged: list[str] = []
        after = None
        for _ in expected:
            page = storage.query_trials(sort=Sort.parse(sort), after=after, limit=1)
            paged += source_ids(page.items)
            after = page.next
        assert paged == expected
        assert after is None

    def test_query_trials_pages_through_ties(self, storage: Storage) -> None:
        records = [
            replace(minimal_trial(), source_id=f"NCT{i}", start_date=date(2020, 1, 1))
            for i in range(5)
        ]
        storage.upsert_batch(records)

        seen: list[str] = []
        after = None
        while True:
            page = storage.query_trials(sort=Sort.parse("-start_date"), after=after, limit=2)
            seen += source_ids(page.items)
            if page.next is None:
                break
            after = page.next
        assert seen == [f"NCT{i}" for i in reversed(range(5))]

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
        assert source_ids(storage.search(text).hits) == [expected]

    @pytest.mark.parametrize("text", ["infusion", "INFUSED", "randomizing"])
    def test_search_matches_other_forms_of_a_word(
        self, storage: Storage, ids: list[int], text: str
    ) -> None:
        assert source_ids(storage.search(text).hits) == ["NCT90000001"]

    def test_search_needs_every_word(self, storage: Storage, ids: list[int]) -> None:
        assert storage.search("amyloid treadmill").hits == []
        assert source_ids(storage.search("amyloid remternetug").hits) == ["NCT90000001"]

    def test_search_hits_identify_the_trial(self, storage: Storage, ids: list[int]) -> None:
        [hit] = storage.search("remternetug").hits

        trial = phase3_trial()
        assert (hit.id, hit.source, hit.source_id, hit.title, hit.status, hit.phase) == (
            ids[0],
            trial.source,
            trial.source_id,
            trial.title,
            trial.status,
            trial.phase,
        )

    def test_search_hits_carry_a_snippet(self, storage: Storage, ids: list[int]) -> None:
        [hit] = storage.search("plaques").hits

        matched = {part.text.lower() for part in hit.snippet if part.match}
        assert matched
        assert matched <= {"plaque", "plaques"}  # stemmed like the search
        assert "plaque" in "".join(part.text for part in hit.snippet).lower()

    def test_a_title_only_match_gets_the_start_of_the_text(
        self, storage: Storage, ids: list[int]
    ) -> None:
        [hit] = storage.search("aerobic exercise memory older").hits

        assert hit.source_id == "NCT90000002"
        assert hit.snippet  # the conditions or summary, matched words marked if any

    def test_search_within_a_filter(self, storage: Storage, ids: list[int]) -> None:
        result = storage.search("alzheimer", filter=TrialFilter(status=("COMPLETED",)))

        assert source_ids(result.hits) == ["NCT90000002"]
        assert result.candidates == 1
        assert not result.capped

    def test_search_ranks_title_matches_first(self, storage: Storage) -> None:
        in_description = replace(
            minimal_trial(), source_id="NCT1", description="Exploratory zebrafish model."
        )
        in_title = replace(minimal_trial(), source_id="NCT2", title="Zebrafish models of tau")
        storage.upsert_batch([in_description, in_title])

        hits = storage.search("zebrafish").hits

        assert source_ids(hits) == ["NCT2", "NCT1"]
        first, second = hits[0].score, hits[1].score
        assert first is not None
        assert second is not None
        assert first > second

    def test_search_limit(self, storage: Storage, ids: list[int]) -> None:
        assert len(storage.search("alzheimer").hits) == 2
        assert len(storage.search("alzheimer", limit=1).hits) == 1
        assert storage.search("alzheimer", limit=1).candidates == 2
        assert storage.search("alzheimer", limit=0).hits == []

    def test_search_follows_updates(self, storage: Storage, ids: list[int]) -> None:
        changed = replace(
            phase3_trial(),
            brief_summary="Enrollment closed early.",
            interventions=[Intervention("Lecanemab", "DRUG")],
        )

        storage.upsert_batch([changed])

        assert storage.search("infusions").hits == []
        assert storage.search("TAL-0451").hits == []
        assert source_ids(storage.search("enrollment closed").hits) == ["NCT90000001"]
        assert source_ids(storage.search("lecanemab").hits) == ["NCT90000001"]

    @pytest.mark.parametrize(
        "text",
        ['"', "NOT", "AND OR", "remternetug*", "(plaques", "title:x", "-", "^", "", "   "],
    )
    def test_search_treats_query_syntax_as_text(
        self, storage: Storage, ids: list[int], text: str
    ) -> None:
        assert isinstance(storage.search(text).hits, list)

    def test_search_reads_quoted_words(self, storage: Storage, ids: list[int]) -> None:
        assert source_ids(storage.search('"remternetug').hits) == ["NCT90000001"]

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
        assert storage.search("remternetug").hits == []
        assert storage.lookup_names("alzheimer") == []

    # --- refreshing ------------------------------------------------------------------------

    def test_refresh_leaves_unchanged_trials_alone(self, storage: Storage, ids: list[int]) -> None:
        before = [storage.get_trial(trial_id) for trial_id in ids]

        with storage.transaction() as tx:
            result = tx.refresh(ids, lambda stored: replace(stored, id=None, ingested_at=None))

        assert (result.unchanged, result.rewritten, result.replaced) == (ids, [], [])
        assert [storage.get_trial(trial_id) for trial_id in ids] == before

    def test_refresh_rewrites_new_details_in_place(self, storage: Storage) -> None:
        old = replace(
            phase3_trial(),
            allocation=None,
            masking=None,
            masked_roles=[],
            keywords=[],
            arms=[],
            interventions=[replace(i, description=None) for i in phase3_trial().interventions],
        )
        [trial_id] = storage.upsert_batch([old])
        before = storage.get_trial(trial_id)
        assert before is not None

        with storage.transaction() as tx:
            result = tx.refresh(
                [trial_id], lambda stored: replace(phase3_trial(), status="COMPLETED")
            )

        assert result.rewritten == [trial_id]
        after = storage.get_trial(trial_id)
        assert after == replace(
            phase3_trial(), status="COMPLETED", id=trial_id, ingested_at=before.ingested_at
        )
        assert source_ids(storage.search("remternetug").hits) == ["NCT90000001"]
        assert storage.count_trials(TrialFilter(status=("COMPLETED",))) == 1

    def test_refresh_replaces_trials_whose_indexed_text_changed(
        self, storage: Storage, ids: list[int]
    ) -> None:
        changed = replace(
            phase3_trial(),
            title="Lecanemab in Early Alzheimer's Disease",
            arms=[Arm("Lecanemab", "EXPERIMENTAL")],
            raw=None,
        )

        with storage.transaction() as tx:
            result = tx.refresh([ids[0]], lambda stored: changed)

        assert result.replaced == [ids[0]]
        stored = storage.get_trial(ids[0])
        assert stored is not None
        assert stored == as_stored(replace(changed, raw=phase3_trial().raw), stored)
        assert source_ids(storage.search("lecanemab").hits) == ["NCT90000001"]

    def test_refresh_skips_what_isnt_derived(self, storage: Storage, ids: list[int]) -> None:
        with storage.transaction() as tx:
            result = tx.refresh([ids[0], 999_999], lambda stored: None)

        assert result.skipped == [ids[0], 999_999]
        assert_round_trips(storage, [phase3_trial()], ids[:1])

    def test_refresh_rejects_a_record_for_another_trial(
        self, storage: Storage, ids: list[int]
    ) -> None:
        def refresh() -> None:
            with storage.transaction() as tx:
                tx.refresh(ids[:2], lambda stored: replace(minimal_trial(), title="Moved"))

        with pytest.raises(ValueError, match="NCT90000003"):
            refresh()

        assert_round_trips(storage, [phase3_trial(), completed_behavioral_trial()], ids[:2])

    # --- bulk loads -------------------------------------------------------------------------

    def test_bulk_load_round_trips_and_indexes(self, storage: Storage) -> None:
        records = sample_trials()

        with storage.bulk_load() as load:
            ids = load.upsert_batch(records[:2]) + load.upsert_batch(records[2:])

        assert_round_trips(storage, records, ids)
        assert source_ids(storage.search("remternetug").hits) == ["NCT90000001"]
        assert [hit.name for hit in storage.lookup_names("zheim")] == ["Alzheimer Disease"]
        assert storage.count_trials(TrialFilter(status=("RECRUITING",))) == 1

    def test_bulk_load_replaces_existing_trials(self, storage: Storage, ids: list[int]) -> None:
        changed = replace(phase3_trial(), title="Renamed", brief_summary="Nothing to see.")

        with storage.bulk_load() as load:
            assert load.upsert_batch([changed]) == [ids[0]]

        assert_round_trips(storage, [changed], [ids[0]])
        assert storage.search("infusions").hits == []
        assert source_ids(storage.search("renamed").hits) == ["NCT90000001"]
        assert source_ids(storage.search("treadmill").hits) == ["NCT90000002"]

    def test_writes_after_a_bulk_load(self, storage: Storage) -> None:
        with storage.bulk_load() as load:
            load.upsert_batch([phase3_trial()])

        storage.upsert_batch([completed_behavioral_trial(), replace(phase3_trial(), title="New")])

        assert source_ids(storage.search("treadmill").hits) == ["NCT90000002"]
        assert source_ids(storage.search("new").hits) == ["NCT90000001"]
        assert storage.search("TRAIL").hits == []

    def test_a_rejected_bulk_batch_writes_nothing(self, storage: Storage) -> None:
        with storage.bulk_load() as load:
            with pytest.raises(ValueError, match="unknown country codes"):
                load.upsert_batch([phase3_trial(), replace(minimal_trial(), countries=["XX"])])
            load.upsert_batch([other_registry_trial()])

        assert source_ids(storage.query_trials().items) == ["ISRCTN00000001"]
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
        assert source_ids(storage.search("remternetug").hits) == ["NCT90000001"]
        assert storage.count_trials() == 3
