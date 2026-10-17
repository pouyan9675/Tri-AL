"""Bookkeeping in ``trials.db``: runs and their checkpoints, and ``meta`` values (design §6)."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, insert, select, update

from tri_al.pipeline.summary import RunKind, RunSummary
from tri_al.storage import tables as t

DATA_VERSION = "data_version"
"""``meta`` key: bumped whenever the data changes, so caches keyed by it go stale."""


def cursor_key(source: str) -> str:
    """``meta`` key of a source's update cursor: the latest ``last_update`` it has seen."""
    return f"cursor.{source}"


@dataclass
class Run:
    id: int
    kind: str
    status: str
    checkpoint: dict[str, Any] = field(default_factory=dict)

    @property
    def stages_done(self) -> dict[str, float]:
        """Finished stages and how long each took, in seconds."""
        stages: dict[str, float] = self.checkpoint.setdefault("stages", {})
        return stages


def start_run(conn: Connection, kind: RunKind) -> Run:
    run_id = conn.execute(
        insert(t.runs)
        .values(kind=kind, status="running", started_at=datetime.now(UTC))
        .returning(t.runs.c.id)
    ).scalar_one()
    return Run(run_id, kind, "running")


def latest_run(conn: Connection, kind: RunKind) -> Run | None:
    row = conn.execute(
        select(t.runs.c.id, t.runs.c.kind, t.runs.c.status, t.runs.c.checkpoint)
        .where(t.runs.c.kind == kind)
        .order_by(t.runs.c.id.desc())
        .limit(1)
    ).one_or_none()
    if row is None:
        return None
    return Run(row.id, row.kind, row.status, json.loads(row.checkpoint or "{}"))


def save_checkpoint(conn: Connection, run: Run, *, status: str = "running") -> None:
    run.status = status
    conn.execute(
        update(t.runs)
        .where(t.runs.c.id == run.id)
        .values(status=status, checkpoint=json.dumps(run.checkpoint))
    )


def finish_run(conn: Connection, run: Run, summary: RunSummary) -> None:
    run.status = "finished"
    conn.execute(
        update(t.runs)
        .where(t.runs.c.id == run.id)
        .values(
            status="finished",
            finished_at=datetime.now(UTC),
            checkpoint=json.dumps(run.checkpoint),
            summary=json.dumps(summary.as_dict()),
        )
    )


def fail_run(conn: Connection, run: Run, error: BaseException, summary: RunSummary) -> None:
    run.status = "failed"
    conn.execute(
        update(t.runs)
        .where(t.runs.c.id == run.id)
        .values(
            status="failed",
            finished_at=datetime.now(UTC),
            checkpoint=json.dumps(run.checkpoint),
            summary=json.dumps({**summary.as_dict(), "error": repr(error)}),
        )
    )


def get_meta(conn: Connection, key: str) -> str | None:
    return conn.execute(select(t.meta.c.value).where(t.meta.c.key == key)).scalar_one_or_none()


def set_meta(conn: Connection, key: str, value: str) -> None:
    conn.execute(insert(t.meta).prefix_with("OR REPLACE").values(key=key, value=value))


def data_version(conn: Connection) -> int:
    return int(get_meta(conn, DATA_VERSION) or 0)
