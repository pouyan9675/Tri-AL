"""The trial record that sources produce and storage keeps (docs/design.md §5.1 and §6).

Coded fields use ClinicalTrials.gov API v2's enum values, which is the vocabulary the core
filters and charts on: ``status="RECRUITING"``, ``phase="PHASE2_PHASE3"``,
``study_type="INTERVENTIONAL"``, ``sex="ALL"``, ``enrollment_type="ESTIMATED"``,
``Intervention.type="DRUG"``, ``Sponsor.sponsor_class="INDUSTRY"``. A source for another
registry maps its own codes onto these.
"""

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Literal

type SponsorRole = Literal["lead", "collaborator"]
type MeshKind = Literal["condition", "intervention"]
type OutcomeKind = Literal["primary", "secondary", "other"]
type LocationScope = Literal["US", "NON_US", "BOTH"]


DAYS_PER_UNIT: dict[str, float] = {
    "year": 365.25,
    "month": 365.25 / 12,
    "week": 7,
    "day": 1,
    "hour": 1 / 24,
    "minute": 1 / 1440,
}
"""How ``age_in_days`` counts each unit. 12 months make a year, so the two agree."""


def age_in_days(amount: float, unit: str) -> int:
    """An age such as ``18 Years`` in whole days (rounded down), for ``min_age_days``.

    ``unit`` is singular or plural, in any case. Filters convert ages with this function too,
    so an "18 years or older" filter matches trials whose minimum age is "18 Years" exactly.
    """
    key = unit.lower().removesuffix("s")
    if key not in DAYS_PER_UNIT:
        raise ValueError(f"unknown age unit {unit!r}; use years, months, weeks, days, ...")
    return math.floor(amount * DAYS_PER_UNIT[key])


@dataclass(frozen=True, slots=True)
class Outcome:
    kind: OutcomeKind
    measure: str
    description: str | None = None
    time_frame: str | None = None


@dataclass(frozen=True, slots=True)
class MeshTerm:
    """A MeSH descriptor the registry attached to the trial's conditions or interventions.

    ``ancestor`` marks terms the registry added from higher up the MeSH tree, so a filter on
    "Dementia" also finds trials tagged "Alzheimer Disease".
    """

    code: str  # descriptor ID, e.g. "D000544"
    term: str
    kind: MeshKind
    ancestor: bool = False


@dataclass(frozen=True, slots=True)
class Intervention:
    name: str
    type: str | None = None
    other_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Sponsor:
    name: str
    role: SponsorRole
    sponsor_class: str | None = None


@dataclass(frozen=True, slots=True)
class Location:
    facility: str | None = None
    city: str | None = None
    state: str | None = None
    country_code: str | None = None  # ISO 3166-1 alpha-2
    status: str | None = None
    lat: float | None = None
    lon: float | None = None


@dataclass(slots=True, kw_only=True)
class TrialRecord:
    """One trial, normalized.

    Identity is ``(source, source_id)``, such as ``("ctgov", "NCT04437511")``.

    Lists keep the source's order. A list may name the same thing twice (the same condition,
    MeSH code and kind, intervention name, sponsor name, country, or alias of one
    intervention); storage keeps the first and drops the rest (see ``without_repeats``).

    ``id`` and ``ingested_at`` belong to storage: it sets them when it writes the record and
    ignores whatever the record carries.
    """

    source: str
    source_id: str
    title: str
    official_title: str | None = None

    status: str | None = None
    phase: str | None = None
    study_type: str | None = None
    primary_purpose: str | None = None

    start_date: date | None = None  # month-only dates become the 1st of the month
    primary_completion_date: date | None = None
    completion_date: date | None = None
    first_posted: date | None = None
    last_update: date | None = None

    enrollment: int | None = None
    enrollment_type: str | None = None
    arms_count: int | None = None
    has_results: bool = False

    min_age_days: int | None = None
    max_age_days: int | None = None
    sex: str | None = None
    healthy_volunteers: bool | None = None

    brief_summary: str | None = None
    description: str | None = None
    eligibility_criteria: str | None = None
    outcomes: list[Outcome] = field(default_factory=list)

    conditions: list[str] = field(default_factory=list)
    mesh_terms: list[MeshTerm] = field(default_factory=list)
    interventions: list[Intervention] = field(default_factory=list)
    sponsors: list[Sponsor] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)  # ISO 3166-1 alpha-2
    locations: list[Location] = field(default_factory=list)

    raw: bytes | None = None  # the source's JSON for this trial
    content_hash: bytes | None = None

    id: int | None = None
    ingested_at: datetime | None = None

    @property
    def lead_sponsor(self) -> Sponsor | None:
        return next((sponsor for sponsor in self.sponsors if sponsor.role == "lead"), None)

    @property
    def location_scope(self) -> LocationScope | None:
        codes = set(self.countries)
        if not codes:
            return None
        if codes == {"US"}:
            return "US"
        return "BOTH" if "US" in codes else "NON_US"

    @property
    def num_sites(self) -> int:
        return len(self.locations)


def without_repeats(record: TrialRecord) -> TrialRecord:
    """``record`` as storage keeps it: repeated list items dropped, the first of each kept.

    Repeats are the same condition, MeSH code and kind, intervention name, sponsor name,
    country, or alias of one intervention.
    """
    return replace(
        record,
        conditions=_unique(record.conditions, lambda name: name),
        mesh_terms=_unique(record.mesh_terms, lambda term: (term.code, term.kind)),
        interventions=[
            replace(i, other_names=tuple(_unique(i.other_names, lambda alias: alias)))
            for i in _unique(record.interventions, lambda i: i.name)
        ],
        sponsors=_unique(record.sponsors, lambda sponsor: sponsor.name),
        countries=_unique(record.countries, lambda code: code),
    )


def _unique[T](items: Iterable[T], key: Callable[[T], object]) -> list[T]:
    seen = set()
    unique = []
    for item in items:
        k = key(item)
        if k not in seen:
            seen.add(k)
            unique.append(item)
    return unique


__all__ = [
    "DAYS_PER_UNIT",
    "Intervention",
    "Location",
    "LocationScope",
    "MeshKind",
    "MeshTerm",
    "Outcome",
    "OutcomeKind",
    "Sponsor",
    "SponsorRole",
    "TrialRecord",
    "age_in_days",
    "without_repeats",
]
