"""What a source plugin implements, and what the pipeline hands it (docs/design.md §7)."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from tri_al.schema import TrialRecord


class FetchError(Exception):
    """A source couldn't fetch: the network or the registry failed, or a download is bad.

    Sources raise it (or a subclass) instead of their HTTP client's own errors, so callers
    can report it without knowing the client.
    """


@dataclass(frozen=True, slots=True)
class Progress:
    """One progress report: ``done`` of ``total`` (None if unknown) in ``unit``, for ``stage``.

    Install stages are ``download`` (reported by the source), ``load``, ``index``, ``enrich``,
    ``stats``, ``check`` and ``swap``; update stages are ``fetch``, ``write``, ``enrich``,
    ``stats`` and ``commit``. A stage reports ``done=0`` when it starts, and may report more
    often than anyone wants to show, so a display should throttle.
    """

    stage: str
    done: int = 0
    total: int | None = None
    unit: str = ""
    message: str = ""


type ProgressCallback = Callable[[Progress], None]


def ignore_progress(progress: Progress) -> None:
    pass


@dataclass(kw_only=True)
class FetchContext:
    """What a fetch gets from the pipeline, and how it reports back.

    ``downloads`` is a directory the source may keep downloads in. ``from_file`` is a local
    copy of the source's bulk download for ``fetch_all`` to read instead of downloading one.
    ``reuse_download`` says a complete download from an earlier attempt may be used: the
    pipeline sets it when it resumes an install.

    The source may set ``total`` to the number of studies it will yield, so the pipeline can
    show a percentage, and may put facts worth keeping in ``notes`` (such as the download's
    checksum or the data's date); the run summary records them under the source's name.
    """

    downloads: Path
    progress: ProgressCallback = ignore_progress
    from_file: Path | None = None
    reuse_download: bool = False
    total: int | None = None
    notes: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Source(Protocol):
    """A registry that trials come from, such as ClinicalTrials.gov.

    The pipeline sends the source to worker processes to normalize in parallel, so it must
    be picklable (keep clients and open files out of its attributes) and ``normalize`` and
    ``hashable`` must be pure.
    """

    @property
    def name(self) -> str:
        """The ``TrialRecord.source`` of every record it makes, such as ``"ctgov"``."""
        ...

    def fetch_all(self, ctx: FetchContext) -> Iterator[bytes]:
        """Every study, each one's raw JSON document."""
        ...

    def fetch_changed(self, since: date, ctx: FetchContext) -> Iterator[bytes]:
        """The studies updated on or after ``since``, each one's raw JSON document."""
        ...

    def normalize(self, raw: dict[str, Any]) -> TrialRecord:
        """The trial in a parsed raw document. Raise ValueError if it can't be read."""
        ...

    def hashable(self, raw: dict[str, Any]) -> Any:
        """The part of a parsed raw document that a new version of the study changes.

        The pipeline hashes it to skip studies that haven't changed, so leave out fields
        that change without the study changing, such as the date of the data snapshot.
        Return ``raw`` itself if there are none. Don't change ``raw``.
        """
        ...
