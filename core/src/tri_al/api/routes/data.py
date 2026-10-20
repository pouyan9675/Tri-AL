"""Data endpoints (docs/design.md §5.9): meta, trials, search, facets, dashboard and stats.

Every response is JSON from orjson with an ETag made of the data version (and the build),
so an unchanged request gets a 304 before any work. All reads of one request happen in one
read transaction, so the data version and the data always agree.
"""

import re
from dataclasses import asdict
from typing import Annotated, Any

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select

from tri_al import __version__
from tri_al.access import READ, require
from tri_al.api.http import data_json, decode_cursor, encode_cursor, live_json, not_modified
from tri_al.api.models import (
    ChangesOut,
    DashboardOut,
    ErrorOut,
    FacetsOut,
    LinkedTrialsOut,
    MetaOut,
    SearchOut,
    StatsOut,
    TrialDetailOut,
    TrialPageOut,
)
from tri_al.api.params import sort_param, trial_filter
from tri_al.api.state import ApiState
from tri_al.filters import TrialFilter
from tri_al.linking import linked_trials
from tri_al.pipeline.runs import cursor_key
from tri_al.schema import TrialRecord, labels
from tri_al.search import merge
from tri_al.stats import UnknownChart
from tri_al.storage import SEARCH_CANDIDATES, Sort, SQLiteReader
from tri_al.storage import tables as t
from tri_al.terms.scope import PHASE_GROUPS

router = APIRouter(prefix="/api", dependencies=[Depends(require(READ))])

_WORD = re.compile(r"\w+")

LABELS: dict[str, dict[str, str]] = {
    "status": dict(labels.STATUS),
    "phase": dict(labels.PHASE),
    "study_type": dict(labels.STUDY_TYPE),
    "sponsor_class": dict(labels.SPONSOR_CLASS),
    "intervention_type": dict(labels.INTERVENTION_TYPE),
    "primary_purpose": dict(labels.PRIMARY_PURPOSE),
    "arm_type": dict(labels.ARM_TYPE),
    "allocation": dict(labels.ALLOCATION),
    "intervention_model": dict(labels.INTERVENTION_MODEL),
    "observational_model": dict(labels.OBSERVATIONAL_MODEL),
    "time_perspective": dict(labels.TIME_PERSPECTIVE),
    "masking": dict(labels.MASKING),
    "masked_role": dict(labels.MASKED_ROLE),
    "phase_group": dict(PHASE_GROUPS),
}
"""Sent with the meta, so the front end shows codes as ClinicalTrials.gov does, with no copy."""

NOT_INSTALLED: dict[int | str, dict[str, Any]] = {
    503: {"model": ErrorOut, "description": "There's no data yet."}
}
NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorOut}, **NOT_INSTALLED}


def get_state(request: Request) -> ApiState:
    state: ApiState = request.app.state.tri_al
    return state


State = Annotated[ApiState, Depends(get_state)]
Filter = Annotated[TrialFilter, Depends(trial_filter)]
Limit = Annotated[int, Query(ge=1, le=500)]


# --- meta ---------------------------------------------------------------------------------


@router.get("/meta", response_model=MetaOut, tags=["meta"], name="getMeta")
def get_meta(request: Request, state: State) -> Response:
    """The version, the data version, the last install or update, and what's enabled."""
    storage = state.storage()
    if storage is None:
        return live_json(_meta(state, None, 0))
    with storage.read() as reader:
        version = reader.data_version()
        last_run = reader.connection.execute(
            select(func.max(t.runs.c.id)).where(t.runs.c.status == "finished")
        ).scalar_one()
        etag = f'W/"{version}.{last_run}-{state.build}"'
        if (cached := not_modified(request, etag)) is not None:
            return cached
        return data_json(_meta(state, reader, version), etag)


def _meta(state: ApiState, reader: SQLiteReader | None, version: int) -> dict[str, Any]:
    sources = state.plugins.contributions.sources
    meta: dict[str, Any] = {
        "version": __version__,
        "installed": reader is not None,
        "data_version": version,
        "trials": 0,
        "last_run": None,
        "sources": dict.fromkeys(sources),
        "schedule": state.config.update.schedule,
        "plugins": [plugin.name for plugin in state.plugins.plugins],
        "search_candidates": SEARCH_CANDIDATES,
        "labels": LABELS,
    }
    if reader is None:
        return meta
    conn = reader.connection
    meta["trials"] = state.stats().count(reader, TrialFilter())
    meta["sources"] = {name: reader.meta(cursor_key(name)) for name in sources}
    run = conn.execute(
        select(t.runs.c.id, t.runs.c.kind, t.runs.c.finished_at, t.runs.c.summary)
        .where(t.runs.c.status == "finished")
        .order_by(t.runs.c.id.desc())
        .limit(1)
    ).one_or_none()
    if run is not None:
        summary = orjson.loads(run.summary or "{}")
        counts = summary.get("sources", {}).values()
        meta["last_run"] = {
            "run_id": run.id,
            "kind": run.kind,
            "finished_at": run.finished_at,
            **{key: sum(c.get(key, 0) for c in counts) for key in ("new", "updated", "unchanged")},
        }
    return meta


# --- trials -------------------------------------------------------------------------------


@router.get(
    "/trials",
    response_model=TrialPageOut,
    responses=NOT_INSTALLED,
    tags=["trials"],
    name="listTrials",
)
def list_trials(
    request: Request,
    state: State,
    filter: Filter,
    sort: Annotated[Sort, Depends(sort_param)],
    cursor: Annotated[str | None, Query(description="`next_cursor` of the previous page")] = None,
    limit: Limit = 50,
) -> Response:
    """Trials the filter matches, a page at a time (keyset paging: no offsets)."""
    with state.read() as reader:
        version = reader.data_version()
        etag = state.etag(version)
        if (cached := not_modified(request, etag)) is not None:
            return cached
        after = None if cursor is None else decode_cursor(sort, cursor)
        stats = state.stats()
        page = stats.trial_page(reader, filter, sort=sort, after=after, limit=limit)
        body = {
            "data_version": version,
            "items": page.items,
            "next_cursor": None if page.next is None else encode_cursor(sort, page.next),
            "total": stats.count(reader, filter) if cursor is None else None,
        }
        return data_json(body, etag)


def _find(reader: SQLiteReader, source_id: str, source: str | None) -> tuple[str, int]:
    found = reader.find_ids(source_id)
    if source is not None:
        found = [(s, i) for s, i in found if s == source]
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no trial {source_id}")
    if len(found) > 1:
        sources = ", ".join(s for s, _ in found)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{source_id} is in several registries ({sources}); pick one with ?source=",
        )
    return found[0]


@router.get(
    "/trials/{source_id}",
    response_model=TrialDetailOut,
    responses=NOT_FOUND,
    tags=["trials"],
    name="getTrial",
)
def get_trial(
    request: Request,
    state: State,
    source_id: str,
    source: Annotated[
        str | None, Query(description="The registry, if the id is in several")
    ] = None,
) -> Response:
    """Everything about one trial, such as ``NCT04437511``."""
    with state.read() as reader:
        version = reader.data_version()
        etag = state.etag(version)
        if (cached := not_modified(request, etag)) is not None:
            return cached
        _, trial_id = _find(reader, source_id, source)
        record = reader.get_trial(trial_id, raw=False)
        assert record is not None
        return data_json(_detail(record, version), etag)


def _detail(record: TrialRecord, version: int) -> dict[str, Any]:
    body = asdict(record)
    for key in ("raw", "content_hash"):
        body.pop(key)
    body["data_version"] = version
    body["location_scope"] = record.location_scope
    return body


@router.get(
    "/trials/{source_id}/changes",
    response_model=ChangesOut,
    responses=NOT_FOUND,
    tags=["trials"],
    name="getTrialChanges",
)
def get_trial_changes(
    request: Request,
    state: State,
    source_id: str,
    source: Annotated[
        str | None, Query(description="The registry, if the id is in several")
    ] = None,
) -> Response:
    """What updates changed in the trial since it was installed, newest first."""
    with state.read() as reader:
        version = reader.data_version()
        etag = state.etag(version)
        if (cached := not_modified(request, etag)) is not None:
            return cached
        found_source, trial_id = _find(reader, source_id, source)
        body = {
            "data_version": version,
            "source": found_source,
            "source_id": source_id,
            "changes": reader.changes(trial_id),
        }
        return data_json(body, etag)


@router.get(
    "/trials/{source_id}/linked",
    response_model=LinkedTrialsOut,
    responses=NOT_FOUND,
    tags=["trials"],
    name="getLinkedTrials",
)
def get_linked_trials(
    request: Request,
    state: State,
    source_id: str,
    filter: Filter,
    terms: Annotated[
        list[str] | None,
        Query(description="The trial's MeSH codes to link by; all of them if not given"),
    ] = None,
    source: Annotated[
        str | None, Query(description="The registry, if the id is in several")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Trials listed per phase")] = 100,
) -> Response:
    """Trials that share the trial's MeSH conditions and interventions, by phase.

    A trial is linked when it's tagged with at least one of the chosen condition terms and
    one of the chosen intervention terms; the filter narrows the linked trials.
    """
    with state.read() as reader:
        version = reader.data_version()
        etag = state.etag(version)
        if (cached := not_modified(request, etag)) is not None:
            return cached
        _, trial_id = _find(reader, source_id, source)
        links = linked_trials(reader, trial_id, terms=terms, filter=filter, limit=limit)
        body = {
            "data_version": version,
            "trial": reader.summaries([trial_id])[0],
            "terms": links.terms,
            "total": links.total,
            "phases": links.phases,
        }
        return data_json(body, etag)


# --- search -------------------------------------------------------------------------------


@router.get(
    "/search", response_model=SearchOut, responses=NOT_INSTALLED, tags=["search"], name="search"
)
def search(
    request: Request,
    state: State,
    filter: Filter,
    q: Annotated[
        str, Query(min_length=1, max_length=500, description="Words or trial IDs to find")
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    names: Annotated[
        int,
        Query(ge=0, le=50, description="Matching names to include, for words of 3+ letters"),
    ] = 8,
) -> Response:
    """Trials named by ID, then full-text search merged across search providers, within the
    filter.

    Every term with a letter and a digit, such as ``NCT04437511`` or ``nct04437511``, finds
    the trial with that ID (``id_match`` is ``exact``), so a pasted list of IDs finds each
    one. A single term of 7 or more characters also finds the trials whose ID starts with it
    (``prefix``), for finding a trial as its ID is typed. Each hit has a snippet of the text
    it matched. ``names`` adds conditions, interventions and sponsors whose names match, for
    jumping to a filter.
    """
    filter = filter.without("q")  # q is the search itself here
    with state.read() as reader:
        version = reader.data_version()
        etag = state.etag(version)
        if (cached := not_modified(request, etag)) is not None:
            return cached

        def run() -> bytes:
            conn = reader.connection
            by_id = dict(reader.find_by_id(q, filter=filter, limit=limit))
            results = {
                name: provider.search(conn, q, filter, limit)
                for name, provider in state.providers.items()
            }
            scored: list[tuple[int, float | None]] = [(trial_id, None) for trial_id in by_id]
            scored += [(hit.id, hit.score) for hit in merge(results, limit) if hit.id not in by_id]
            fts = results.get("fts")
            return orjson.dumps(
                {
                    "data_version": version,
                    "query": q,
                    "hits": reader.describe_hits(scored[:limit], q, by_id),
                    "candidates": None if fts is None else fts.candidates,
                    "capped": any(result.capped for result in results.values()),
                    # Below three letters the name index can't help (a full scan).
                    "names": reader.lookup_names(q, limit=names) if names and _long_word(q) else [],
                }
            )

        body = state.stats().cached(reader, ("search", q, filter, limit, names), run)
        return data_json(body, etag)


def _long_word(q: str) -> bool:
    return any(len(word) >= 3 for word in _WORD.findall(q))


# --- facets, dashboard and stats ----------------------------------------------------------


@router.get(
    "/facets", response_model=FacetsOut, responses=NOT_INSTALLED, tags=["stats"], name="getFacets"
)
def get_facets(
    request: Request,
    state: State,
    filter: Filter,
    fields: Annotated[
        list[str] | None, Query(description="Facets to count (repeat for several); default: all")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Options per facet")] = 10,
) -> Response:
    """Counts beside each filter option. A facet ignores its own field, so picking one
    status still shows how many trials the other statuses would add."""
    stats = state.stats()
    names = fields or list(stats.facets)
    if unknown := [name for name in names if name not in stats.facets]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"unknown facets {unknown}; there are {', '.join(stats.facets)}",
        )
    with state.read() as reader:
        version = reader.data_version()
        etag = state.etag(version)
        if (cached := not_modified(request, etag)) is not None:
            return cached
        body = {
            "data_version": version,
            "total": stats.count(reader, filter),
            "facets": stats.facet_counts(reader, names, filter, limit),
        }
        return data_json(body, etag)


@router.get(
    "/dashboard",
    response_model=DashboardOut,
    responses=NOT_INSTALLED,
    tags=["stats"],
    name="getDashboard",
)
def get_dashboard(request: Request, state: State) -> Response:
    """Every chart, for the dashboard and the analysis page, in layout order, and the facets
    the explorer offers."""
    with state.read() as reader:
        version = reader.data_version()
        etag = state.etag(version)
        if (cached := not_modified(request, etag)) is not None:
            return cached
        body = {
            "data_version": version,
            "charts": [
                {
                    "id": chart.id,
                    "title": chart.title,
                    "widget": chart.widget,
                    "description": chart.description,
                    "section": chart.section,
                    "page": chart.page,
                    "x": chart.x,
                    "y": chart.y,
                    "series": chart.series,
                    "format": chart.format,
                    "layout": chart.layout,
                    "plugin": chart.plugin,
                    "precomputed": chart.precompute,
                }
                for chart in state.charts
            ],
            "facets": [
                {"field": facet.field, "title": facet.title, "plugin": facet.plugin}
                for facet in state.facets
            ],
        }
        return data_json(body, etag)


@router.get(
    "/stats/{chart_id}",
    response_model=StatsOut,
    responses=NOT_FOUND,
    tags=["stats"],
    name="getChartData",
)
def get_chart_data(request: Request, state: State, chart_id: str, filter: Filter) -> Response:
    """A chart's rows: precomputed with no filter, computed (and cached) with one."""
    stats = state.stats()
    with state.read() as reader:
        version = reader.data_version()
        etag = state.etag(version)
        if (cached := not_modified(request, etag)) is not None:
            return cached
        try:
            data = stats.chart(reader, chart_id, filter)
        except UnknownChart:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no chart {chart_id!r}") from None
        body = b"".join(
            (
                b'{"chart_id":',
                orjson.dumps(chart_id),
                b',"data_version":',
                str(version).encode(),
                b',"filtered":',
                b"true" if data.filtered else b"false",
                b',"rows":',
                data.rows,
                b"}",
            )
        )
        return data_json(body, etag)
