"""Jobs (docs/design.md §5.4 and §5.9): start an update, follow and cancel jobs."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from tri_al.access import CANCEL_JOB, READ, START_UPDATE, require
from tri_al.api.events import job_json
from tri_al.api.http import live_json
from tri_al.api.models import ErrorOut, JobConflictOut, JobOut, JobsOut
from tri_al.api.routes.data import State
from tri_al.jobs import JobConflict

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post(
    "/update",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobOut,
    responses={409: {"model": JobConflictOut, "description": "A data job is queued or running."}},
    dependencies=[Depends(require(START_UPDATE))],
    name="startUpdate",
)
def start_update(state: State) -> Response:
    """Queue an update; the job worker runs it. Follow it on ``/api/events``."""
    if not state.trials_db.exists():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "there's no database to update; run `tri-al install` first"
        )
    try:
        job = state.queue.enqueue("update", origin="api")
    except JobConflict as exc:
        body = {"detail": str(exc), "job": job_json(exc.existing)}
        return live_json(body, status_code=status.HTTP_409_CONFLICT)
    return live_json(job_json(job), status_code=status.HTTP_202_ACCEPTED)


@router.get("", response_model=JobsOut, dependencies=[Depends(require(READ))], name="listJobs")
def list_jobs(state: State, limit: Annotated[int, Query(ge=1, le=200)] = 20) -> Response:
    """The newest jobs first."""
    return live_json({"jobs": [job_json(job) for job in state.queue.recent(limit)]})


@router.get(
    "/{job_id}",
    response_model=JobOut,
    responses={404: {"model": ErrorOut}},
    dependencies=[Depends(require(READ))],
    name="getJob",
)
def get_job(state: State, job_id: int) -> Response:
    job = state.queue.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no job {job_id}")
    return live_json(job_json(job))


@router.post(
    "/{job_id}/cancel",
    response_model=JobOut,
    responses={404: {"model": ErrorOut}},
    dependencies=[Depends(require(CANCEL_JOB))],
    name="cancelJob",
)
def cancel_job(state: State, job_id: int) -> Response:
    """Cancel a queued job, or ask a running one to stop at its next progress report.

    A cancelled update rolls back: nothing it fetched is kept.
    """
    job = state.queue.cancel(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no job {job_id}")
    return live_json(job_json(job))
