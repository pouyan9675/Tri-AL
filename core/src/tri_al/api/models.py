"""Response and request models: the API's OpenAPI schema, which ``web/`` builds a client from.

Handlers return JSON bytes made with orjson rather than these models, which is faster; the
tests check that responses validate against them, so the schema stays true.
"""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


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
        description="Display names of coded fields: status, phase, study_type, sponsor_class, "
        "intervention_type, primary_purpose, arm_type, allocation, intervention_model, "
        "observational_model, time_perspective, masking and masked_role. A code without one "
        "is shown as itself."
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
    description: str | None


class ArmOut(_Out):
    label: str
    type: str | None
    description: str | None
    interventions: list[str] = Field(description="Names of the interventions this arm gets.")


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
    allocation: str | None
    intervention_model: str | None
    observational_model: str | None
    time_perspective: str | None
    masking: str | None
    masked_roles: list[str]
    start_date: date | None
    primary_completion_date: date | None
    completion_date: date | None
    first_posted: date | None
    last_update: date | None
    start_date_type: str | None = Field(description="ACTUAL or ESTIMATED; None if not given.")
    primary_completion_date_type: str | None
    completion_date_type: str | None
    results_first_posted: date | None
    status_verified: date | None = Field(description="When the status was last confirmed.")
    last_known_status: str | None = Field(description="The status before it became UNKNOWN.")
    why_stopped: str | None
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
    keywords: list[str]
    mesh_terms: list[MeshTermOut]
    interventions: list[InterventionOut]
    arms: list[ArmOut]
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
    score: float | None = Field(
        description="Higher is better, among text matches; null for an ID match."
    )
    snippet: list[SnippetPartOut]
    id_match: Literal["exact", "prefix"] | None = Field(
        description="Found by its ID (`exact`) or the start of it (`prefix`), before every "
        "text match; null for a text match."
    )


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


class SeriesOut(_Out):
    key: str
    label: str


class ChartSpecOut(_Out):
    id: str
    title: str
    widget: Literal[
        "bar", "line", "area", "pie", "stat", "table", "map", "trends", "scatter", "scatter3d"
    ]
    description: str
    section: str = Field(description="The page section; empty for the first, untitled one.")
    page: Literal["dashboard", "analysis"] = Field(
        description="Where the chart is shown: the dashboard or the analysis page."
    )
    x: str
    y: str
    series: list[SeriesOut] = Field(
        description="Line and area charts with several series: each one's row key and name. "
        "Empty: one series, `y`."
    )
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


# --- AI -----------------------------------------------------------------------------------

LabelColor = Literal["blue", "orange", "teal", "amber", "pink", "green", "violet", "red"]
AnnotatedField = Literal["brief_summary", "description", "eligibility_criteria"]


class AnnotationLabelOut(_Out):
    name: str
    description: str
    examples: list[str]
    color: LabelColor = Field(description="Its own colour, or one given by its position.")


class AnnotationLabelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    examples: list[str] = Field(default_factory=list)
    color: LabelColor | Literal[""] = Field(default="", description="Empty: by position.")


class ModelBackendOut(_Out):
    name: str
    title: str


class AiSettingsOut(_Out):
    enabled: bool
    backend: str
    backends: list[ModelBackendOut]
    server: str
    model: str = Field(description="Empty: the first model the server has loaded.")
    labels: list[AnnotationLabelOut]
    colors: list[LabelColor] = Field(description="The colours a label can take, in order.")
    locked: list[str] = Field(
        description="Settings a TRI_AL_AI__* variable sets; changing them in the file does "
        "nothing while it's set."
    )


class AiSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    backend: str | None = None
    server: str | None = None
    model: str | None = Field(default=None, description="Empty: the first loaded model.")
    labels: list[AnnotationLabelIn] | None = Field(
        default=None, description="Replaces every label."
    )


class AiModelsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: str | None = Field(default=None, description="Default: the saved one.")
    server: str | None = Field(default=None, description="Default: the saved one.")


class AiModelOut(_Out):
    id: str
    kind: str | None = Field(description="llm, vlm or embeddings, when the server says.")
    loaded: bool | None = Field(description="In memory now, when the server says.")
    detail: str | None


class AiModelsOut(_Out):
    backend: str
    server: str
    models: list[AiModelOut]
    error: str | None = Field(description="Why the models couldn't be listed.")


class AnnotateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: AnnotatedField


class AnnotationSpanOut(_Out):
    start: int = Field(description="Offsets in the field's text, with line breaks as \\n.")
    end: int
    label: str


class AnnotationLabelRefOut(_Out):
    name: str
    color: LabelColor


class AnnotationStartOut(_Out):
    type: Literal["start"]
    model: str
    length: int = Field(description="Characters in the text the offsets refer to.")
    chunks: int = Field(description="Pieces the text was cut into, each its own request.")
    cached: bool
    labels: list[AnnotationLabelRefOut]


class AnnotationSpansOut(_Out):
    type: Literal["spans"]
    chunk: int
    spans: list[AnnotationSpanOut]


class AnnotationDoneOut(_Out):
    type: Literal["done"]
    spans: int
    seconds: float


class AnnotationErrorOut(_Out):
    type: Literal["error"]
    message: str


class AnnotationEvent(
    RootModel[
        Annotated[
            AnnotationStartOut | AnnotationSpansOut | AnnotationDoneOut | AnnotationErrorOut,
            Field(discriminator="type"),
        ]
    ]
):
    """One line of an annotation stream."""
