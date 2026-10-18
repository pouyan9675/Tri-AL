"""``/api/events``: server-sent events for data version changes and job progress (§5.9).

Each API worker runs one poller while anyone listens. Every ``interval`` seconds it reads
the data version from ``trials.db`` and the jobs changed since its last look from
``app.db`` (both tiny queries), and passes what changed to every open stream. The worker
process writes progress at most twice a second, so a poll every half second shows it all.

Events (``event:`` names; ``data:`` is JSON):

- ``hello``: on connecting, ``{"data_version": n, "jobs": [active jobs]}``
- ``data_version``: ``{"data_version": n}`` when an update or install committed
- ``job``: a job (as ``GET /api/jobs/{id}``) whenever it changes
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import orjson
from fastapi import Request

from tri_al.api.state import ApiState
from tri_al.jobs import Job

log = logging.getLogger(__name__)

POLL_INTERVAL = 0.5
_BEGINNING = datetime(1970, 1, 1, tzinfo=UTC)
KEEPALIVE = 15.0
"""Seconds between comments on a quiet stream, so proxies keep it open."""


def job_json(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "type": job.type,
        "status": job.status,
        "origin": job.origin,
        "stage": job.stage,
        "progress": job.progress,
        "total": job.total,
        "unit": job.unit,
        "message": job.message,
        "error": job.error,
        "cancel_requested": job.cancel_requested,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "heartbeat": job.heartbeat,
        "result": job.result,
    }


def format_event(event: str, data: Any) -> bytes:
    return b"event: " + event.encode() + b"\ndata: " + orjson.dumps(data) + b"\n\n"


class EventHub:
    def __init__(self, state: ApiState, *, interval: float = POLL_INTERVAL) -> None:
        self._state = state
        self._interval = interval
        self._listeners: set[asyncio.Queue[bytes]] = set()
        self._data_version: int | None = None
        self._jobs_seen: datetime | None = None
        self._task: asyncio.Task[None] | None = None

    def data_version(self) -> int:
        storage = self._state.storage()
        if storage is None:
            return 0
        with storage.read() as reader:
            return reader.data_version()

    def _poll(self) -> list[bytes]:
        events: list[bytes] = []
        version = self.data_version()
        if self._data_version is not None and version != self._data_version:
            events.append(format_event("data_version", {"data_version": version}))
        self._data_version = version
        # A hub that started before any job existed must still see jobs that came and
        # went between two polls, so it asks for every change since the beginning.
        for job in self._state.queue.changed_since(self._jobs_seen or _BEGINNING):
            if job.updated_at is not None and (
                self._jobs_seen is None or job.updated_at > self._jobs_seen
            ):
                self._jobs_seen = job.updated_at
            events.append(format_event("job", job_json(job)))
        return events

    async def run(self) -> None:
        """Poll while anyone listens; started by the first stream, until cancelled."""
        while True:
            if self._listeners:
                try:
                    events = await asyncio.to_thread(self._poll)
                except Exception:
                    log.exception("events: polling failed")
                    events = []
                for listener in list(self._listeners):
                    for event in events:
                        listener.put_nowait(event)
            await asyncio.sleep(self._interval)

    async def subscribe(self) -> asyncio.Queue[bytes]:
        if self._task is None or self._task.done():
            self._jobs_seen = await asyncio.to_thread(self._state.queue.last_change)
            self._data_version = await asyncio.to_thread(self.data_version)
            self._task = asyncio.create_task(self.run())
        listener: asyncio.Queue[bytes] = asyncio.Queue()
        self._listeners.add(listener)
        return listener

    def unsubscribe(self, listener: asyncio.Queue[bytes]) -> None:
        self._listeners.discard(listener)

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def hello(self) -> bytes:
        jobs = [job_json(job) for job in self._state.queue.changed_since(None)]
        return format_event("hello", {"data_version": self.data_version(), "jobs": jobs})


async def stream(request: Request, hub: EventHub, max_events: int | None) -> AsyncIterator[bytes]:
    listener = await hub.subscribe()
    try:
        yield await asyncio.to_thread(hub.hello)
        sent = 0
        while max_events is None or sent < max_events:
            try:
                event = await asyncio.wait_for(listener.get(), KEEPALIVE)
            except TimeoutError:
                if await request.is_disconnected():
                    break
                yield b": keep-alive\n\n"
                continue
            yield event
            sent += 1
    finally:
        hub.unsubscribe(listener)
