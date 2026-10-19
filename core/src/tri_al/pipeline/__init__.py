"""The data pipeline (docs/design.md §5.3): sources, install, update and their events."""

from tri_al.pipeline.events import (
    EVENTS,
    Event,
    Handler,
    InstallFinished,
    Subscription,
    TrialsChanged,
    UpdateFinished,
    UpdateStarted,
)
from tri_al.pipeline.pipeline import Pipeline, PipelineError
from tri_al.pipeline.prepare import content_hash, prepare
from tri_al.pipeline.source import (
    FetchContext,
    FetchError,
    Progress,
    ProgressCallback,
    Source,
    ignore_progress,
)
from tri_al.pipeline.summary import (
    EmbeddingSummary,
    RenormalizeSummary,
    RunSummary,
    SourceCounts,
    StatsSummary,
)

__all__ = [
    "EVENTS",
    "EmbeddingSummary",
    "Event",
    "FetchContext",
    "FetchError",
    "Handler",
    "InstallFinished",
    "Pipeline",
    "PipelineError",
    "Progress",
    "ProgressCallback",
    "RenormalizeSummary",
    "RunSummary",
    "Source",
    "SourceCounts",
    "StatsSummary",
    "Subscription",
    "TrialsChanged",
    "UpdateFinished",
    "UpdateStarted",
    "content_hash",
    "ignore_progress",
    "prepare",
]
