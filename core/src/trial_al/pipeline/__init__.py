"""The data pipeline (docs/design.md §5.3): sources, install, update and their events."""

from trial_al.pipeline.events import (
    EVENTS,
    Event,
    Handler,
    InstallFinished,
    Subscription,
    TrialsChanged,
    UpdateFinished,
    UpdateStarted,
)
from trial_al.pipeline.pipeline import Pipeline, PipelineError
from trial_al.pipeline.prepare import content_hash, prepare
from trial_al.pipeline.source import (
    FetchContext,
    FetchError,
    Progress,
    ProgressCallback,
    Source,
    ignore_progress,
)
from trial_al.pipeline.summary import RunSummary, SourceCounts

__all__ = [
    "EVENTS",
    "Event",
    "FetchContext",
    "FetchError",
    "Handler",
    "InstallFinished",
    "Pipeline",
    "PipelineError",
    "Progress",
    "ProgressCallback",
    "RunSummary",
    "Source",
    "SourceCounts",
    "Subscription",
    "TrialsChanged",
    "UpdateFinished",
    "UpdateStarted",
    "content_hash",
    "ignore_progress",
    "prepare",
]
