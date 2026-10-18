"""Response and request models: the API's OpenAPI schema, which ``web/`` builds a client from.

Handlers return JSON bytes made with orjson rather than these models, which is faster; the
tests check that responses validate against them, so the schema stays true.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunOut(_Out):
    run_id: int
    kind: str
    finished_at: datetime | None
    new: int
    updated: int
    unchanged: int


class MetaOut(_Out):
    version: str
    installed: bool
    data_version: int
    trials: int
    last_run: RunOut | None = Field(description="The latest finished install or update.")
    sources: dict[str, str | None] = Field(description="Each source's update cursor.")
    schedule: str
    plugins: list[str]
    search_candidates: int = Field(description="Matches a search ranks at most.")
    labels: dict[str, dict[str, str]] = Field(
        description="Display names of coded fields: status, phase, study_type, sponsor_class "
        "and intervention_type. A code without one is shown as itself."
    )


class TrialSummaryOut(_Out):
    id: int
    source: str
    source_id: str
    title: str
    status: str | None
    phase: str | None
    study_type: str | None
    start_date: date | None
    completion_date: date | None
    last_update: date | None
    enrollment: int | None
    has_results: bool
    num_sites: int
    lead_sponsor: str | None
    conditions: list[str]


class TrialPageOut(_Out):
    data_version: int
    items: list[TrialSummaryOut]
    next_cursor: str | None = Field(description="Pass as `cursor` for the next page.")
    total: int | None = Field(description="Trials the filter matches; on the first page only.")


class OutcomeOut(_Out):
    kind: str
    measure: str
    description: str | None
    time_frame: str | None


class MeshTermOut(_Out):
    code: str
    term: str
    kind: str
    ancestor: bool


class InterventionOut(_Out):
    name: str
    type: str | None
    other_names: list[str]


class SponsorOut(_Out):
    name: str
    role: str
    sponsor_class: str | None


class LocationOut(_Out):
    facility: str | None
    city: str | None
    state: str | None
    country_code: str | None
    status: str | None
    lat: float | None
    lon: float | None


class TrialDetailOut(_Out):
    data_version: int
    id: int
    source: str
    source_id: str
    title: str
    official_title: str | None
    status: str | None
    phase: str | None
    study_type: str | None
    primary_purpose: str | None
    start_date: date | None
    primary_completion_date: date | None
    completion_date: date | None
    first_posted: date | None
    last_update: date | None
    enrollment: int | None
    enrollment_type: str | None
    arms_count: int | None
    has_results: bool
    min_age_days: int | None
    max_age_days: int | None
    sex: str | None
    healthy_volunteers: bool | None
    location_scope: str | None
    brief_summary: str | None
    description: str | None
    eligibility_criteria: str | None
    outcomes: list[OutcomeOut]
    conditions: list[str]
    mesh_terms: list[MeshTermOut]
    interventions: list[InterventionOut]
    sponsors: list[SponsorOut]
    countries: list[str]
    locations: list[LocationOut]
    ingested_at: datetime | None


class ChangeOut(_Out):
    run_id: int
    changed_at: datetime | None
    field: str
    old: Any
    new: Any


class ChangesOut(_Out):
    data_version: int
    source: str
    source_id: str
    changes: list[ChangeOut]


class SnippetPartOut(_Out):
    text: str
    match: bool


class SearchHitOut(_Out):
    id: int
    source: str
    source_id: str
    title: str
    status: str | None
    phase: str | None
    score: float
    snippet: list[SnippetPartOut]


class NameHitOut(_Out):
    kind: Literal["condition", "intervention", "sponsor"]
    id: int
    name: str


class SearchOut(_Out):
    data_version: int
    query: str
    hits: list[SearchHitOut]
    candidates: int | None = Field(description="Matches ranked, at most `search_candidates`.")
    capped: bool = Field(description="More trials matched than were ranked: the newest were.")
    names: list[NameHitOut] = Field(description="Conditions, interventions and sponsors.")


class FacetValueOut(_Out):
    value: str | None = Field(description="The filter value; null for trials without one.")
    label: str
    count: int


class FacetsOut(_Out):
    data_version: int
    total: int = Field(description="Trials the whole filter matches.")
    facets: dict[str, list[FacetValueOut]]


class LayoutOut(_Out):
    width: int
    height: int
    order: int


class ChartSpecOut(_Out):
    id: str
    title: str
    widget: Literal["bar", "line", "area", "pie", "stat", "table", "map"]
    description: str
    x: str
    y: str
    layout: LayoutOut
    plugin: str
    precomputed: bool


class FacetSpecOut(_Out):
    field: str
    title: str
    plugin: str


class DashboardOut(_Out):
    data_version: int
    charts: list[ChartSpecOut]
    facets: list[FacetSpecOut]


class StatsOut(_Out):
    chart_id: str
    data_version: int
    filtered: bool
    rows: list[dict[str, Any]]


class JobOut(_Out):
    id: int
    type: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    origin: str
    stage: str | None
    progress: int
    total: int | None
    unit: str | None
    message: str | None
    error: str | None
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat: datetime | None
    result: dict[str, Any] | None


class JobsOut(_Out):
    jobs: list[JobOut]


class JobConflictOut(_Out):
    detail: str
    job: JobOut


class PluginOut(_Out):
    name: str
    enabled: bool
    installed: bool
    loaded: bool = Field(description="Running in this server now.")
    version: str | None
    description: str
    problems: list[str]
    settings: dict[str, Any]


class PluginsOut(_Out):
    plugins: list[PluginOut]


class PluginPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    settings: dict[str, Any] | None = Field(
        default=None, description="Settings to change; null values remove a setting."
    )


class PluginChangedOut(_Out):
    plugin: PluginOut
    restart_required: bool = Field(description="Changes apply when the server next starts.")


class ErrorOut(_Out):
    detail: str
