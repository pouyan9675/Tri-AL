from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tri_al.schema import Arm, Intervention, Location, MeshTerm, Outcome, Sponsor
from tri_al.storage.countries import COUNTRIES, EXTRA_COUNTRIES
from tri_al_ctgov.countries import CTGOV_COUNTRIES, country_code
from tri_al_ctgov.normalize import age_days, hashable, normalize, parse_date, phase

if TYPE_CHECKING:
    from tests.conftest import StudyLoader

RESPONSES = Path(__file__).parent / "fixtures" / "responses"


def test_a_study_with_results_and_two_phases(load_study: StudyLoader) -> None:
    record = normalize(load_study("NCT01662882"))

    assert (record.source, record.source_id) == ("ctgov", "NCT01662882")
    assert record.title.startswith("A Phase II Trial of Florbetapir (18F)")
    assert record.has_results is True
    assert record.phase == "PHASE2_PHASE3"
    assert (record.status, record.study_type, record.primary_purpose) == (
        "COMPLETED",
        "INTERVENTIONAL",
        "DIAGNOSTIC",
    )
    assert (record.enrollment, record.enrollment_type, record.arms_count) == (48, "ACTUAL", 3)
    assert record.healthy_volunteers is True
    assert record.interventions == [
        Intervention(
            "florbetapir (18F)",
            "DRUG",
            ("18F-AV-45", "Amyvid", "Florbetapir F 18"),
            "IV injection, 370 MBq(10mCi), single dose",
        )
    ]
    assert record.sponsors == [
        Sponsor("Avid Radiopharmaceuticals", "lead", "INDUSTRY"),
        Sponsor("Eli Lilly and Company", "collaborator", "INDUSTRY"),
    ]


def test_arms_get_their_interventions(load_study: StudyLoader) -> None:
    record = normalize(load_study("NCT05026866"))

    assert [(arm.label, arm.type, arm.interventions) for arm in record.arms] == [
        ("Donanemab", "EXPERIMENTAL", ("Donanemab",)),
        ("Placebo", "PLACEBO_COMPARATOR", ("Placebo",)),
    ]
    assert record.arms[0].description is not None
    assert record.arms[0].description.startswith("Donanemab administered intravenously")
    assert [i.description for i in record.interventions] == ["Administered intravenously"] * 2


def test_an_arm_without_interventions(load_study: StudyLoader) -> None:
    record = normalize(load_study("NCT06716476"))

    assert record.arms[1] == Arm(
        "No treatment with Vitamin D", "NO_INTERVENTION", "RA Patients without Vitamin D"
    )


def test_an_arm_names_an_intervention_by_type_and_name(load_study: StudyLoader) -> None:
    raw = copy.deepcopy(load_study("NCT05026866"))
    module = raw["protocolSection"]["armsInterventionsModule"]
    for intervention in module["interventions"]:
        intervention.pop("armGroupLabels", None)
    record = normalize(raw)

    # The arms list "Drug: Donanemab" and "Drug: Placebo".
    assert [arm.interventions for arm in record.arms] == [("Donanemab",), ("Placebo",)]


def test_interventional_design(load_study: StudyLoader) -> None:
    record = normalize(load_study("NCT01245725"))

    assert (record.allocation, record.intervention_model, record.masking) == (
        "RANDOMIZED",
        "PARALLEL",
        "QUADRUPLE",
    )
    assert record.masked_roles == [
        "PARTICIPANT",
        "CARE_PROVIDER",
        "INVESTIGATOR",
        "OUTCOMES_ASSESSOR",
    ]
    assert (record.observational_model, record.time_perspective) == (None, None)


def test_observational_design_and_cohorts(load_study: StudyLoader) -> None:
    record = normalize(load_study("NCT07187596"))

    assert record.study_type == "OBSERVATIONAL"
    assert (record.observational_model, record.time_perspective) == ("OTHER", "OTHER")
    assert (record.allocation, record.masking, record.masked_roles) == (None, None, [])
    assert [(arm.label, arm.type) for arm in record.arms] == [("Mortality outcomes", None)]
    assert record.keywords[:2] == ["Controlled blood pressure", "Mortality outcomes"]


def test_the_timeline(load_study: StudyLoader) -> None:
    record = normalize(load_study("NCT01662882"))

    # Older studies may give a date without saying whether it's actual or estimated.
    assert (
        record.start_date_type,
        record.primary_completion_date_type,
        record.completion_date_type,
    ) == (None, "ACTUAL", "ACTUAL")
    assert record.results_first_posted == date(2013, 9, 19)
    assert record.status_verified == date(2013, 7, 1)
    assert (record.last_known_status, record.why_stopped) == (None, None)


def test_why_a_trial_stopped(load_study: StudyLoader) -> None:
    raw = copy.deepcopy(load_study("NCT01245725"))
    status = raw["protocolSection"]["statusModule"]
    status |= {"whyStopped": "  Sponsor decision ", "lastKnownStatus": "RECRUITING"}
    status["statusVerifiedDate"] = "2011-03"
    record = normalize(raw)

    assert record.why_stopped == "Sponsor decision"
    assert record.last_known_status == "RECRUITING"
    assert record.status_verified == date(2011, 3, 1)


def test_month_only_dates_become_the_first(load_study: StudyLoader) -> None:
    record = normalize(load_study("NCT01662882"))

    # startDateStruct is "2012-10"; the posting dates are full dates.
    assert record.start_date == date(2012, 10, 1)
    assert record.primary_completion_date == date(2013, 2, 1)
    assert record.first_posted == date(2012, 8, 13)
    assert record.last_update == date(2013, 9, 19)


def test_a_withdrawn_study_without_locations(load_study: StudyLoader) -> None:
    record = normalize(load_study("NCT01245725"))

    assert record.status == "WITHDRAWN"
    assert (record.enrollment, record.enrollment_type) == (0, "ACTUAL")
    assert record.start_date is None
    assert (record.locations, record.countries) == ([], [])
    assert (record.location_scope, record.num_sites) == (None, 0)
    assert record.min_age_days == 6574  # 18 years
    assert record.max_age_days is None


def test_a_multinational_study(load_study: StudyLoader) -> None:
    record = normalize(load_study("NCT05026866"))

    assert record.countries == ["US", "JP", "PR"]
    assert record.location_scope == "BOTH"
    assert record.num_sites == 216
    assert record.locations[0] == Location(
        "Parkway Medical Center", "Birmingham", "Alabama", "US", None, 33.52066, -86.80249
    )
    assert (record.min_age_days, record.max_age_days) == (20088, 29220)  # 55 to 80 years
    assert record.start_date == date(2021, 8, 27)
    assert record.conditions == ["Alzheimer Disease"]


def test_mesh_terms_and_ancestors(load_study: StudyLoader) -> None:
    record = normalize(load_study("NCT05026866"))

    assert record.mesh_terms[:2] == [
        MeshTerm("D000544", "Alzheimer Disease", "condition"),
        MeshTerm("D003704", "Dementia", "condition", ancestor=True),
    ]
    assert MeshTerm("C000729112", "donanemab", "intervention") in record.mesh_terms
    assert sum(not term.ancestor for term in record.mesh_terms) == 2


def test_outcomes_keep_their_kind_and_order(load_study: StudyLoader) -> None:
    record = normalize(load_study("NCT05026866"))

    assert [outcome.kind for outcome in record.outcomes] == ["primary"] + ["secondary"] * 17
    first = record.outcomes[0]
    assert first.measure.startswith("Time to Clinical Progression")
    assert first.time_frame == "Estimated up to Week 332"
    assert first.description is not None


def test_ages_in_minutes_and_hours(load_study: StudyLoader) -> None:
    record = normalize(load_study("NCT06082674"))

    assert (record.min_age_days, record.max_age_days) == (0, 0)  # 5 minutes to 6 hours


def test_an_observational_study(load_study: StudyLoader) -> None:
    record = normalize(load_study("NCT07187596"))

    assert (record.study_type, record.phase, record.primary_purpose) == (
        "OBSERVATIONAL",
        None,
        None,
    )
    assert record.interventions == []
    assert record.max_age_days == 47482  # 130 years


def test_kosovo_gets_its_user_assigned_code(load_study: StudyLoader) -> None:
    record = normalize(load_study("NCT06716476"))

    assert record.countries == ["XK"]
    assert record.location_scope == "NON_US"


def test_text_fields(load_study: StudyLoader) -> None:
    record = normalize(load_study("NCT06082674"))

    raw = load_study("NCT06082674")["protocolSection"]
    assert record.brief_summary == raw["descriptionModule"]["briefSummary"].strip()
    assert record.description == raw["descriptionModule"]["detailedDescription"].strip()
    assert record.eligibility_criteria == raw["eligibilityModule"]["eligibilityCriteria"].strip()


def test_a_minimal_study() -> None:
    record = normalize({"protocolSection": {"identificationModule": {"nctId": "NCT00000001"}}})

    assert (record.source_id, record.title, record.has_results) == (
        "NCT00000001",
        "NCT00000001",
        False,
    )
    assert record.outcomes == []
    assert record.locations == []


def test_a_study_without_an_id() -> None:
    with pytest.raises(ValueError, match=r"no protocolSection\.identificationModule\.nctId"):
        normalize({"protocolSection": {}})


def test_errors_name_the_study() -> None:
    raw: dict[str, Any] = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000002"},
            "statusModule": {"startDateStruct": {"date": "sometime"}},
        }
    }

    with pytest.raises(ValueError, match="NCT00000002: unreadable date 'sometime'"):
        normalize(raw)


def test_wrongly_shaped_modules_are_errors() -> None:
    raw = {"protocolSection": {"identificationModule": {"nctId": "N1"}, "designModule": []}}

    with pytest.raises(ValueError, match="N1: designModule is a list, not an object"):
        normalize(raw)


def test_blank_names_are_dropped() -> None:
    raw = {
        "protocolSection": {
            "identificationModule": {"nctId": "N1", "briefTitle": "  Title  "},
            "conditionsModule": {"conditions": ["  ", "Pain ", None]},
            "outcomesModule": {"primaryOutcomes": [{"measure": " "}, {"description": "Only"}]},
            "armsInterventionsModule": {"interventions": [{"type": "DRUG"}]},
        }
    }

    record = normalize(raw)

    assert (record.title, record.conditions, record.interventions) == ("Title", ["Pain"], [])
    assert record.outcomes == [Outcome("primary", "", "Only")]


@pytest.mark.parametrize(
    ("phases", "expected"),
    [
        (["PHASE2", "PHASE3"], "PHASE2_PHASE3"),
        (["PHASE2", "PHASE1"], "PHASE1_PHASE2"),
        (["EARLY_PHASE1"], "EARLY_PHASE1"),
        (["NA"], "NA"),
        ([], None),
        (None, None),
    ],
)
def test_phase(phases: object, expected: str | None) -> None:
    assert phase(phases) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2024-03-15", date(2024, 3, 15)), ("2024-03", date(2024, 3, 1)), ("2024", date(2024, 1, 1))],
)
def test_parse_date(text: str, expected: date) -> None:
    assert parse_date(text) == expected


@pytest.mark.parametrize("text", ["", "2024-13", "March 2024", "2024-03-15-01"])
def test_parse_date_rejects_other_shapes(text: str) -> None:
    with pytest.raises(ValueError, match=r"unreadable date|month must be"):
        parse_date(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("18 Years", 6574), ("1 Year", 365), ("6 Months", 182), ("36 Weeks", 252), ("12 Hours", 0)],
)
def test_age_days(text: str, expected: int) -> None:
    assert age_days(text) == expected


@pytest.mark.parametrize("text", ["N/A", "", "18", "18 Lightyears", None, 18])
def test_unreadable_ages_are_none(text: object) -> None:
    assert age_days(text) is None


def test_hashable_drops_only_the_release_date(load_study: StudyLoader) -> None:
    raw = load_study("NCT01662882")
    untouched = copy.deepcopy(raw)

    view = hashable(raw)

    assert raw == untouched
    assert view["derivedSection"]["miscInfoModule"] == {}
    assert {**view, "derivedSection": raw["derivedSection"]} == raw


def test_hashable_without_a_release_date() -> None:
    raw: dict[str, Any] = {"protocolSection": {}, "derivedSection": {"miscInfoModule": {}}}

    assert hashable(raw) is raw
    assert hashable({"protocolSection": {}}) == {"protocolSection": {}}


def test_every_country_the_api_uses_has_a_code_the_core_knows() -> None:
    values = json.loads((RESPONSES / "location_country_values.json").read_text())
    names = [value["value"] for value in values[0]["topValues"]]
    known = {code for code, _, _ in (*COUNTRIES, *EXTRA_COUNTRIES)}

    assert len(names) == len(CTGOV_COUNTRIES) == 226
    assert all(country_code(name) in known for name in names)


def test_country_names_match_loosely() -> None:
    assert country_code("united states ") == "US"
    assert country_code("Côte d’Ivoire") == "CI"  # noqa: RUF001 (the API's apostrophe)
    assert country_code("Atlantis") is None
    assert country_code(None) is None
