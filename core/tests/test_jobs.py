import threading
from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text

from tri_al.config import Config
from tri_al.config.schedule import Schedule
from tri_al.jobs import (
    JobCancelled,
    JobConflict,
    JobContext,
    JobProgress,
    JobQueue,
    JobType,
    Worker,
)
from tri_al.pipeline import Pipeline, Progress
from tri_al.storage import open_app_db
from tri_al.testing import FakeSource, fake_study


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = open_app_db(tmp_path / "app.db")
    yield engine
    engine.dispose()


@pytest.fixture
def queue(engine: Engine) -> JobQueue:
    return JobQueue(engine)


def config(tmp_path: Path, schedule: str = "off") -> Config:
    return Config.model_validate(
        {"data": {"dir": str(tmp_path / "data")}, "update": {"schedule": schedule}}
    )


# --- the queue ----------------------------------------------------------------------------


def test_enqueue_and_claim(queue: JobQueue) -> None:
    job = queue.enqueue("update", {"why": "test"})

    assert (job.status, job.type, job.origin, job.payload) == (
        "queued",
        "update",
        "api",
        {"why": "test"},
    )
    claimed = queue.claim("w1")
    assert claimed is not None
    assert (claimed.id, claimed.status, claimed.worker) == (job.id, "running", "w1")
    assert claimed.started_at is not None
    assert queue.claim("w1") is None


def test_only_one_data_job_at_a_time(queue: JobQueue) -> None:
    first = queue.enqueue("update")

    with pytest.raises(JobConflict) as conflict:
        queue.enqueue("update")
    assert conflict.value.existing.id == first.id
    with pytest.raises(JobConflict):
        queue.enqueue("install")
    other = queue.enqueue("export")  # not a data job

    claimed = queue.claim("w")
    assert claimed is not None
    assert claimed.id == first.id
    with pytest.raises(JobConflict):
        queue.start("update")  # the shell can't start one either
    queue.finish(first.id, {"ok": True})
    assert queue.enqueue("update").status == "queued"
    assert queue.get(other.id) is not None


def test_claim_skips_data_jobs_while_one_runs(queue: JobQueue, engine: Engine) -> None:
    running = queue.start("update", origin="cli")
    # A data job that slipped into the queue (written straight to the table) waits.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO jobs (type, status, created_at, updated_at) VALUES "
                "('install', 'queued', '2026-10-17T00:00:00+00:00', '2026-10-17T00:00:00+00:00')"
            )
        )
    export = queue.enqueue("export")

    claimed = queue.claim("w")
    assert claimed is not None
    assert claimed.id == export.id
    assert queue.claim("w") is None
    queue.finish(running.id)
    claimed = queue.claim("w")
    assert claimed is not None
    assert claimed.type == "install"


def test_progress_reports_and_cancelling(queue: JobQueue) -> None:
    job = queue.enqueue("update")
    queue.claim("w")

    assert not queue.report(job.id, Progress("write", 10, 20, "trials", "busy"))
    stored = queue.get(job.id)
    assert stored is not None
    assert (stored.stage, stored.progress, stored.total, stored.unit, stored.message) == (
        "write",
        10,
        20,
        "trials",
        "busy",
    )
    cancelled = queue.cancel(job.id)
    assert cancelled is not None
    assert (cancelled.status, cancelled.cancel_requested) == ("running", True)
    assert queue.report(job.id, None)  # the next report hears about it
    assert queue.cancelled(job.id).status == "cancelled"


def test_cancelling_a_queued_job(queue: JobQueue) -> None:
    job = queue.enqueue("update")

    cancelled = queue.cancel(job.id)

    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert queue.claim("w") is None
    assert queue.cancel(999) is None


def test_recover_fails_jobs_whose_heartbeat_stopped(queue: JobQueue, engine: Engine) -> None:
    stale = queue.enqueue("update")
    queue.claim("dead")
    fresh = queue.enqueue("export")
    queue.claim("alive")
    old = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE jobs SET heartbeat = :old WHERE id = :id"), {"old": old, "id": stale.id}
        )

    recovered = queue.recover(timedelta(seconds=60))

    assert [job.id for job in recovered] == [stale.id]
    failed = queue.get(stale.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error is not None
    assert "stopped" in failed.error
    running = queue.get(fresh.id)
    assert running is not None
    assert running.status == "running"


def test_changes_since(queue: JobQueue) -> None:
    first = queue.enqueue("update")
    seen = queue.last_change()

    queue.claim("w")
    second = queue.enqueue("export")

    assert [job.id for job in queue.changed_since(seen)] == [first.id, second.id]
    assert [job.id for job in queue.changed_since(None)] == [first.id, second.id]  # active ones


# --- progress -----------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_progress_is_written_at_most_twice_a_second(queue: JobQueue) -> None:
    job = queue.start("update")
    clock = Clock()
    seen: list[Progress] = []
    progress = JobProgress(queue, job.id, interval=0.5, heartbeat=5, also=seen.append, clock=clock)

    for i in range(100):  # 100 reports in one second
        clock.now = i / 100
        progress(Progress("write", i, 100, "trials"))

    assert len(seen) == 100
    assert progress.writes == 2
    stored = queue.get(job.id)
    assert stored is not None
    assert stored.progress == 50
    progress.tick()  # too soon after the last write
    assert progress.writes == 2
    clock.now = 1.5
    progress.tick()  # the held-back report goes out
    stored = queue.get(job.id)
    assert stored is not None
    assert (progress.writes, stored.progress) == (3, 99)
    progress.tick()
    assert progress.writes == 3  # nothing new, and no heartbeat due yet
    clock.now = 7.0
    progress.tick()
    assert progress.writes == 4  # a heartbeat


def test_progress_raises_once_cancelled(queue: JobQueue) -> None:
    job = queue.start("update")
    clock = Clock()
    progress = JobProgress(queue, job.id, interval=0.5, clock=clock)
    progress(Progress("fetch"))
    queue.cancel(job.id)

    clock.now = 0.1
    progress(Progress("fetch", 1))  # not written yet, so not heard yet
    clock.now = 1.0
    with pytest.raises(JobCancelled):
        progress(Progress("fetch", 2))


def test_the_heartbeat_thread_flushes_the_last_report(queue: JobQueue) -> None:
    job = queue.start("update")

    with JobProgress(queue, job.id, interval=0.05, heartbeat=0.1) as progress:
        progress(Progress("write", 1, 3))
        progress(Progress("write", 2, 3))  # held back
        progress(Progress("commit"))  # held back
    stored = queue.get(job.id)
    assert stored is not None
    assert stored.stage == "commit"


# --- the schedule -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("off", Schedule(None)),
        ("never", Schedule(None)),
        ("hourly", Schedule(timedelta(hours=1))),
        ("Daily", Schedule(timedelta(days=1))),
        ("weekly", Schedule(timedelta(weeks=1))),
        ("daily at 06:30", Schedule(timedelta(days=1), time(6, 30))),
        ("every 6 hours", Schedule(timedelta(hours=6))),
        ("every 30 minutes", Schedule(timedelta(minutes=30))),
        ("every 2 days", Schedule(timedelta(days=2))),
    ],
)
def test_schedules(text: str, expected: Schedule) -> None:
    assert Schedule.parse(text) == expected


@pytest.mark.parametrize("text", ["sometimes", "daily at 25:00", "every 1 minute", "every hours"])
def test_bad_schedules(text: str) -> None:
    with pytest.raises(ValueError, match=r"schedule|time of day|5 minutes"):
        Schedule.parse(text)


def test_bad_schedules_are_config_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="isn't a schedule"):
        config(tmp_path, schedule="twice a day")


def test_when_a_schedule_is_due() -> None:
    now = datetime(2026, 10, 17, 12, tzinfo=UTC)
    daily = Schedule.parse("daily")

    assert daily.due(now=now, last_success=None, last_attempt=None)
    assert not daily.due(now=now, last_success=now - timedelta(hours=23), last_attempt=None)
    assert daily.due(now=now, last_success=now - timedelta(hours=25), last_attempt=None)
    # A failed try waits an hour before the next.
    assert not daily.due(
        now=now, last_success=now - timedelta(days=3), last_attempt=now - timedelta(minutes=10)
    )
    assert daily.due(
        now=now, last_success=now - timedelta(days=3), last_attempt=now - timedelta(hours=2)
    )
    assert not Schedule.parse("off").due(now=now, last_success=None, last_attempt=None)


def test_daily_at_a_time() -> None:
    at = Schedule.parse("daily at 06:00")
    local = datetime(2026, 10, 17, 9, 0).astimezone()  # 09:00 local
    today_six = local.replace(hour=6)

    assert at.due(now=local, last_success=today_six - timedelta(hours=1), last_attempt=None)
    assert not at.due(now=local, last_success=today_six + timedelta(minutes=5), last_attempt=None)
    early = local.replace(hour=5)  # before today's slot: yesterday's counts
    assert not at.due(now=early, last_success=today_six - timedelta(hours=10), last_attempt=None)


# --- the worker ---------------------------------------------------------------------------


def worker_for(
    queue: JobQueue, tmp_path: Path, job_types: dict[str, JobType], **options: Any
) -> Worker:
    return Worker(queue, job_types, config=config(tmp_path), name="test", **options)


def test_the_worker_runs_jobs_and_records_results(queue: JobQueue, tmp_path: Path) -> None:
    def echo(ctx: JobContext) -> dict[str, Any]:
        ctx.progress(Progress("echo", 1, 1))
        return {"payload": ctx.job.payload}

    worker = worker_for(queue, tmp_path, {"echo": JobType(name="echo", run=echo)})
    job = queue.enqueue("echo", {"n": 1}, origin="plugin")

    ended = worker.run_once()

    assert ended is not None
    assert (ended.id, ended.status, ended.result) == (job.id, "succeeded", {"payload": {"n": 1}})
    assert ended.finished_at is not None
    assert worker.run_once() is None


def test_failed_and_unknown_jobs(queue: JobQueue, tmp_path: Path) -> None:
    def boom(ctx: JobContext) -> None:
        raise RuntimeError("no network")

    worker = worker_for(queue, tmp_path, {"boom": JobType(name="boom", run=boom)})
    queue.enqueue("boom")
    queue.enqueue("mystery")

    failed = worker.run_once()
    unknown = worker.run_once()

    assert failed is not None
    assert (failed.status, failed.error) == ("failed", "no network")
    assert unknown is not None
    assert unknown.status == "failed"
    assert unknown.error is not None
    assert "no job type 'mystery'" in unknown.error


def test_cancelling_a_running_job(queue: JobQueue, tmp_path: Path) -> None:
    started = threading.Event()

    def slow(ctx: JobContext) -> None:
        started.set()
        while True:
            ctx.progress(Progress("waiting"))

    worker = worker_for(
        queue, tmp_path, {"slow": JobType(name="slow", run=slow)}, progress_interval=0.01
    )
    job = queue.enqueue("slow")
    thread = threading.Thread(target=worker.run_once)
    thread.start()
    started.wait(5)
    queue.cancel(job.id)
    thread.join(5)

    ended = queue.get(job.id)
    assert ended is not None
    assert ended.status == "cancelled"


def test_a_real_update_runs_as_a_job(queue: JobQueue, tmp_path: Path) -> None:
    source = FakeSource(
        studies=(fake_study("F1", updated="2026-10-01"),),
        changed=(
            fake_study("F1", "Renamed", updated="2026-10-02"),
            fake_study("F2", updated="2026-10-02"),
        ),
    )
    pipeline = Pipeline(data_dir=tmp_path / "data", sources=[source], workers=0)
    pipeline.run_install()
    from tri_al.jobs import core_job_types

    worker = worker_for(queue, tmp_path, core_job_types(lambda: pipeline))
    queue.enqueue("update")

    ended = worker.run_once()

    assert ended is not None
    assert ended.status == "succeeded", ended.error
    assert ended.result is not None
    assert ended.result["sources"]["fake"]["new"] == 1
    assert ended.result["sources"]["fake"]["updated"] == 1
    assert ended.stage == "commit"


def test_the_schedule_queues_updates(queue: JobQueue, tmp_path: Path) -> None:
    now = datetime(2026, 10, 17, 12, tzinfo=UTC)
    worker = Worker(queue, {}, config=config(tmp_path, schedule="daily"), clock=lambda: now)

    assert worker.schedule_due() is None  # nothing installed yet
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "trials.db").touch()
    scheduled = worker.schedule_due()
    assert scheduled is not None
    assert (scheduled.type, scheduled.origin) == ("update", "schedule")
    assert worker.schedule_due() is None  # it's waiting
    queue.claim("w")
    queue.finish(scheduled.id)
    assert worker.schedule_due() is None  # it just ran


def test_the_worker_loop_recovers_and_stops(
    queue: JobQueue, tmp_path: Path, engine: Engine
) -> None:
    stale = queue.enqueue("update")
    queue.claim("gone")
    with engine.begin() as conn:
        conn.execute(text("UPDATE jobs SET heartbeat = NULL"))
    done = threading.Event()

    def mark(ctx: JobContext) -> None:
        done.set()

    worker = worker_for(
        queue, tmp_path, {"mark": JobType(name="mark", run=mark)}, poll_interval=0.01
    )
    stop = threading.Event()
    thread = threading.Thread(target=worker.run, args=(stop,))
    thread.start()
    queue.enqueue("mark")
    assert done.wait(5)
    stop.set()
    thread.join(5)

    recovered = queue.get(stale.id)
    assert recovered is not None
    assert recovered.status == "failed"
    assert not thread.is_alive()
