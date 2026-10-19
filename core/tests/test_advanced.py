"""Advanced search (``tri_al.advanced``) on five trials where every answer can be worked out."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from tri_al.advanced import (
    AdvancedQuery,
    Near,
    Place,
    SiteCache,
    Sites,
    TextTable,
    Words,
    default_order,
    describe,
    find,
    participant_mask,
    split_eligibility,
)
from tri_al.advanced import results as advanced_results
from tri_al.advanced.query import Term
from tri_al.api import create_app
from tri_al.api import models as m
from tri_al.config import Config
from tri_al.filters import IntRange
from tri_al.plugins import LoadedPlugins
from tri_al.plugins.registry import Contributions
from tri_al.schema import Intervention, Location, Outcome, TrialRecord, age_in_days
from tri_al.stats import TrialIndex
from tri_al.storage import Sort, SQLiteReader, SQLiteStorage
from tri_al.testing.fixtures import minimal_trial

TORONTO = Location("Sunnybrook", "Toronto", "Ontario", "CA", lat=43.7064, lon=-79.3986)
BOSTON = Location("Mass General", "Boston", "Massachusetts", "US", lat=42.3601, lon=-71.0589)
BOSTON_TYPO = replace(BOSTON, facility="Brigham", state="Massachusets")
CAMBRIDGE = Location("Addenbrooke's", "Cambridge", None, "GB", lat=52.2, lon=0.12)

ELIGIBILITY = """Inclusion Criteria:

* Positive amyloid PET scan
* MMSE between 20 and 26

Exclusion Criteria:

* Use of warfarin or other anticoagulants
* Pregnancy"""


def years(n: int) -> int:
    return age_in_days(n, "years")


def trial(source_id: str, **fields: Any) -> TrialRecord:
    defaults: dict[str, Any] = {
        "source_id": source_id,
        "status": "RECRUITING",
        "phase": "PHASE2",
        "study_type": "INTERVENTIONAL",
        "start_date": date(2020, 1, 1),
        "sex": "ALL",
    }
    return replace(minimal_trial(), **{**defaults, **fields})


def registry() -> list[TrialRecord]:
    return [
        trial(
            "NCT00000001",
            title="Lecanemab in Early Alzheimer's Disease",
            phase="PHASE3",
            start_date=date(2023, 1, 1),
            conditions=["Alzheimer Disease"],
            interventions=[
                Intervention("Lecanemab", "DRUG", ("BAN2401",)),
                Intervention("Placebo"),
            ],
            eligibility_criteria=ELIGIBILITY,
            outcomes=[
                Outcome("primary", "Change in ADAS-Cog"),
                Outcome("secondary", "Change in MMSE"),
            ],
            min_age_days=years(50),
            max_age_days=years(85),
            allocation="RANDOMIZED",
            masking="DOUBLE",
            intervention_model="PARALLEL",
            primary_purpose="TREATMENT",
            healthy_volunteers=False,
            locations=[TORONTO, BOSTON],
        ),
        trial(
            "NCT00000002",
            title="Warfarin Dosing in Atrial Fibrillation",
            start_date=date(2021, 1, 1),
            conditions=["Atrial Fibrillation"],
            eligibility_criteria="Inclusion Criteria:\n* Taking warfarin\n\n"
            "Exclusion Criteria:\n* Dementia",
            outcomes=[Outcome("primary", "Time in therapeutic INR range")],
            min_age_days=years(18),
            sex="FEMALE",
            allocation="NON_RANDOMIZED",
            masking="NONE",
            healthy_volunteers=False,
            locations=[BOSTON_TYPO, BOSTON],
        ),
        trial(
            "NCT00000003",
            title="Walking for Older Adults",
            brief_summary="Aerobic exercise to slow cognitive decline.",
            eligibility_criteria="Adults over 65 who can walk.",
            min_age_days=years(65),
            sex="MALE",
            healthy_volunteers=True,
            locations=[CAMBRIDGE],
        ),
        trial(
            "NCT00000004",
            title="Pediatric Asthma Inhaler",
            conditions=["Asthma"],
            min_age_days=years(6),
            max_age_days=years(17),
        ),
        trial(
            "NCT00000005",
            title="Asthma in Adults",
            status="COMPLETED",
            conditions=["Asthma"],
            brief_summary="Asthma control with a new inhaler.",
            outcomes=[
                Outcome("primary", "Asthma control"),
                Outcome("secondary", "ADAS-Cog", "Cognition, measured with ADAS-Cog."),
            ],
        ),
    ]


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[SQLiteStorage]:
    with SQLiteStorage.open(tmp_path / "data" / "trials.db") as storage:
        storage.upsert_batch(registry())
        yield storage


@pytest.fixture
def reader(storage: SQLiteStorage) -> Iterator[SQLiteReader]:
    with storage.read() as reader:
        yield reader


@pytest.fixture
def index(reader: SQLiteReader) -> TrialIndex:
    return TrialIndex.build(reader.connection, reader.data_version())


@pytest.fixture
def table() -> Iterator[TextTable]:
    table = TextTable()
    yield table
    table.close()


def search(
    reader: SQLiteReader,
    index: TrialIndex,
    table: TextTable,
    texts: dict[str, str] | None = None,
    **fields: Any,
) -> list[str]:
    """The source ids the query finds, in its default order."""
    order = fields.pop("order", None)
    query = AdvancedQuery.make(texts or {}, **fields)  # type: ignore[arg-type]
    sites = Sites.build(reader.connection, reader.data_version()) if query.near else None
    found = find(
        reader,
        index,
        index.present,
        query,
        order or default_order(query),
        sites=sites,
        table=table,
    )
    hits = describe(reader, found, query, table, offset=0, limit=50)
    return [hit.trial.source_id for hit in hits]


# --- the syntax ---------------------------------------------------------------------------


def test_reading_words() -> None:
    words = Words.parse(
        'amyloid "positron emission" tau OR p-tau -warfarin -"open label" anticoag*'
    )
    assert words.groups == (
        (Term(("amyloid",)),),
        (Term(("positron", "emission")),),
        (Term(("tau",)), Term(("p", "tau"))),
        (Term(("anticoag",), prefix=True),),
    )
    assert words.excluded == (Term(("warfarin",)), Term(("open", "label")))
    assert words.positive() == (
        '"amyloid" AND "positron emission" AND ("tau" OR "p tau") AND "anticoag"*'
    )
    assert words.negative() == '"warfarin" OR "open label"'
    assert words.expression() == f"({words.positive()}) NOT ({words.negative()})"
    assert [str(term) for group in words.groups for term in group] == [
        "amyloid",
        '"positron emission"',
        "tau",
        '"p tau"',
        "anticoag*",
    ]


def test_reading_near_and_odd_input() -> None:
    near = Words.parse('"amyloid PET"~5 "unclosed quote')
    assert near.groups[0] == (Term(("amyloid", "PET"), near=5),)
    assert near.groups[0][0].fts() == 'NEAR("amyloid" "PET", 5)'
    assert str(near.groups[0][0]) == '"amyloid PET"~5'
    assert near.groups[1] == (Term(("unclosed", "quote")),)
    # A prefix needs three letters; a lone OR, a lone minus and punctuation are ignored;
    # repeats count once; FTS5 syntax is quoted as plain words.
    odd = Words.parse("OR ab* - ... AND NOT tau tau OR")
    assert odd.groups == ((Term(("ab",)),), (Term(("AND",)),), (Term(("NOT",)),), (Term(("tau",)),))
    assert odd.positive() == '"ab" AND "AND" AND "NOT" AND "tau"'
    assert Words.parse("-warfarin").expression() is None
    assert Words.parse("  ").is_empty


def test_fields_become_one_index_query() -> None:
    query = AdvancedQuery.make(
        {
            "title": "amyloid",
            "exclusion": "warfarin -aspirin",
            "condition": "-dementia",
            "text": "tau",
        }
    )
    assert [name for name, _ in query.text] == ["text", "title", "condition", "exclusion"]
    positive, negative = query.index_expressions()
    # The exclusion criteria are in the eligibility column; what they leave out is checked
    # in the text, since the index can't tell the parts apart.
    assert (
        positive
        == '("tau") AND {title official_title} : ("amyloid") AND {eligibility} : ("warfarin")'
    )
    assert negative == '{conditions} : ("dementia")'
    assert [name for name, _ in query.sections] == ["exclusion"]
    assert default_order(query) == "relevance"
    assert default_order(AdvancedQuery.make({"condition": "-dementia"})) == Sort()
    near = AdvancedQuery(near=Near(43.7, -79.4, 50))
    assert default_order(near) == "distance"


def test_equal_queries_are_equal_keys() -> None:
    one = AdvancedQuery.make({"title": "a  b"}, masking=("DOUBLE", "SINGLE", "DOUBLE"))
    two = AdvancedQuery.make({"title": "a b", "summary": ""}, masking=("SINGLE", "DOUBLE"))
    assert one == two
    assert hash(one) == hash(two)
    assert AdvancedQuery.make({"title": "  "}).is_empty


def test_bad_places_and_ages() -> None:
    with pytest.raises(ValueError, match="latitude"):
        Near.parse("toronto", 50)
    with pytest.raises(ValueError, match="latitude"):
        Near(91, 0, 50)
    with pytest.raises(ValueError, match="distance"):
        Near(0, 0, 0)
    with pytest.raises(ValueError, match="negative"):
        AdvancedQuery(ages=IntRange(-5, 10))


def test_splitting_eligibility() -> None:
    assert split_eligibility(ELIGIBILITY) == (
        "* Positive amyloid PET scan\n* MMSE between 20 and 26",
        "* Use of warfarin or other anticoagulants\n* Pregnancy",
    )
    # Headings in other words; text before the first heading belongs to neither part.
    text = (
        "Key criteria below.\n\nKEY INCLUSION CRITERIA\n- age 50+\n"
        "Main Exclusion Criterion:\n- stroke\nother inclusion criteria\n- MMSE 20"
    )
    assert split_eligibility(text) == ("- age 50+\n- MMSE 20", "- stroke")
    # A heading mentioned in a sentence isn't a heading.
    assert split_eligibility("Patients meeting none of the exclusion criteria listed below.") == (
        None,
        None,
    )
    assert split_eligibility(None) == (None, None)
    assert split_eligibility("Exclusion Criteria:\n* smoking") == (None, "* smoking")


# --- searching ----------------------------------------------------------------------------


def test_text_fields_search_their_own_part(
    reader: SQLiteReader, index: TrialIndex, table: TextTable
) -> None:
    assert search(reader, index, table, {"condition": "alzheimer"}) == ["NCT00000001"]
    assert search(reader, index, table, {"title": "alzheimer"}) == ["NCT00000001"]
    assert search(reader, index, table, {"summary": "alzheimer"}) == []
    assert search(reader, index, table, {"intervention": "BAN2401"}) == ["NCT00000001"]
    assert search(reader, index, table, {"summary": "aerobic"}) == ["NCT00000003"]
    assert sorted(search(reader, index, table, {"title": "asthma"})) == [
        "NCT00000004",
        "NCT00000005",
    ]
    assert search(reader, index, table, {"title": "asthma -pediatric"}) == ["NCT00000005"]
    assert search(reader, index, table, {"text": '"amyloid PET"~2'}) == ["NCT00000001"]
    assert search(reader, index, table, {"text": "amyloid", "title": "warfarin"}) == []


def test_only_what_a_field_leaves_out(
    reader: SQLiteReader, index: TrialIndex, table: TextTable
) -> None:
    every = {f"NCT0000000{i}" for i in range(1, 6)}
    assert set(search(reader, index, table, {"condition": "-asthma"})) == every - {
        "NCT00000004",
        "NCT00000005",
    }


def test_inclusion_and_exclusion_criteria(
    reader: SQLiteReader, index: TrialIndex, table: TextTable
) -> None:
    assert sorted(search(reader, index, table, {"eligibility": "warfarin"})) == [
        "NCT00000001",
        "NCT00000002",
    ]
    assert search(reader, index, table, {"exclusion": "warfarin"}) == ["NCT00000001"]
    assert search(reader, index, table, {"inclusion": "warfarin"}) == ["NCT00000002"]
    assert search(reader, index, table, {"exclusion": "anticoag* -pregnancy"}) == []
    assert search(reader, index, table, {"inclusion": "amyloid", "exclusion": "pregnancy"}) == [
        "NCT00000001"
    ]
    # Leaving out words only: trials whose exclusion criteria don't mention them, which
    # includes those without the heading.
    assert sorted(search(reader, index, table, {"exclusion": "-pregnancy"})) == [
        "NCT00000002",
        "NCT00000003",
        "NCT00000004",
        "NCT00000005",
    ]


def test_primary_and_secondary_outcomes(
    reader: SQLiteReader, index: TrialIndex, table: TextTable
) -> None:
    assert search(reader, index, table, {"primary_outcome": "ADAS-Cog"}) == ["NCT00000001"]
    assert search(reader, index, table, {"secondary_outcome": "ADAS-Cog"}) == ["NCT00000005"]
    assert sorted(search(reader, index, table, {"outcome": "ADAS-Cog"})) == [
        "NCT00000001",
        "NCT00000005",
    ]


def test_only_the_newest_candidates_are_checked(
    reader: SQLiteReader,
    index: TrialIndex,
    table: TextTable,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(advanced_results, "SECTION_CANDIDATES", 1)
    query = AdvancedQuery.make({"inclusion": "warfarin OR amyloid"})
    found = find(reader, index, index.present, query, "relevance", table=table)
    assert found.sections is not None
    assert (found.sections.candidates, found.sections.checked) == (2, 1)
    hits = describe(reader, found, query, table, offset=0, limit=10)
    assert [hit.trial.source_id for hit in hits] == ["NCT00000002"]  # the newer one


def test_participants_and_design(reader: SQLiteReader, index: TrialIndex) -> None:
    def ids(**fields: Any) -> list[str]:
        mask = participant_mask(index, AdvancedQuery(**fields))
        found = [int(i) for i in mask.nonzero()[0]]
        return sorted(summary.source_id for summary in reader.summaries(found))

    # 70: within 50-85, over 18 and 65, and no ages given; not 6-17.
    assert ids(ages=IntRange(70, 70)) == [
        "NCT00000001",
        "NCT00000002",
        "NCT00000003",
        "NCT00000005",
    ]
    assert ids(ages=IntRange(None, 17)) == ["NCT00000004", "NCT00000005"]
    assert ids(ages=IntRange(17, 17)) == ["NCT00000004", "NCT00000005"]
    assert ids(ages=IntRange(86, None)) == ["NCT00000002", "NCT00000003", "NCT00000005"]
    assert ids(sex="FEMALE") == ["NCT00000001", "NCT00000002", "NCT00000004", "NCT00000005"]
    assert ids(sex="MALE") == ["NCT00000001", "NCT00000003", "NCT00000004", "NCT00000005"]
    assert ids(healthy_volunteers=True) == ["NCT00000003"]
    assert ids(healthy_volunteers=False) == ["NCT00000001", "NCT00000002"]
    assert ids(allocation=("RANDOMIZED",)) == ["NCT00000001"]
    assert ids(masking=("DOUBLE", "NONE")) == ["NCT00000001", "NCT00000002"]
    assert ids(intervention_model=("PARALLEL",), primary_purpose=("TREATMENT",)) == ["NCT00000001"]
    assert ids(primary_purpose=("UNKNOWN",)) == []
    assert ids(placebo=True) == ["NCT00000001"]
    assert len(ids(placebo=False)) == 4


def test_near_a_place(reader: SQLiteReader, index: TrialIndex, table: TextTable) -> None:
    sites = Sites.build(reader.connection, reader.data_version())
    # Two spellings of Boston's state: the commoner wins.
    boston = sites.find("bost")
    assert [(p.city, p.state, p.country, p.sites) for p in boston] == [
        ("Boston", "Massachusetts", "US", 3)
    ]
    assert [p.city for p in sites.find("cambridge, united k")] == ["Cambridge"]
    assert sites.find("bridge") == []  # inside a word
    assert sites.find("cambridge, us") == []
    assert sites.find("") == []

    near_boston = AdvancedQuery(near=Near(42.36, -71.06, 50))
    found = find(reader, index, index.present, near_boston, "distance", sites=sites, table=table)
    hits = describe(reader, found, near_boston, table, offset=0, limit=10)
    # Equally near: the newer trial first.
    assert [hit.trial.source_id for hit in hits] == ["NCT00000002", "NCT00000001"]
    nearest = hits[0].nearest
    assert nearest is not None
    assert nearest.sites == 2
    assert nearest.km < 1
    assert hits[1].nearest is not None
    assert hits[1].nearest.facility == "Mass General"
    assert found.km is not None
    assert float(found.km.max()) < 1

    # Boston is about 690 km from Toronto.
    assert search(reader, index, table, near=Near(43.7, -79.4, 100)) == ["NCT00000001"]
    assert len(search(reader, index, table, near=Near(43.7, -79.4, 700))) == 2
    assert search(reader, index, table, near=Near(0, 0, 10)) == []


def test_places_by_name_then_sites() -> None:
    places = [
        Place("Toro", "Zamora", "ES", 41.5, -5.4, 1),
        Place("East Toronto", None, "CA", 43.7, -79.3, 5),
        Place("Toronto", "Ontario", "CA", 43.7, -79.4, 16_802),
        Place("Västerås", None, "SE", 59.6, 16.5, 40),
    ]
    sites = Sites(1, np.empty(0, np.int32), np.empty(0, np.int32), places)
    assert [p.city for p in sites.find("toro")] == ["Toronto", "Toro", "East Toronto"]
    assert [p.city for p in sites.find("toronto, can")] == ["Toronto", "East Toronto"]
    assert [p.city for p in sites.find("VÄSTERÅS")] == ["Västerås"]
    assert [p.city for p in sites.find("toro", limit=1)] == ["Toronto"]


def test_order_and_snippets(reader: SQLiteReader, index: TrialIndex, table: TextTable) -> None:
    query = AdvancedQuery.make({"eligibility": "warfarin", "exclusion": "anticoagulants"})
    found = find(reader, index, index.present, query, "relevance", table=table)
    hits = describe(reader, found, query, table, offset=0, limit=10)
    assert [hit.trial.source_id for hit in hits] == ["NCT00000001"]
    assert hits[0].score is not None
    fields = {snippet.field: snippet.parts for snippet in hits[0].snippets}
    assert set(fields) == {"eligibility", "exclusion"}
    assert [part.text for part in fields["exclusion"] if part.match] == ["anticoagulants"]

    female = AdvancedQuery(sex="FEMALE")
    by_start = find(reader, index, index.present, female, Sort("start_date", False), table=table)
    starts = describe(reader, by_start, AdvancedQuery(), table, offset=0, limit=10)
    assert [hit.trial.source_id for hit in starts][:2] == ["NCT00000004", "NCT00000005"]
    assert all(hit.score is None and hit.snippets == () for hit in starts)
    paged = describe(reader, by_start, AdvancedQuery(), table, offset=3, limit=10)
    assert [hit.trial.source_id for hit in paged] == ["NCT00000001"]


# --- the API ------------------------------------------------------------------------------


@pytest.fixture
def client(storage: SQLiteStorage, tmp_path: Path) -> Iterator[TestClient]:
    config = Config.model_validate({"data": {"dir": str(tmp_path / "data")}})
    loaded = LoadedPlugins(plugins=[], settings={}, contributions=Contributions())
    app = create_app(config, loaded, config_file=tmp_path / "tri-al.toml", use_index=False)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client


def test_the_advanced_search_endpoint(client: TestClient) -> None:
    params = {"exclusion": "warfarin", "condition": "alzheimer -asthma", "age": "70"}
    response = client.get("/api/search/advanced", params=params)
    assert response.status_code == 200, response.text
    result = m.AdvancedSearchOut.model_validate(response.json())
    assert (result.total, result.sort, result.ranked) == (1, "relevance", 1)
    assert result.sections == m.SectionCheckOut(candidates=1, checked=1)
    assert [(r.field, r.all, r.none) for r in result.read] == [
        ("condition", [["alzheimer"]], ["asthma"]),
        ("exclusion", [["warfarin"]], []),
    ]
    hit = result.items[0]
    assert hit.trial.source_id == "NCT00000001"
    assert [snippet.field for snippet in hit.snippets] == ["exclusion"]

    again = client.get(
        "/api/search/advanced", params=params, headers={"If-None-Match": response.headers["etag"]}
    )
    assert again.status_code == 304


def test_the_endpoint_pages_sorts_and_filters(client: TestClient) -> None:
    def get(**params: Any) -> m.AdvancedSearchOut:
        response = client.get("/api/search/advanced", params=params)
        assert response.status_code == 200, response.text
        return m.AdvancedSearchOut.model_validate(response.json())

    first = get(sort="-start_date", limit=2)
    assert (first.total, first.sort, first.ranked, first.next_offset) == (5, "-start_date", None, 2)
    assert [hit.trial.source_id for hit in first.items] == ["NCT00000001", "NCT00000002"]
    last = get(sort="-start_date", limit=2, offset=4)
    assert last.next_offset is None
    assert len(last.items) == 1
    # Relevance needs words, distance a place: without them, the default.
    assert get(sort="relevance").sort == "-last_update"
    assert get(sort="distance", title="asthma").sort == "relevance"
    assert get(status="COMPLETED", title="asthma").total == 1
    near = get(near="42.36,-71.06", within=50, sex="FEMALE", allocation="NON_RANDOMIZED")
    assert near.sort == "distance"
    assert near.total == 1
    assert near.items[0].nearest is not None
    assert near.items[0].nearest.city == "Boston"


@pytest.mark.parametrize(
    "params",
    [{"near": "toronto"}, {"near": "91,0"}, {"age": "old"}, {"sort": "title"}, {"sex": "OTHER"}],
)
def test_the_endpoint_refuses_what_it_cant_read(client: TestClient, params: dict[str, str]) -> None:
    assert client.get("/api/search/advanced", params=params).status_code == 422


def test_the_places_endpoint(client: TestClient) -> None:
    response = client.get("/api/places", params={"q": "Bos"})
    assert response.status_code == 200, response.text
    places = m.PlacesOut.model_validate(response.json()).places
    assert [(p.city, p.country_name, p.sites) for p in places] == [("Boston", "United States", 3)]
    assert client.get("/api/places", params={"q": ""}).status_code == 422


def test_site_cache_builds_once_per_version(reader: SQLiteReader) -> None:
    cache = SiteCache()
    first = cache.get(reader.connection, reader.data_version())
    assert cache.get(reader.connection, reader.data_version()) is first
    assert cache.get(reader.connection, reader.data_version() + 1) is not first
