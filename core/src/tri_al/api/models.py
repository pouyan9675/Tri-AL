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
        "observational_model, time_perspective, masking, masked_role and phase_group (the "
        "phase groups term analyses count by, in order). A code without one is shown as "
        "itself."
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


class LinkTermOut(_Out):
    code: str
    term: str
    kind: Literal["condition", "intervention"]
    selected: bool = Field(description="Whether trials are linked by it.")
    trials: int = Field(description="Linked trials that share it.")


class LinkedTrialOut(_Out):
    trial: TrialSummaryOut
    shared: list[str] = Field(description="The codes of the chosen terms it shares.")


class PhaseGroupOut(_Out):
    phase: str | None = Field(description="Null for trials without a phase.")
    total: int
    trials: list[LinkedTrialOut] = Field(description="The first `limit`, most terms shared first.")


class LinkedTrialsOut(_Out):
    data_version: int
    trial: TrialSummaryOut
    terms: list[LinkTermOut] = Field(description="The trial's own MeSH terms.")
    total: int = Field(description="Linked trials.")
    phases: list[PhaseGroupOut] = Field(description="In phase order; trials without one last.")


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
    format: Literal["number", "percent"] | None = Field(
        description="How its numbers read; null: as the chart's `format`."
    )


class ChartSpecOut(_Out):
    id: str
    title: str
    widget: Literal[
        "bar",
        "line",
        "area",
        "pie",
        "stat",
        "table",
        "map",
        "trends",
        "scatter",
        "scatter3d",
        "stacked",
        "forest",
    ]
    description: str
    section: str = Field(description="The page section; empty for the first, untitled one.")
    page: Literal["dashboard", "analysis", "results"] = Field(
        description="Where the chart is shown: the dashboard, the analysis page's Landscape "
        "(`analysis`), or its Results section (`results`)."
    )
    x: str
    y: str
    series: list[SeriesOut] = Field(
        description="Charts with several numbers per row (line, area, bar, table, stacked, "
        "forest): each one's row key and name. Empty: one series, `y`."
    )
    format: Literal["number", "percent"] = Field(
        description="How the numbers read: `percent` for fractions (0.25 is 25%)."
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


# --- term analyses ------------------------------------------------------------------------

TermKind = Literal["condition", "intervention"]
Confidence = Literal["high", "medium", "low"]


class TermRefOut(_Out):
    code: str = Field(description="MeSH descriptor or supplementary concept code.")
    term: str
    kind: TermKind


class TermCountOut(_Out):
    code: str
    term: str
    trials: int


class TermsOut(_Out):
    data_version: int
    kind: TermKind
    terms: list[TermCountOut] = Field(
        description="Trials count those tagged with a narrower term too, in the whole registry."
    )


class TermOverviewOut(_Out):
    data_version: int
    term: TermRefOut
    trials: int = Field(description="The term's trials within the filter.")
    registry_trials: int = Field(description="The term's trials without the filter.")
    within: int = Field(description="Trials within the filter.")
    direct: int = Field(description="The term's trials tagged with it, not only a narrower term.")
    narrower: list[TermCountOut] = Field(description="Narrower terms, with trials in the filter.")
    active: int
    completed: int
    stopped: int
    with_results: int
    lead_sponsors: int
    industry: int = Field(description="Trials with an industry lead sponsor.")
    countries: int
    first_start: date | None
    as_of: date = Field(description="The latest update of any trial: the data's today.")


class YearCountOut(_Out):
    year: int
    trials: int = Field(description="Started that year.")
    phases: list[int] = Field(description="By phase group, in the order of meta labels.")
    share: float = Field(description="Of the filter's trials started that year.")
    new_sponsors: int = Field(description="Lead sponsors whose first trial of it started then.")


class MomentumOut(_Out):
    months: int
    since: date
    until: date
    trials: int = Field(description="First posted in the window.")
    baseline: int = Field(description="First posted in the 12 months before.")
    expected: float
    growth: float = Field(description="Its share in the window over its share before, smoothed.")
    raw_growth: float | None
    p: float
    confidence: Confidence
    direction: Literal["rising", "falling", "steady"]


class TermTimelineOut(_Out):
    data_version: int
    years: list[YearCountOut]
    partial: bool = Field(description="Whether the last year isn't over.")
    momentum: list[MomentumOut]


class ReadoutOut(_Out):
    trial: TrialSummaryOut
    primary_completion: date
    estimated: bool


class QuarterCountOut(_Out):
    quarter: str
    start: date
    trials: int
    phases: list[int]


class TermReadoutsOut(_Out):
    data_version: int
    as_of: date
    until: date
    total: int = Field(description="Active trials whose primary completion is due by `until`.")
    overdue: int = Field(description="Active trials whose primary completion date has passed.")
    quarters: list[QuarterCountOut]
    trials: list[ReadoutOut] = Field(description="The soonest 200.")


class RelatedTermOut(_Out):
    code: str
    term: str
    kind: TermKind
    trials: int
    share: float
    elsewhere: float = Field(description="Share of the filter's other trials tagged with it.")
    lift: float = Field(description="How many times more common with the term, smoothed.")
    p: float
    q: float = Field(description="p corrected for every term tested (Benjamini-Hochberg).")
    confidence: Confidence


class NetworkNodeOut(_Out):
    code: str
    term: str
    kind: TermKind
    trials: int
    lift: float | None
    group: int = Field(description="Its community; -1 for the term itself.")
    center: bool


class NetworkEdgeOut(_Out):
    source: int = Field(description="Index into nodes.")
    target: int
    trials: int
    jaccard: float


class TermRelatedOut(_Out):
    data_version: int
    trials: int
    others: int = Field(description="The filter's other trials, the baseline.")
    tested: int
    conditions: list[RelatedTermOut]
    interventions: list[RelatedTermOut]
    nodes: list[NetworkNodeOut] = Field(description="The term first.")
    edges: list[NetworkEdgeOut]


class PipelineRowOut(_Out):
    code: str
    term: str
    kind: TermKind
    trials: int
    phases: list[int] = Field(description="Trials in each of `phases`.")
    active: int
    highest: str | None
    last_start: date | None


class FunnelRowOut(_Out):
    phase: str | None
    trials: int
    active: int
    completed: int
    stopped: int
    unknown: int
    other: int


class TermPipelineOut(_Out):
    data_version: int
    kind: TermKind = Field(description="The rows' kind: the other kind than the term's.")
    phases: list[str]
    rows: list[PipelineRowOut]
    funnel: list[FunnelRowOut]


class StopRateOut(_Out):
    group: str
    closed: int
    stopped: int
    rate: float | None
    baseline_closed: int
    baseline_rate: float | None
    ratio: float | None
    p: float
    q: float
    confidence: Confidence


class ReasonExampleOut(_Out):
    source_id: str
    reason: str


class StopReasonOut(_Out):
    key: str
    label: str
    trials: int
    examples: list[ReasonExampleOut]


class TermAttritionOut(_Out):
    data_version: int
    phases: list[StopRateOut]
    observed: int
    expected: float = Field(description="Stopped trials at the baseline's rates, by phase.")
    ratio: float | None
    p: float
    confidence: Confidence
    stopped: int
    read: int = Field(description="Stopped trials whose reasons were read (at most 2,000).")
    stated: int
    reasons: list[StopReasonOut]


class CurveOut(_Out):
    group: str
    trials: int
    events: int
    median: float | None = Field(description="Months.")
    months: list[float]
    values: list[float]


class ResultsShareOut(_Out):
    months: int
    share: float | None
    baseline: float | None


class TermDurationsOut(_Out):
    data_version: int
    completion: list[CurveOut] = Field(
        description="Share still running by months since start, by phase group, then all."
    )
    completion_baseline: list[CurveOut]
    results: CurveOut = Field(description="Share with results by months since completion.")
    results_baseline: CurveOut
    results_at: list[ResultsShareOut]


class BenchmarkOut(_Out):
    key: str
    label: str
    section: str
    unit: Literal["share", "years", "participants", "sites"]
    value: float | None
    baseline: float | None = Field(description="The filter's other trials, with its phase mix.")
    difference: float | None = Field(description="Standardized: 0.2 small, 0.5 medium, 0.8 large.")
    trials: int


class EnrollmentBinOut(_Out):
    low: int
    high: int | None
    share: float
    baseline: float


class TermProfileOut(_Out):
    data_version: int
    trials: int
    baseline_trials: int
    rows: list[BenchmarkOut]
    enrollment: list[EnrollmentBinOut]


class ThemeTrialOut(_Out):
    source_id: str
    title: str


class ThemeTermOut(_Out):
    code: str
    term: str
    kind: TermKind


class ThemeOut(_Out):
    cluster: int
    label: str
    words: list[str]
    terms: list[ThemeTermOut]
    size: int
    share: float
    growth: float = Field(description="Its share of trials started in 3 years over before.")
    confidence: Confidence
    examples: list[ThemeTrialOut]


class ThemePointOut(_Out):
    x: float
    y: float
    cluster: int
    source_id: str
    title: str


class TermThemesOut(_Out):
    data_version: int
    trials: int
    embedded: int
    sampled: int
    silhouette: float | None
    themes: list[ThemeOut] = Field(description="Largest first; empty under 30 trials with vectors.")
    points: list[ThemePointOut]


class SimilarTermOut(_Out):
    code: str
    term: str
    kind: TermKind
    similarity: float
    trials: int
    shared: int = Field(description="Trials tagged with both; 0: never tagged together.")


class TermSimilarOut(_Out):
    data_version: int
    embedded: int
    same: list[SimilarTermOut]
    other: list[SimilarTermOut]


# --- advanced search ----------------------------------------------------------------------

TextFieldName = Literal[
    "text",
    "title",
    "condition",
    "intervention",
    "summary",
    "eligibility",
    "inclusion",
    "exclusion",
    "outcome",
    "primary_outcome",
    "secondary_outcome",
]


class FieldReadOut(_Out):
    field: TextFieldName
    all: list[list[str]] = Field(
        description="Groups that must all match, each by any of its terms, as typed: a word, "
        '`"a phrase"`, `"words near"~5` or `prefix*`.'
    )
    none: list[str] = Field(description="Terms that mustn't match.")


class SectionCheckOut(_Out):
    candidates: int = Field(
        description="Trials matching the rest, whose text was to be checked for inclusion, "
        "exclusion, primary or secondary outcomes."
    )
    checked: int = Field(description="The newest of them, whose text was checked.")


class FieldSnippetOut(_Out):
    field: TextFieldName
    parts: list[SnippetPartOut]


class NearestSiteOut(_Out):
    km: float
    facility: str | None
    city: str | None
    state: str | None
    country: str | None
    sites: int = Field(description="The trial's sites within the distance.")


class AdvancedHitOut(_Out):
    trial: TrialSummaryOut
    score: float | None = Field(
        description="Relevance (higher is better), for the ranked matches when sorted by it."
    )
    snippets: list[FieldSnippetOut] = Field(
        description="Where each field's words are, for fields with text to show."
    )
    nearest: NearestSiteOut | None = Field(description="The nearest site, with a place.")


class AdvancedSearchOut(_Out):
    data_version: int
    total: int = Field(description="Trials that match.")
    sort: str = Field(description="`relevance`, `distance` or a trial list sort.")
    ranked: int | None = Field(
        description="By relevance: matches ranked, the newest ones (at most `search_candidates` "
        "in the meta); the rest follow, newest first."
    )
    sections: SectionCheckOut | None = Field(
        description="With inclusion, exclusion, primary or secondary outcome fields."
    )
    read: list[FieldReadOut] = Field(description="How each text field was read.")
    offset: int
    next_offset: int | None = Field(description="Pass as `offset` for the next page.")
    items: list[AdvancedHitOut]


class PlaceOut(_Out):
    city: str | None
    state: str | None
    country: str | None = Field(description="ISO 3166-1 alpha-2 code.")
    country_name: str | None
    lat: float
    lon: float
    sites: int = Field(description="Trial sites there.")


class PlacesOut(_Out):
    data_version: int
    places: list[PlaceOut]
