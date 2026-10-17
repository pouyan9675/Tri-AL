"""ClinicalTrials.gov API v2 study JSON → ``TrialRecord`` (docs/design.md §6).

The study shape: ``protocolSection`` (13 modules), ``resultsSection``, ``documentSection``,
``derivedSection`` (MeSH terms for conditions and interventions) and ``hasResults``. Coded
fields keep the API's enum values (``RECRUITING``, ``PHASE3``, ``INDUSTRY``), which is the
core's vocabulary.
"""

import re
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from trial_al.schema import (
    Intervention,
    Location,
    MeshKind,
    MeshTerm,
    Outcome,
    OutcomeKind,
    Sponsor,
    SponsorRole,
    TrialRecord,
    age_in_days,
)
from trial_al_ctgov.countries import country_code

SOURCE = "ctgov"

PHASE_ORDER = ("EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4", "NA")
"""Phases in the order a combined phase names them: ``PHASE2_PHASE3``."""

_AGE = re.compile(r"\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)\s*")
_OUTCOME_KEYS: tuple[tuple[OutcomeKind, str], ...] = (
    ("primary", "primaryOutcomes"),
    ("secondary", "secondaryOutcomes"),
    ("other", "otherOutcomes"),
)
_BROWSE_MODULES: tuple[tuple[MeshKind, str], ...] = (
    ("condition", "conditionBrowseModule"),
    ("intervention", "interventionBrowseModule"),
)

type Json = Mapping[str, Any]


def normalize(raw: Json) -> TrialRecord:
    """The trial in one study document. Raises ValueError, naming the study, if it can't."""
    protocol = _module(raw, "protocolSection")
    nct_id = _text(_module(protocol, "identificationModule").get("nctId"))
    if nct_id is None:
        raise ValueError("the study has no protocolSection.identificationModule.nctId")
    try:
        return _normalize(nct_id, raw, protocol)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{nct_id}: {exc}") from exc


def _normalize(nct_id: str, raw: Json, protocol: Json) -> TrialRecord:
    ident = _module(protocol, "identificationModule")
    status = _module(protocol, "statusModule")
    design = _module(protocol, "designModule")
    eligibility = _module(protocol, "eligibilityModule")
    description = _module(protocol, "descriptionModule")
    arms = _module(protocol, "armsInterventionsModule")
    enrollment = _module(design, "enrollmentInfo")
    locations = [
        _location(location)
        for location in _list(_module(protocol, "contactsLocationsModule"), "locations")
    ]
    arm_groups = arms.get("armGroups")

    return TrialRecord(
        source=SOURCE,
        source_id=nct_id,
        title=_text(ident.get("briefTitle")) or _text(ident.get("officialTitle")) or nct_id,
        official_title=_text(ident.get("officialTitle")),
        status=_text(status.get("overallStatus")),
        phase=phase(design.get("phases")),
        study_type=_text(design.get("studyType")),
        primary_purpose=_text(_module(design, "designInfo").get("primaryPurpose")),
        start_date=_date(status, "startDateStruct"),
        primary_completion_date=_date(status, "primaryCompletionDateStruct"),
        completion_date=_date(status, "completionDateStruct"),
        first_posted=_date(status, "studyFirstPostDateStruct"),
        last_update=_date(status, "lastUpdatePostDateStruct"),
        enrollment=_int(enrollment.get("count")),
        enrollment_type=_text(enrollment.get("type")),
        arms_count=len(arm_groups) if isinstance(arm_groups, list) else None,
        has_results=bool(raw.get("hasResults")),
        min_age_days=age_days(eligibility.get("minimumAge")),
        max_age_days=age_days(eligibility.get("maximumAge")),
        sex=_text(eligibility.get("sex")),
        healthy_volunteers=_bool(eligibility.get("healthyVolunteers")),
        brief_summary=_text(description.get("briefSummary")),
        description=_text(description.get("detailedDescription")),
        eligibility_criteria=_text(eligibility.get("eligibilityCriteria")),
        outcomes=_outcomes(_module(protocol, "outcomesModule")),
        conditions=_texts(_list(_module(protocol, "conditionsModule"), "conditions")),
        mesh_terms=_mesh_terms(_module(raw, "derivedSection")),
        interventions=_interventions(_list(arms, "interventions")),
        sponsors=_sponsors(_module(protocol, "sponsorCollaboratorsModule")),
        countries=list(dict.fromkeys(loc.country_code for loc in locations if loc.country_code)),
        locations=locations,
    )


def phase(phases: object) -> str | None:
    """``["PHASE2", "PHASE3"]`` → ``"PHASE2_PHASE3"``; no phases → None."""
    if not isinstance(phases, list) or not phases:
        return None
    names = dict.fromkeys(str(name) for name in phases)
    order = {name: i for i, name in enumerate(PHASE_ORDER)}
    return "_".join(sorted(names, key=lambda name: order.get(name, len(order))))


def parse_date(text: str) -> date:
    """``2024-03-15`` as is; month-only ``2024-03`` and year-only ``2024`` become the 1st."""
    parts = text.strip().split("-")
    if not 1 <= len(parts) <= 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"unreadable date {text!r}")
    year, month, day = (int(part) for part in [*parts, "1", "1"][:3])
    return date(year, month, day)


def age_days(text: object) -> int | None:
    """``"18 Years"`` → 6574 days (see ``trial_al.schema.age_in_days``); unreadable → None."""
    if not isinstance(text, str) or not (match := _AGE.fullmatch(text)):
        return None
    try:
        return age_in_days(float(match[1]), match[2])
    except ValueError:
        return None


def hashable(raw: Json) -> Json:
    """The study without ``derivedSection.miscInfoModule.versionHolder``.

    ``versionHolder`` is the date of the data release, the same in every study and new
    every day, so hashing it would make every study look changed after each release.
    """
    derived = raw.get("derivedSection")
    if not isinstance(derived, Mapping):
        return raw
    misc = derived.get("miscInfoModule")
    if not isinstance(misc, Mapping) or "versionHolder" not in misc:
        return raw
    misc = {key: value for key, value in misc.items() if key != "versionHolder"}
    return {**raw, "derivedSection": {**derived, "miscInfoModule": misc}}


# --- parts ----------------------------------------------------------------------------------


def _location(location: Json) -> Location:
    geo = _module(location, "geoPoint")
    return Location(
        facility=_text(location.get("facility")),
        city=_text(location.get("city")),
        state=_text(location.get("state")),
        country_code=country_code(_text(location.get("country"))),
        status=_text(location.get("status")),
        lat=_float(geo.get("lat")),
        lon=_float(geo.get("lon")),
    )


def _outcomes(module: Json) -> list[Outcome]:
    outcomes = []
    for kind, key in _OUTCOME_KEYS:
        for outcome in _list(module, key):
            measure = _text(outcome.get("measure"))
            details = _text(outcome.get("description"))
            if measure or details:
                outcomes.append(
                    Outcome(kind, measure or "", details, _text(outcome.get("timeFrame")))
                )
    return outcomes


def _mesh_terms(derived: Json) -> list[MeshTerm]:
    terms = []
    for kind, key in _BROWSE_MODULES:
        browse = _module(derived, key)
        for ancestor, list_key in ((False, "meshes"), (True, "ancestors")):
            for term in _list(browse, list_key):
                code, name = _text(term.get("id")), _text(term.get("term"))
                if code and name:
                    terms.append(MeshTerm(code, name, kind, ancestor))
    return terms


def _interventions(items: Iterable[Json]) -> list[Intervention]:
    return [
        Intervention(name, _text(item.get("type")), tuple(_texts(item.get("otherNames") or [])))
        for item in items
        if (name := _text(item.get("name")))
    ]


def _sponsors(module: Json) -> list[Sponsor]:
    lead = _module(module, "leadSponsor")
    sponsors: list[tuple[Json, SponsorRole]] = [(lead, "lead")] if lead else []
    sponsors += [(collaborator, "collaborator") for collaborator in _list(module, "collaborators")]
    return [
        Sponsor(name, role, _text(sponsor.get("class")))
        for sponsor, role in sponsors
        if (name := _text(sponsor.get("name")))
    ]


# --- values ---------------------------------------------------------------------------------


def _module(parent: Json, key: str) -> Json:
    value = parent.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} is a {type(value).__name__}, not an object")
    return value


def _list(parent: Json, key: str) -> list[Any]:
    value = parent.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{key} is a {type(value).__name__}, not a list")
    return value


def _date(module: Json, key: str) -> date | None:
    text = _text(_module(module, key).get("date"))
    return None if text is None else parse_date(text)


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _texts(values: Iterable[object]) -> list[str]:
    return [text for value in values if (text := _text(value))]


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None
