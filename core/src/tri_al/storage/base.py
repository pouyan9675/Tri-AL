"""The storage contract (docs/design.md §5.2). Backends must pass ``tri_al.testing``."""

from collections.abc import Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol, Self

from sqlalchemy import Connection

from tri_al.filters import EVERY_TRIAL, TrialFilter
from tri_al.schema import TrialRecord

type NameKind = Literal["condition", "intervention", "sponsor"]
type SortKey = Literal["last_update", "start_date", "first_posted", "enrollment", "id"]

SORT_KEYS: tuple[SortKey, ...] = ("last_update", "start_date", "first_posted", "enrollment", "id")


class StorageError(Exception):
    """The database can't be used: too old, the wrong schema, or in the wrong state."""


@dataclass(frozen=True, slots=True)
class Sort:
    """How a trial list is ordered: by ``key``, ties broken by ``id`` in the same direction.

    Trials without a value (no start date, say) come last when descending and first when
    ascending. ``id`` follows registration order for a single source.
    """

    key: SortKey = "last_update"
    descending: bool = True

    @classmethod
    def parse(cls, text: str) -> Self:
        """``last_update`` (ascending) or ``-last_update`` (descending)."""
        name = text.removeprefix("-")
        for key in SORT_KEYS:
            if key == name:
                return cls(key, text.startswith("-"))
        raise ValueError(f"can't sort by {name!r}; use one of {', '.join(SORT_KEYS)}")

    def __str__(self) -> str:
        return f"-{self.key}" if self.descending else self.key


NEWEST_FIRST = Sort()

type Cursor = tuple[Any, int]
"""Where a page ends: the last trial's sort value (ISO text for dates) and its id."""


@dataclass(frozen=True, slots=True)
class TrialSummary:
    """The columns a trial list shows."""

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
    conditions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TrialPage:
    items: list[TrialSummary]
    next: Cursor | None  # pass as ``after`` for the next page; None on the last page


@dataclass(frozen=True, slots=True)
class SnippetPart:
    text: str
    match: bool  # the text matched the query


@dataclass(frozen=True, slots=True)
class SearchHit:
    id: int
    source: str
    source_id: str
    title: str
    status: str | None
    phase: str | None
    score: float  # higher is a better match; only comparable within one search
    snippet: tuple[SnippetPart, ...] = ()


@dataclass(frozen=True, slots=True)
class SearchResult:
    """The best hits, from at most ``SEARCH_CANDIDATES`` ranked candidates.

    ``capped`` means more trials matched than were ranked: the candidates are the most
    recently registered matches, so a more specific query finds older trials.
    """

    hits: list[SearchHit]
    candidates: int
    capped: bool


@dataclass(frozen=True, slots=True)
class NameHit:
    kind: NameKind
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class TrialChange:
    """One field an update changed, with the values as JSON-compatible data."""

    run_id: int
    changed_at: datetime | None  # when the update finished
    field: str
    old: Any
    new: Any


class StorageTransaction(Protocol):
    """Writes that commit together, or not at all."""

    @property
    def connection(self) -> Connection:
        """The transaction's connection, for writing other tables in the same transaction."""
        ...

    def get_trial(self, trial_id: int) -> TrialRecord | None: ...

    def find_trial(self, source: str, source_id: str) -> TrialRecord | None: ...

    def content_hashes(
        self, source: str, source_ids: Iterable[str] | None = None
    ) -> dict[str, bytes | None]:
        """Stored ``content_hash`` by ``source_id``, for every trial of ``source`` or those listed.

        Trials that aren't stored are left out. The pipeline compares these with fresh hashes
        to skip trials that haven't changed.
        """
        ...

    def upsert_batch(self, records: Sequence[TrialRecord]) -> list[int]:
        """Insert new trials and replace existing ones (matched on ``(source, source_id)``).

        Returns the trials' ids in input order. An existing trial keeps its id, and
        everything about it is replaced, lists included. Raises ValueError, writing nothing,
        if the batch has two records for one trial or uses an unknown country code.
        """
        ...


class BulkLoader(Protocol):
    def content_hashes(
        self, source: str, source_ids: Iterable[str] | None = None
    ) -> dict[str, bytes | None]:
        """Like ``Storage.content_hashes``; a resumed load uses it to skip what it already wrote."""
        ...

    def upsert_batch(self, records: Sequence[TrialRecord]) -> list[int]:
        """Like ``StorageTransaction.upsert_batch``; each batch commits on its own."""
        ...


class Storage(Protocol):
    def get_trial(self, trial_id: int) -> TrialRecord | None: ...

    def find_trial(self, source: str, source_id: str) -> TrialRecord | None: ...

    def content_hashes(
        self, source: str, source_ids: Iterable[str] | None = None
    ) -> dict[str, bytes | None]:
        """``StorageTransaction.content_hashes``, reading the last commit."""
        ...

    def query_trials(
        self,
        filter: TrialFilter = EVERY_TRIAL,
        *,
        sort: Sort = NEWEST_FIRST,
        after: Cursor | None = None,
        limit: int = 100,
    ) -> TrialPage:
        """The trials ``filter`` matches, in ``sort`` order, starting after ``after``."""
        ...

    def count_trials(self, filter: TrialFilter = EVERY_TRIAL) -> int: ...

    def search(
        self, text: str, *, filter: TrialFilter = EVERY_TRIAL, limit: int = 20
    ) -> SearchResult:
        """Full-text search over titles, text, conditions and interventions, best first.

        ``text`` is plain words, all of which must match (after stemming); query syntax
        characters are treated as spaces. Hits carry a snippet of the text they matched.
        """
        ...

    def lookup_names(
        self, text: str, *, kind: NameKind | None = None, limit: int = 20
    ) -> list[NameHit]:
        """Condition, intervention and sponsor names containing every word of ``text``.

        Matching ignores case and accents, shorter names first. Words shorter than three
        letters only match at the start of a name.
        """
        ...

    def upsert_batch(self, records: Sequence[TrialRecord]) -> list[int]:
        """``StorageTransaction.upsert_batch`` in a transaction of its own."""
        ...

    def transaction(self) -> AbstractContextManager[StorageTransaction]:
        """A write transaction. It commits when the block exits normally."""
        ...

    def bulk_load(self) -> AbstractContextManager[BulkLoader]:
        """Fast loading for install and rebuild, into a database nobody else is using.

        Secondary indexes are dropped at the start and rebuilt when the block exits
        normally. If it raises, they stay missing and ``transaction`` refuses to run until
        a bulk load finishes, so restart the bulk load.
        """
        ...

    def close(self) -> None: ...
