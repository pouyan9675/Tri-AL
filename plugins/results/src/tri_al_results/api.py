"""The plugin's routes, under ``/api/x/results/``: a trial's posted results, for its page.

The results are read from the trial's raw document on request (about a millisecond), so
the page shows everything the registry has, outcome measures included, not only what the
tables keep. The models below are the OpenAPI schema the front end's client is generated
from (``python -m tri_al.api.openapi --plugin results``); the handler returns orjson bytes.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from tri_al.access import READ, require
from tri_al.api.http import JSONBytes, data_json, not_modified
from tri_al.api.models import ErrorOut
from tri_al.api.state import ApiState
from tri_al.storage import tables as t
from tri_al_results.parse import parse
from tri_al_results.store import read_studies


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GroupOut(_Out):
    id: str
    title: str
    description: str | None


class MilestoneOut(_Out):
    label: str
    counts: dict[str, int]


class DropoutOut(_Out):
    reason: str
    kind: str
    counts: dict[str, int]


class PeriodOut(_Out):
    title: str
    milestones: list[MilestoneOut]
    dropouts: list[DropoutOut]


class FlowOut(_Out):
    groups: list[GroupOut]
    periods: list[PeriodOut]
    recruitment: str | None
    pre_assignment: str | None


class ValueOut(_Out):
    value: str | None
    spread: str | None
    lower: str | None
    upper: str | None
    comment: str | None


class CategoryOut(_Out):
    title: str
    values: dict[str, ValueOut]


class ClassOut(_Out):
    title: str
    categories: list[CategoryOut]


class MeasureOut(_Out):
    title: str
    param: str | None
    dispersion: str | None
    unit: str | None
    classes: list[ClassOut]
    description: str | None
    population: str | None


class BaselineOut(_Out):
    groups: list[GroupOut]
    total: str | None
    participants: dict[str, int]
    measures: list[MeasureOut]
    population: str | None


class AnalysisOut(_Out):
    groups: list[str]
    method: str | None
    p_value: str | None
    estimate_type: str | None
    estimate: str | None
    ci_percent: str | None
    ci_lower: str | None
    ci_upper: str | None
    hypothesis: str | None
    description: str | None


class OutcomeResultOut(_Out):
    type: str
    title: str
    groups: list[GroupOut]
    participants: dict[str, int]
    classes: list[ClassOut]
    analyses: list[AnalysisOut]
    description: str | None
    time_frame: str | None
    population: str | None
    param: str | None
    dispersion: str | None
    unit: str | None
    posted: bool


class EventGroupOut(_Out):
    id: str
    title: str
    description: str | None
    placebo: bool
    total: bool
    serious_affected: int | None
    serious_at_risk: int | None
    other_affected: int | None
    other_at_risk: int | None
    deaths: int | None
    deaths_at_risk: int | None


class EventCountOut(_Out):
    affected: int | None
    at_risk: int | None
    events: int | None


class EventOut(_Out):
    term: str
    serious: bool
    counts: dict[str, EventCountOut]
    organ: str | None
    organ_key: str | None
    vocabulary: str | None
    systematic: bool | None


class AdverseEventsOut(_Out):
    groups: list[EventGroupOut]
    events: list[EventOut]
    threshold: float | None
    time_frame: str | None
    description: str | None


class AgreementOut(_Out):
    pi_sponsor_employee: bool | None
    restrictive: bool | None
    restriction: str | None
    details: str | None


class TrialResultsOut(_Out):
    source: str
    source_id: str
    flow: FlowOut | None
    baseline: BaselineOut | None
    outcomes: list[OutcomeResultOut]
    adverse_events: AdverseEventsOut | None
    limitations: str | None
    agreement: AgreementOut | None


NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorOut, "description": "No such trial, or it has no results posted."},
    409: {"model": ErrorOut, "description": "The id is in several registries."},
    503: {"model": ErrorOut, "description": "There's no data yet."},
}

router = APIRouter(dependencies=[Depends(require(READ))])


@router.get(
    "/trials/{source_id}",
    response_model=TrialResultsOut,
    response_class=JSONBytes,
    responses=NOT_FOUND,
    name="getTrialResults",
)
def get_trial_results(
    request: Request,
    source_id: str,
    source: Annotated[
        str | None, Query(description="The registry, if the id is in several")
    ] = None,
) -> Response:
    """A trial's posted results: participant flow, baseline characteristics, outcome
    measures with their analyses, adverse events by arm, limitations and agreements."""
    state: ApiState = request.app.state.tri_al
    with state.read() as reader:
        etag = state.etag(reader.data_version())
        if (cached := not_modified(request, etag)) is not None:
            return cached
        found = [(s, i) for s, i in reader.find_ids(source_id) if source is None or s == source]
        if len(found) > 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{source_id} is in several registries; pick one with ?source=",
            )
        if not found:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no trial {source_id}")
        trial_source, trial_id = found[0]
        studies = dict(read_studies(reader.connection, [trial_id]))
        results = parse(studies[trial_id]) if trial_id in studies else None
        if results is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no results posted for {source_id}")
        canonical = reader.connection.execute(
            select(t.trials.c.source_id).where(t.trials.c.id == trial_id)
        ).scalar_one()
        body = {"source": trial_source, "source_id": canonical, **_fields(results)}
        return data_json(body, etag)


def _fields(results: Any) -> dict[str, Any]:
    return {name: getattr(results, name) for name in results.__slots__}


__all__ = ["TrialResultsOut", "router"]
