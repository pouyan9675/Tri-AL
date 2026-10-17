"""The trial record that sources produce and storage keeps (docs/design.md §5.1 and §6).

Coded fields use ClinicalTrials.gov API v2's enum values, which is the vocabulary the core
filters and charts on: ``status="RECRUITING"``, ``phase="PHASE2_PHASE3"``,
``study_type="INTERVENTIONAL"``, ``sex="ALL"``, ``enrollment_type="ESTIMATED"``,
``Intervention.type="DRUG"``, ``Sponsor.sponsor_class="INDUSTRY"``. A source for another
registry maps its own codes onto these.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

type SponsorRole = Literal["lead", "collaborator"]
type MeshKind = Literal["condition", "intervention"]
type OutcomeKind = Literal["primary", "secondary", "other"]
type LocationScope = Literal["US", "NON_US", "BOTH"]


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
    intervention); storage keeps the first and drops the rest.

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


__all__ = [
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
]
