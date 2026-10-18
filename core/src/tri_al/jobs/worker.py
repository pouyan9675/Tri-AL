"""The job worker (docs/design.md §5.4): runs queued jobs one at a time, and the schedule.

``tri-al serve`` starts one worker process beside the API workers; ``tri-al worker`` runs
one on its own. When it starts, the worker fails running jobs whose heartbeat went quiet,
since the process running them is gone. Then it claims the oldest job that can run, runs it
with progress going to ``app.db``, and between jobs queues an update when
``update.schedule`` says one is due.
"""

import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from tri_al.config import Config
from tri_al.config.schedule import Schedule
from tri_al.jobs.progress import HEARTBEAT_INTERVAL, WRITE_INTERVAL, JobProgress
from tri_al.jobs.queue import Job, JobCancelled, JobConflict, JobQueue, worker_name
from tri_al.pipeline import Pipeline, ProgressCallback

if TYPE_CHECKING:
    from tri_al.plugins import LoadedPlugins

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(seconds=60)
"""A running job whose heartbeat is older than this has lost its process."""

POLL_INTERVAL = 1.0
"""Seconds the worker waits between looks at the queue when it is empty."""


@dataclass(frozen=True, slots=True)
class JobContext:
    """What a job's ``run`` gets: the job, where to report progress, and the setup."""

    job: Job
    progress: ProgressCallback
    config: Config
    data_dir: Path


@dataclass(frozen=True, slots=True, kw_only=True)
class JobType:
    """A kind of job the worker runs. Plugins add theirs with ``registry.add_job``.

    ``run`` returns the job's result (JSON-compatible, or None). Raising fails the job;
    reporting progress raises JobCancelled once someone cancels it. Plugin jobs never count
    as data jobs, so they may run while an update holds the lock on ``trials.db``.
    """

    name: str
    run: Callable[[JobContext], dict[str, Any] | None]
    description: str = ""
    plugin: str = ""


def core_job_types(pipeline: Callable[[], Pipeline]) -> dict[str, JobType]:
    """``update`` and ``install``, run by the pipeline ``pipeline()`` makes."""

    def update(ctx: JobContext) -> dict[str, Any]:
        return pipeline().run_update(ctx.progress).as_dict()

    def install(ctx: JobContext) -> dict[str, Any]:
        from_file = ctx.job.payload.get("from_file")
        summary = pipeline().run_install(
            ctx.progress,
            from_file=None if from_file is None else Path(from_file),
            force=bool(ctx.job.payload.get("force", False)),
        )
        return summary.as_dict()

    return {
        "update": JobType(name="update", run=update, description="Fetch what changed."),
        "install": JobType(name="install", run=install, description="Build the database."),
    }


class Worker:
    def __init__(
        self,
        queue: JobQueue,
        job_types: Mapping[str, JobType],
        *,
        config: Config,
        data_dir: Path | None = None,
        name: str | None = None,
        poll_interval: float = POLL_INTERVAL,
        stale_after: timedelta = STALE_AFTER,
        progress_interval: float = WRITE_INTERVAL,
        heartbeat_interval: float = HEARTBEAT_INTERVAL,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.queue = queue
        self.job_types = dict(job_types)
        self.config = config
        self.data_dir = config.data.dir if data_dir is None else data_dir
        self.name = name or worker_name()
        self.schedule: Schedule = config.update.parsed_schedule
        self.poll_interval = poll_interval
        self.stale_after = stale_after
        self.progress_interval = progress_interval
        self.heartbeat_interval = heartbeat_interval
        self.clock = clock

    @classmethod
    def from_plugins(
        cls,
        queue: JobQueue,
        config: Config,
        plugins: "LoadedPlugins",
        *,
        data_dir: Path | None = None,
        **options: Any,
    ) -> Self:
        """A worker for the core's jobs and every enabled plugin's."""

        def pipeline() -> Pipeline:
            return Pipeline.from_plugins(config, plugins, data_dir=data_dir)

        job_types = core_job_types(pipeline) | plugins.contributions.jobs
        return cls(queue, job_types, config=config, data_dir=data_dir, **options)

    def recover(self) -> list[Job]:
        """Fail the running jobs whose process is gone; return them."""
        jobs = self.queue.recover(self.stale_after)
        for job in jobs:
            log.warning(
                "job %d (%s) was running when its process stopped; failed it", job.id, job.type
            )
        return jobs

    def run_once(self) -> Job | None:
        """Claim and run one job; return it as it ended, or None if none could start."""
        job = self.queue.claim(self.name)
        if job is None:
            return None
        return self.execute(job)

    def execute(self, job: Job) -> Job:
        """Run a claimed (running) job to its end."""
        job_type = self.job_types.get(job.type)
        if job_type is None:
            return self.queue.fail(job.id, f"no job type {job.type!r}; is its plugin enabled?")
        log.info("job %d (%s) started", job.id, job.type)
        started = time.monotonic()
        progress = JobProgress(
            self.queue,
            job.id,
            interval=self.progress_interval,
            heartbeat=self.heartbeat_interval,
        )
        try:
            with progress:
                result = job_type.run(JobContext(job, progress, self.config, self.data_dir))
        except JobCancelled:
            log.info("job %d (%s) cancelled", job.id, job.type)
            return self.queue.cancelled(job.id)
        except BaseException as exc:
            ended = self.queue.fail(job.id, _describe(exc))
            if not isinstance(exc, Exception):
                raise  # KeyboardInterrupt, SystemExit: stop the worker too
            log.exception("job %d (%s) failed", job.id, job.type)
            return ended
        log.info("job %d (%s) finished in %.1fs", job.id, job.type, time.monotonic() - started)
        return self.queue.finish(job.id, result)

    def schedule_due(self) -> Job | None:
        """Queue an update if the schedule says one is due; return it."""
        if not self.schedule.enabled or not (self.data_dir / "trials.db").exists():
            return None
        last_attempt = self.queue.last_data_job(("update",))
        if last_attempt is not None and last_attempt.active:
            return None
        succeeded = self.queue.last_data_job(("update", "install"), statuses=("succeeded",))
        last_success = max(
            (
                when
                for when in (
                    succeeded.finished_at if succeeded else None,
                    _last_finished_run(self.data_dir / "trials.db"),
                )
                if when is not None
            ),
            default=None,
        )
        due = self.schedule.due(
            now=self.clock(),
            last_success=last_success,
            last_attempt=None if last_attempt is None else last_attempt.created_at,
        )
        if not due:
            return None
        try:
            job = self.queue.enqueue("update", origin="schedule")
        except JobConflict:
            return None
        log.info("queued scheduled update (job %d)", job.id)
        return job

    def run(self, stop: threading.Event) -> None:
        """Run jobs until ``stop`` is set (checked between jobs)."""
        self.recover()
        next_recovery = time.monotonic() + self.stale_after.total_seconds()
        while not stop.is_set():
            try:
                if time.monotonic() >= next_recovery:
                    self.recover()
                    next_recovery = time.monotonic() + self.stale_after.total_seconds()
                if self.run_once() is not None:
                    continue
                if self.schedule_due() is not None:
                    continue
            except Exception:
                log.exception("the worker hit an error; it carries on")
            stop.wait(self.poll_interval)


def _describe(exc: BaseException) -> str:
    if isinstance(exc, KeyboardInterrupt):
        return "interrupted: the worker was stopped while the job ran"
    return str(exc) or type(exc).__name__


def _last_finished_run(trials_db: Path) -> datetime | None:
    """When the newest finished install or update in ``trials.db`` finished."""
    try:
        conn = sqlite3.connect(f"{trials_db.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT max(finished_at) FROM runs WHERE status = 'finished' "
            "AND kind IN ('install', 'update')"
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return None if row is None or row[0] is None else datetime.fromisoformat(row[0])
