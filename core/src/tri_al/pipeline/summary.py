"""What a pipeline run did: the result of ``run_install`` and ``run_update``."""

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

type RunKind = Literal["install", "update"]

MAX_FAILURES = 100
"""Problem messages a summary keeps; ``SourceCounts.failed`` still counts every one."""


@dataclass(kw_only=True)
class SourceCounts:
    """What happened to one source's studies.

    ``fetched`` counts every document the source yielded. Each one ends up ``new``,
    ``updated``, ``unchanged`` (its content hash matched) or ``failed`` (it didn't parse or
    normalize); a study fetched twice in one run counts once in those four.
    """

    fetched: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0


@dataclass(kw_only=True)
class RunSummary:
    run_id: int
    kind: RunKind
    data_version: int = 0
    sources: dict[str, SourceCounts] = field(default_factory=dict)
    stages: dict[str, float] = field(default_factory=dict)  # seconds each stage took
    failures: list[str] = field(default_factory=list)  # the first MAX_FAILURES problems
    handler_errors: list[str] = field(default_factory=list)  # event handlers that raised
    stats_errors: list[str] = field(default_factory=list)  # charts that failed to precompute
    notes: dict[str, Any] = field(default_factory=dict)  # FetchContext.notes, by source

    def counts(self, source: str) -> SourceCounts:
        return self.sources.setdefault(source, SourceCounts())

    def add_failure(self, source: str, message: str) -> None:
        self.counts(source).failed += 1
        if len(self.failures) < MAX_FAILURES:
            self.failures.append(f"{source}: {message}")

    @property
    def new(self) -> int:
        return sum(counts.new for counts in self.sources.values())

    @property
    def updated(self) -> int:
        return sum(counts.updated for counts in self.sources.values())

    @property
    def unchanged(self) -> int:
        return sum(counts.unchanged for counts in self.sources.values())

    @property
    def failed(self) -> int:
        return sum(counts.failed for counts in self.sources.values())

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(kw_only=True)
class EmbeddingSummary:
    """What ``run_embedding_backfill`` did."""

    engine: str
    model: str
    trials: int = 0  # vectors written
    skipped: int = 0  # trials that changed while being embedded; their update embedded them
    data_version: int = 0
    stages: dict[str, float] = field(default_factory=dict)  # seconds: model, embed, stats
    stats_errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(kw_only=True)
class RenormalizeSummary:
    """What ``run_renormalize`` did, in trials."""

    trials: int = 0  # read
    unchanged: int = 0
    rewritten: int = 0  # columns and text, in place
    replaced: int = 0  # written in full and embedded again
    skipped: int = 0  # no raw document, or their source isn't enabled
    failed: int = 0  # their document didn't normalize
    failures: list[str] = field(default_factory=list)  # the first MAX_FAILURES problems
    embedding_error: str | None = None
    data_version: int = 0
    stages: dict[str, float] = field(default_factory=dict)  # seconds: normalize, stats
    stats_errors: list[str] = field(default_factory=list)

    def add_failure(self, message: str) -> None:
        self.failed += 1
        if len(self.failures) < MAX_FAILURES:
            self.failures.append(message)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(kw_only=True)
class StatsSummary:
    """What ``run_stats`` did."""

    data_version: int = 0
    stages: dict[str, float] = field(default_factory=dict)  # seconds
    stats_errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
