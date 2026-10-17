"""Raw documents to records: parse, hash and normalize (docs/design.md §5.3).

Installs do this in a pool of worker processes, since normalizing 600k studies is
CPU-bound; updates are small enough to do it in-process.
"""

import hashlib
import itertools
import multiprocessing
import os
from collections import deque
from collections.abc import Iterable, Iterator
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any

import orjson

from trial_al.pipeline.source import Source
from trial_al.schema import TrialRecord

HASH_SIZE = 16
"""Bytes of BLAKE2b digest kept as ``content_hash``: plenty to tell versions apart."""

CHUNK_SIZE = 200
"""Documents sent to a worker at a time."""


@dataclass(frozen=True, slots=True)
class Prepared:
    """A record ready to store, or why the document couldn't become one."""

    record: TrialRecord | None = None
    error: str | None = None


def content_hash(source: Source, parsed: dict[str, Any]) -> bytes:
    """BLAKE2b of the document's hashable part, serialized with sorted keys.

    Sorting makes the hash independent of key order, so the same study from the bulk
    download and from the API hashes the same.
    """
    canonical = orjson.dumps(source.hashable(parsed), option=orjson.OPT_SORT_KEYS)
    return hashlib.blake2b(canonical, digest_size=HASH_SIZE).digest()


def prepare(source: Source, raw: bytes) -> Prepared:
    """Parse, hash and normalize one raw document. Never raises: errors are returned."""
    try:
        parsed = orjson.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
        record = source.normalize(parsed)
        if record.source != source.name:
            raise ValueError(f"normalize made a record for source {record.source!r}")
        record.raw = raw
        record.content_hash = content_hash(source, parsed)
    except Exception as exc:
        # A bug or a surprise in one study shouldn't stop an install of 600k.
        return Prepared(error=f"{type(exc).__name__}: {exc}")
    return Prepared(record=record)


def default_workers() -> int:
    """Worker processes for an install: one per spare CPU, at most 8.

    The single database writer is the bottleneck, so more workers than this sit idle.
    """
    return max(1, min(8, (os.cpu_count() or 2) - 1))


def prepared(source: Source, raws: Iterable[bytes], *, workers: int) -> Iterator[Prepared]:
    """``prepare`` each document, in order; with ``workers`` > 0, in that many processes.

    Documents are read from ``raws`` only as fast as the workers keep up, so memory stays
    bounded however many there are.
    """
    if workers <= 0:
        for raw in raws:
            yield prepare(source, raw)
        return
    # spawn, not fork: forking a process that has threads (the database pool, httpx) can
    # deadlock, and it's what macOS and Windows use anyway.
    pool = ProcessPoolExecutor(
        workers,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_start_worker,
        initargs=(source,),
    )
    try:
        pending: deque[Future[list[Prepared]]] = deque()
        for chunk in itertools.batched(raws, CHUNK_SIZE, strict=False):
            pending.append(pool.submit(_prepare_chunk, chunk))
            if len(pending) >= workers * 4:
                yield from pending.popleft().result()
        while pending:
            yield from pending.popleft().result()
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


_worker_source: Source | None = None


def _start_worker(source: Source) -> None:
    global _worker_source
    _worker_source = source


def _prepare_chunk(raws: tuple[bytes, ...]) -> list[Prepared]:
    assert _worker_source is not None
    return [prepare(_worker_source, raw) for raw in raws]
