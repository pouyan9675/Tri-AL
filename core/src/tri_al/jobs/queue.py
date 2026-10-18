"""The job queue: the ``jobs`` table in ``app.db`` (docs/design.md §5.4).

A job is queued by the API, the schedule or a plugin, and claimed by the worker with one
``UPDATE … RETURNING``. A command run from the shell (``tri-al update``) records itself as a
running job too, so it holds the same lock. Only one data job (install, update or rebuild)
runs at a time: ``claim`` skips them while one runs, and a partial unique index on ``jobs``
makes sure of it.
"""

import json
import os
import socket
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Connection, Engine, Row, and_, exists, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from tri_al.pipeline import Progress
from tri_al.storage import tables as t
from tri_al.storage.engine import BEGIN
from tri_al.storage.tables import DATA_JOB_TYPES

type JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
type JobOrigin = Literal["api", "schedule", "cli", "plugin"]

ACTIVE: tuple[JobStatus, ...] = ("queued", "running")
FINISHED: tuple[JobStatus, ...] = ("succeeded", "failed", "cancelled")


class JobConflict(Exception):
    """A data job is already queued or running, so another can't start."""

    def __init__(self, existing: "Job") -> None:
        super().__init__(
            f"{existing.type} job {existing.id} is already {existing.status}; only one install, "
            "update or rebuild runs at a time"
        )
        self.existing = existing


class JobCancelled(Exception):
    """Raised from a job's progress callback once someone asked to cancel it."""


@dataclass(frozen=True, slots=True)
class Job:
    id: int
    type: str
    status: JobStatus
    origin: str
    stage: str | None
    progress: int
    total: int | None
    unit: str | None
    message: str | None
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    cancel_requested: bool
    worker: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat: datetime | None
    updated_at: datetime | None

    @property
    def is_data_job(self) -> bool:
        return self.type in DATA_JOB_TYPES

    @property
    def active(self) -> bool:
        return self.status in ACTIVE

    @classmethod
    def from_row(cls, row: Row[Any]) -> "Job":
        m = row._mapping
        return cls(
            id=m["id"],
            type=m["type"],
            status=m["status"],
            origin=m["origin"],
            stage=m["stage"],
            progress=m["progress"],
            total=m["total"],
            unit=m["unit"],
            message=m["message"],
            payload=json.loads(m["payload"]) if m["payload"] else {},
            result=json.loads(m["result"]) if m["result"] else None,
            error=m["error"],
            cancel_requested=bool(m["cancel_requested"]),
            worker=m["worker"],
            created_at=m["created_at"],
            started_at=m["started_at"],
            finished_at=m["finished_at"],
            heartbeat=m["heartbeat"],
            updated_at=m["updated_at"],
        )


def worker_name() -> str:
    """This process, as a job's ``worker``: ``host:pid``."""
    return f"{socket.gethostname()}:{os.getpid()}"


class JobQueue:
    """Jobs in ``app.db``. Thread-safe; every method is one short transaction."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @property
    def engine(self) -> Engine:
        return self._engine

    # --- adding and claiming ----------------------------------------------------------------

    def enqueue(
        self, type: str, payload: dict[str, Any] | None = None, *, origin: JobOrigin = "api"
    ) -> Job:
        """Queue a job. Raises JobConflict for a data job while another is queued or running."""
        now = _now()
        with self._write() as conn:
            if type in DATA_JOB_TYPES:
                self._check_no_data_job(conn)
            row = conn.execute(
                insert(t.jobs)
                .values(
                    type=type,
                    status="queued",
                    origin=origin,
                    payload=json.dumps(payload or {}),
                    created_at=now,
                    updated_at=now,
                )
                .returning(*t.jobs.c)
            ).one()
        return Job.from_row(row)

    def start(
        self,
        type: str,
        payload: dict[str, Any] | None = None,
        *,
        origin: JobOrigin = "cli",
        worker: str | None = None,
    ) -> Job:
        """Record a job this process runs itself, already running (``tri-al update`` does)."""
        now = _now()
        try:
            with self._write() as conn:
                if type in DATA_JOB_TYPES:
                    self._check_no_data_job(conn)
                row = conn.execute(
                    insert(t.jobs)
                    .values(
                        type=type,
                        status="running",
                        origin=origin,
                        payload=json.dumps(payload or {}),
                        worker=worker or worker_name(),
                        created_at=now,
                        started_at=now,
                        heartbeat=now,
                        updated_at=now,
                    )
                    .returning(*t.jobs.c)
                ).one()
        except IntegrityError:
            running = self.active_data_job()
            if running is None:
                raise
            raise JobConflict(running) from None
        return Job.from_row(row)

    def claim(self, worker: str | None = None) -> Job | None:
        """Start the oldest queued job that can run now, or return None.

        Data jobs wait while another data job runs; other jobs don't wait for them.
        """
        running = t.jobs.alias("running")
        data_job_running = exists().where(
            running.c.status == "running", running.c.type.in_(DATA_JOB_TYPES)
        )
        candidate = (
            select(t.jobs.c.id)
            .where(
                t.jobs.c.status == "queued",
                or_(t.jobs.c.type.not_in(DATA_JOB_TYPES), ~data_job_running),
            )
            .order_by(t.jobs.c.id)
            .limit(1)
            .scalar_subquery()
        )
        now = _now()
        try:
            with self._write() as conn:
                row = conn.execute(
                    update(t.jobs)
                    .where(t.jobs.c.id == candidate)
                    .values(
                        status="running",
                        worker=worker or worker_name(),
                        started_at=now,
                        heartbeat=now,
                        updated_at=now,
                    )
                    .returning(*t.jobs.c)
                ).one_or_none()
        except IntegrityError:
            return None  # a shell command started a data job at the same moment
        return None if row is None else Job.from_row(row)

    # --- while running ----------------------------------------------------------------------

    def report(self, job_id: int, progress: Progress | None) -> bool:
        """Record ``progress`` (None: only the heartbeat); return whether cancelling was asked."""
        now = _now()
        values: dict[str, Any] = {"heartbeat": now, "updated_at": now}
        if progress is not None:
            values |= {
                "stage": progress.stage,
                "progress": progress.done,
                "total": progress.total,
                "unit": progress.unit or None,
                "message": progress.message or None,
            }
        with self._write() as conn:
            cancel = conn.execute(
                update(t.jobs)
                .where(t.jobs.c.id == job_id, t.jobs.c.status == "running")
                .values(**values)
                .returning(t.jobs.c.cancel_requested)
            ).scalar_one_or_none()
        return bool(cancel)

    def finish(self, job_id: int, result: dict[str, Any] | None = None) -> Job:
        return self._end(job_id, "succeeded", result=result)

    def fail(self, job_id: int, error: str, result: dict[str, Any] | None = None) -> Job:
        return self._end(job_id, "failed", error=error, result=result)

    def cancelled(self, job_id: int) -> Job:
        return self._end(job_id, "cancelled", error="cancelled")

    def cancel(self, job_id: int) -> Job | None:
        """Cancel a queued job, or ask a running one to stop at its next progress report."""
        now = _now()
        with self._write() as conn:
            conn.execute(
                update(t.jobs)
                .where(t.jobs.c.id == job_id, t.jobs.c.status == "queued")
                .values(status="cancelled", error="cancelled", finished_at=now, updated_at=now)
            )
            conn.execute(
                update(t.jobs)
                .where(t.jobs.c.id == job_id, t.jobs.c.status == "running")
                .values(cancel_requested=True, updated_at=now)
            )
        return self.get(job_id)

    def recover(self, stale_after: timedelta) -> list[Job]:
        """Fail running jobs whose heartbeat stopped ``stale_after`` ago; return them.

        A worker that crashed or was killed leaves its job running; the next worker to start
        finds it here.
        """
        now = _now()
        cutoff = now - stale_after
        with self._write() as conn:
            rows = conn.execute(
                update(t.jobs)
                .where(
                    t.jobs.c.status == "running",
                    or_(t.jobs.c.heartbeat.is_(None), t.jobs.c.heartbeat < cutoff),
                )
                .values(
                    status="failed",
                    error=(
                        "the process running it stopped (no heartbeat for "
                        f"{int(stale_after.total_seconds())}s)"
                    ),
                    finished_at=now,
                    updated_at=now,
                )
                .returning(*t.jobs.c)
            ).all()
        return [Job.from_row(row) for row in rows]

    # --- reading ----------------------------------------------------------------------------

    def get(self, job_id: int) -> Job | None:
        with self._engine.connect() as conn:
            row = conn.execute(select(t.jobs).where(t.jobs.c.id == job_id)).one_or_none()
        return None if row is None else Job.from_row(row)

    def recent(self, limit: int = 20, *, types: Sequence[str] | None = None) -> list[Job]:
        """The newest jobs first."""
        stmt = select(t.jobs).order_by(t.jobs.c.id.desc()).limit(limit)
        if types is not None:
            stmt = stmt.where(t.jobs.c.type.in_(types))
        with self._engine.connect() as conn:
            return [Job.from_row(row) for row in conn.execute(stmt)]

    def active_data_job(self) -> Job | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                select(t.jobs)
                .where(t.jobs.c.status.in_(ACTIVE), t.jobs.c.type.in_(DATA_JOB_TYPES))
                .order_by(t.jobs.c.status.desc(), t.jobs.c.id)  # running before queued
                .limit(1)
            ).one_or_none()
        return None if row is None else Job.from_row(row)

    def changed_since(self, since: datetime | None, *, limit: int = 50) -> list[Job]:
        """Jobs changed after ``since`` (all active jobs if None), oldest change first."""
        stmt = select(t.jobs).order_by(t.jobs.c.updated_at, t.jobs.c.id).limit(limit)
        if since is None:
            stmt = stmt.where(t.jobs.c.status.in_(ACTIVE))
        else:
            stmt = stmt.where(t.jobs.c.updated_at > since)
        with self._engine.connect() as conn:
            return [Job.from_row(row) for row in conn.execute(stmt)]

    def last_change(self) -> datetime | None:
        """When any job last changed."""
        with self._engine.connect() as conn:
            latest: datetime | None = conn.execute(
                select(func.max(t.jobs.c.updated_at))
            ).scalar_one()
        return latest

    def last_data_job(
        self, types: Sequence[str] = ("update",), *, statuses: Sequence[str] | None = None
    ) -> Job | None:
        """The newest job of ``types`` (with one of ``statuses``, if given)."""
        stmt = select(t.jobs).where(t.jobs.c.type.in_(types)).order_by(t.jobs.c.id.desc()).limit(1)
        if statuses is not None:
            stmt = stmt.where(t.jobs.c.status.in_(statuses))
        with self._engine.connect() as conn:
            row = conn.execute(stmt).one_or_none()
        return None if row is None else Job.from_row(row)

    # --- helpers ----------------------------------------------------------------------------

    @contextmanager
    def _write(self) -> Iterator[Connection]:
        """A write transaction that takes the lock up front."""
        with self._engine.connect() as conn:
            conn.execution_options(**{BEGIN: "IMMEDIATE"})
            with conn.begin():
                yield conn

    def _check_no_data_job(self, conn: Connection) -> None:
        row = conn.execute(
            select(t.jobs)
            .where(and_(t.jobs.c.status.in_(ACTIVE), t.jobs.c.type.in_(DATA_JOB_TYPES)))
            .order_by(t.jobs.c.id)
            .limit(1)
        ).one_or_none()
        if row is not None:
            raise JobConflict(Job.from_row(row))

    def _end(
        self,
        job_id: int,
        status: JobStatus,
        *,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> Job:
        now = _now()
        values: dict[str, Any] = {"status": status, "finished_at": now, "updated_at": now}
        if error is not None:
            values["error"] = error
        if result is not None:
            values["result"] = json.dumps(result, default=str)
        with self._write() as conn:
            row = conn.execute(
                update(t.jobs).where(t.jobs.c.id == job_id).values(**values).returning(*t.jobs.c)
            ).one()
        return Job.from_row(row)


def _now() -> datetime:
    return datetime.now(UTC)
