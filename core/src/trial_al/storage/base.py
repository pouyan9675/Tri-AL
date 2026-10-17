"""The storage contract (docs/design.md §5.2). Backends must pass ``trial_al.testing``."""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from sqlalchemy import Connection

from trial_al.schema import TrialRecord

type NameKind = Literal["condition", "intervention", "sponsor"]


class StorageError(Exception):
    """The database can't be used: too old, the wrong schema, or in the wrong state."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TrialQuery:
    """A basic trial filter. ``None`` means "any"; a tuple matches any of its values.

    Results are ordered by ``id``. Page with ``after_id``, the last ``id`` of the previous
    page. The full ``TrialFilter`` replaces this in milestone 4.
    """

    status: tuple[str, ...] | None = None
    phase: tuple[str, ...] | None = None
    after_id: int | None = None
    limit: int = 100


@dataclass(frozen=True, slots=True)
class TrialSummary:
    """The columns a trial list shows, read from the narrow ``trials`` table only."""

    id: int
    source: str
    source_id: str
    title: str
    status: str | None
    phase: str | None
    start_date: date | None
    last_update: date | None
    enrollment: int | None


@dataclass(frozen=True, slots=True)
class SearchHit:
    id: int
    source: str
    source_id: str
    title: str
    score: float  # higher is a better match; only comparable within one search


@dataclass(frozen=True, slots=True)
class NameHit:
    kind: NameKind
    id: int
    name: str


ALL_TRIALS = TrialQuery()


class StorageTransaction(Protocol):
    """Writes that commit together, or not at all."""

    @property
    def connection(self) -> Connection:
        """The transaction's connection, for writing other tables in the same transaction."""
        ...

    def get_trial(self, trial_id: int) -> TrialRecord | None: ...

    def find_trial(self, source: str, source_id: str) -> TrialRecord | None: ...

    def upsert_batch(self, records: Sequence[TrialRecord]) -> list[int]:
        """Insert new trials and replace existing ones (matched on ``(source, source_id)``).

        Returns the trials' ids in input order. An existing trial keeps its id, and
        everything about it is replaced, lists included. Raises ValueError, writing nothing,
        if the batch has two records for one trial or uses an unknown country code.
        """
        ...


class BulkLoader(Protocol):
    def upsert_batch(self, records: Sequence[TrialRecord]) -> list[int]:
        """Like ``StorageTransaction.upsert_batch``; each batch commits on its own."""
        ...


class Storage(Protocol):
    def get_trial(self, trial_id: int) -> TrialRecord | None: ...

    def find_trial(self, source: str, source_id: str) -> TrialRecord | None: ...

    def query_trials(self, query: TrialQuery = ALL_TRIALS) -> list[TrialSummary]: ...

    def count_trials(self, query: TrialQuery = ALL_TRIALS) -> int:
        """How many trials match, ignoring ``after_id`` and ``limit``."""
        ...

    def search(self, text: str, *, limit: int = 20) -> list[SearchHit]:
        """Full-text search over titles, text, conditions and interventions, best first.

        ``text`` is plain words, all of which must match (after stemming); query syntax
        characters are treated as spaces.
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

        Secondary indexes and full-text search are dropped at the start and rebuilt when the
        block exits normally. If it raises, they stay missing and ``transaction`` refuses to
        run until a bulk load finishes, so restart the bulk load.
        """
        ...

    def close(self) -> None: ...
