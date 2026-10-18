"""Job progress: the pipeline reports often, ``app.db`` hears at most twice a second (§5.4)."""

import threading
import time
from collections.abc import Callable
from types import TracebackType
from typing import Self

from tri_al.jobs.queue import JobCancelled, JobQueue
from tri_al.pipeline import Progress, ProgressCallback

WRITE_INTERVAL = 0.5
"""Seconds between writes of a job's row: progress and heartbeats together."""

HEARTBEAT_INTERVAL = 5.0
"""Seconds between heartbeats while a job reports no progress (a long index build, say)."""


class JobProgress:
    """A pipeline progress callback that keeps a running job's row up to date.

    Reports are kept in memory and written at most once every ``interval`` seconds; a
    report that arrives too soon is written by the heartbeat thread a moment later, so the
    last state of every stage still reaches the row. Use it as a context manager, which
    runs that thread and writes a heartbeat every ``heartbeat`` seconds while reports are
    quiet. A report raises JobCancelled once someone asks to cancel the job.
    """

    def __init__(
        self,
        queue: JobQueue,
        job_id: int,
        *,
        interval: float = WRITE_INTERVAL,
        heartbeat: float = HEARTBEAT_INTERVAL,
        also: ProgressCallback | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._queue = queue
        self._job_id = job_id
        self._interval = interval
        self._heartbeat = heartbeat
        self._also = also
        self._clock = clock
        self._lock = threading.Lock()
        self._pending: Progress | None = None
        self._last_write = float("-inf")
        self._cancel = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.writes = 0

    def __call__(self, progress: Progress) -> None:
        if self._also is not None:
            self._also(progress)
        with self._lock:
            self._pending = progress
            if self._clock() - self._last_write >= self._interval:
                self._write()
            cancel = self._cancel
        if cancel:
            raise JobCancelled(f"job {self._job_id} was cancelled")

    def tick(self) -> None:
        """Write a report held back, or a heartbeat if nothing was written for a while."""
        with self._lock:
            since = self._clock() - self._last_write
            if (self._pending is not None and since >= self._interval) or since >= self._heartbeat:
                self._write()

    def flush(self) -> None:
        """Write the latest report now, whatever the interval."""
        with self._lock:
            if self._pending is not None:
                self._write()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel

    def _write(self) -> None:
        self._cancel = self._queue.report(self._job_id, self._pending) or self._cancel
        self._pending = None
        self._last_write = self._clock()
        self.writes += 1

    def __enter__(self) -> Self:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"job-{self._job_id}-heartbeat", daemon=True
        )
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        self.flush()

    def _run(self) -> None:
        step = min(self._interval, self._heartbeat) / 2
        while not self._stop.wait(step):
            try:
                self.tick()
            except Exception:  # the database is busy or gone; the next tick tries again
                continue
