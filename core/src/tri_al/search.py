"""Search providers behind ``/api/search`` (docs/design.md §5.9, §7 and §12).

The core ships ``FullTextProvider`` (FTS5 over ``trials_fts``). Plugins add others, such as
semantic search, with ``registry.add_search_provider``. Every provider finds and ranks
trial ids; the API merges their lists and storage adds titles and snippets to the winners.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sqlalchemy import Connection

from tri_al.filters import TrialFilter
from tri_al.storage.sqlite import SEARCH_CANDIDATES, rank_matches

RRF_K = 60
"""Reciprocal rank fusion's constant: a hit's merged score is the sum of 1 / (k + rank)."""


@dataclass(frozen=True, slots=True)
class Hit:
    id: int  # trials.id
    score: float  # higher is better; only comparable within one provider's results


@dataclass(frozen=True, slots=True)
class ProviderResult:
    hits: list[Hit]
    candidates: int | None = None  # how many matches were ranked, if the provider knows
    capped: bool = False  # more matched than were ranked


@runtime_checkable
class SearchProvider(Protocol):
    @property
    def name(self) -> str: ...

    def search(self, conn: Connection, q: str, filter: TrialFilter, limit: int) -> ProviderResult:
        """The best ``limit`` trials for ``q`` among those ``filter`` matches, best first."""
        ...


class FullTextProvider:
    """Full-text search with FTS5: every word must match; BM25 with column weights."""

    name = "fts"

    def search(self, conn: Connection, q: str, filter: TrialFilter, limit: int) -> ProviderResult:
        scored, candidates = rank_matches(conn, q, filter=filter, limit=limit)
        return ProviderResult(
            [Hit(trial_id, score) for trial_id, score in scored],
            candidates,
            candidates >= SEARCH_CANDIDATES,
        )


def merge(results: Mapping[str, ProviderResult], limit: int) -> list[Hit]:
    """One ranking from several providers' (reciprocal rank fusion), or the only one's."""
    lists = [result.hits for result in results.values() if result.hits]
    if len(lists) <= 1:
        return (lists[0] if lists else [])[:limit]
    scores: dict[int, float] = {}
    for hits in lists:
        for rank, hit in enumerate(hits, start=1):
            scores[hit.id] = scores.get(hit.id, 0.0) + 1 / (RRF_K + rank)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [Hit(trial_id, score) for trial_id, score in ranked[:limit]]
