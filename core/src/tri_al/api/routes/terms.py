"""Term analyses (``tri_al.terms``): one MeSH condition or intervention, in depth.

``/api/terms`` finds terms; ``/api/terms/{kind}/{code}`` and the paths under it are its
analyses, each within the filter (similar terms excepted: they span the registry). They are
computed from the API worker's trial index, so the first request after a new data version
waits for the index, and cached by data version, term and filter.
"""

from collections.abc import Callable
from dataclasses import fields
from typing import Annotated, Any

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from tri_al.access import READ, require
from tri_al.api.http import data_json, not_modified
from tri_al.api.models import (
    TermAttritionOut,
    TermDurationsOut,
    TermKind,
    TermOverviewOut,
    TermPipelineOut,
    TermProfileOut,
    TermReadoutsOut,
    TermRelatedOut,
    TermSimilarOut,
    TermsOut,
    TermThemesOut,
    TermTimelineOut,
)
from tri_al.api.routes.data import NOT_FOUND, NOT_INSTALLED, Filter, State
from tri_al.api.state import ApiState
from tri_al.filters import EVERY_TRIAL, TrialFilter
from tri_al.stats import IndexUnavailable, TrialIndex
from tri_al.storage import SQLiteReader
from tri_al.terms import (
    Scope,
    TermTotals,
    as_of,
    attrition,
    durations,
    find_term,
    lookup_terms,
    narrower_terms,
    overview,
    pipeline,
    profile,
    readouts,
    related,
    similar,
    term_mask,
    themes,
    timeline,
)

router = APIRouter(prefix="/api/terms", dependencies=[Depends(require(READ))], tags=["terms"])

Kind = Annotated[TermKind, Query(description="condition or intervention")]


@router.get("", response_model=TermsOut, responses=NOT_INSTALLED, name="findTerms")
def find_terms(
    request: Request,
    state: State,
    kind: Kind,
    q: Annotated[str | None, Query(max_length=200, description="Part of a name, or a code")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> Response:
    """MeSH terms of one kind whose name contains ``q`` (or whose code is ``q``), best first:
    the exact name, then names starting with it, then a word starting with it, each by
    trials. Without ``q``, the terms most trials are tagged with."""
    stats = state.stats()
    with state.read() as reader:
        version = reader.data_version()
        etag = state.etag(version)
        if (cached := not_modified(request, etag)) is not None:
            return cached

        def run() -> bytes:
            conn, index = reader.connection, trial_index(state, reader)
            totals: TermTotals = stats.cached(
                reader, ("term-totals", kind), lambda: TermTotals.read(conn, index, kind)
            )
            found = lookup_terms(conn, totals, q, limit)
            return orjson.dumps({"data_version": version, "kind": kind, "terms": found})

        body = stats.cached(reader, ("terms", kind, q, limit), run)
        return data_json(body, etag)


def _analysis(
    request: Request,
    state: ApiState,
    kind: TermKind,
    code: str,
    filter: TrialFilter,
    name: str,
    compute: Callable[[Scope], Any],
) -> Response:
    """Run one analysis of a term, or answer from the cache or with a 304."""
    stats = state.stats()
    with state.read() as reader:
        version = reader.data_version()
        etag = state.etag(version)
        if (cached := not_modified(request, etag)) is not None:
            return cached

        def run() -> bytes:
            scope = _scope(state, reader, kind, code, filter)
            result = compute(scope)
            body = {"data_version": version}
            body.update({field.name: getattr(result, field.name) for field in fields(result)})
            return orjson.dumps(body)

        body = stats.cached(reader, ("term", name, kind, code, filter), run)
        return data_json(body, etag)


def trial_index(state: ApiState, reader: SQLiteReader) -> TrialIndex:
    """The trial index for the reader's data version; 503 if it isn't ready in time."""
    try:
        return state.stats().full_index(reader)
    except IndexUnavailable:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "the trial index is still being built, or the data just changed; try again",
            headers={"Retry-After": "2"},
        ) from None


def _scope(
    state: ApiState, reader: SQLiteReader, kind: TermKind, code: str, filter: TrialFilter
) -> Scope:
    stats = state.stats()
    index = trial_index(state, reader)
    conn = reader.connection
    found = find_term(conn, kind, code.strip().upper())
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no {kind} term {code!r}")
    term_id, ref = found
    everywhere = stats.cached(
        reader, ("term-mask", term_id, kind), lambda: term_mask(index, conn, term_id, kind)
    )
    within = stats.mask(reader, index, filter) if not filter.is_empty else index.present
    return Scope(
        ref=ref,
        term_id=term_id,
        index=index,
        reader=reader,
        within=within,
        trials=within & everywhere,
        everywhere=everywhere,
        as_of=stats.cached(reader, ("as-of",), lambda: as_of(index)),
    )


@router.get("/{kind}/{code}", response_model=TermOverviewOut, responses=NOT_FOUND, name="getTerm")
def get_term(request: Request, state: State, kind: TermKind, code: str, filter: Filter) -> Response:
    """The term in brief: its trials, narrower terms, statuses, sponsors and reach."""
    return _analysis(
        request,
        state,
        kind,
        code,
        filter,
        "overview",
        lambda scope: overview(scope, narrower_terms(scope)),
    )


@router.get(
    "/{kind}/{code}/timeline",
    response_model=TermTimelineOut,
    responses=NOT_FOUND,
    name="getTermTimeline",
)
def get_term_timeline(
    request: Request, state: State, kind: TermKind, code: str, filter: Filter
) -> Response:
    """Trials started per year by phase group, the term's share of all trials started, lead
    sponsors new to it, and its momentum: its share of newly posted trials in the last 3, 6
    and 12 months against the 12 months before each (a two-sided exact binomial test)."""
    return _analysis(request, state, kind, code, filter, "timeline", timeline)


@router.get(
    "/{kind}/{code}/readouts",
    response_model=TermReadoutsOut,
    responses=NOT_FOUND,
    name="getTermReadouts",
)
def get_term_readouts(
    request: Request, state: State, kind: TermKind, code: str, filter: Filter
) -> Response:
    """Active trials by when their primary completion is due over the next 24 months: when
    their main results come."""
    return _analysis(request, state, kind, code, filter, "readouts", readouts)


@router.get(
    "/{kind}/{code}/related",
    response_model=TermRelatedOut,
    responses=NOT_FOUND,
    name="getTermRelated",
)
def get_term_related(
    request: Request, state: State, kind: TermKind, code: str, filter: Filter
) -> Response:
    """Conditions and interventions tagged with the term's trials more often than with the
    filter's other trials: lift (smoothed), and an exact test corrected for the terms tested.
    The network links the most related terms by the trials they share, in communities."""
    return _analysis(
        request,
        state,
        kind,
        code,
        filter,
        "related",
        lambda scope: related(scope, list(narrower_terms(scope))),
    )


@router.get(
    "/{kind}/{code}/pipeline",
    response_model=TermPipelineOut,
    responses=NOT_FOUND,
    name="getTermPipeline",
)
def get_term_pipeline(
    request: Request, state: State, kind: TermKind, code: str, filter: Filter
) -> Response:
    """The other kind's terms in the term's trials by phase (a condition's interventions, an
    intervention's conditions), and the term's trials by phase and status."""
    return _analysis(request, state, kind, code, filter, "pipeline", pipeline)


@router.get(
    "/{kind}/{code}/attrition",
    response_model=TermAttritionOut,
    responses=NOT_FOUND,
    name="getTermAttrition",
)
def get_term_attrition(
    request: Request, state: State, kind: TermKind, code: str, filter: Filter
) -> Response:
    """How often the term's trials stop early against the filter's others, phase by phase,
    and the reasons they give, sorted into kinds by their words."""
    return _analysis(request, state, kind, code, filter, "attrition", attrition)


@router.get(
    "/{kind}/{code}/durations",
    response_model=TermDurationsOut,
    responses=NOT_FOUND,
    name="getTermDurations",
)
def get_term_durations(
    request: Request, state: State, kind: TermKind, code: str, filter: Filter
) -> Response:
    """Kaplan-Meier curves: months from start to primary completion by phase group, and from
    completion to posted results, for the term's trials and the filter's others."""
    return _analysis(request, state, kind, code, filter, "durations", durations)


@router.get(
    "/{kind}/{code}/profile",
    response_model=TermProfileOut,
    responses=NOT_FOUND,
    name="getTermProfile",
)
def get_term_profile(
    request: Request, state: State, kind: TermKind, code: str, filter: Filter
) -> Response:
    """Design, population and scale against the filter's other trials, with the baseline
    weighted to the term's mix of phases, and standardized differences."""
    return _analysis(request, state, kind, code, filter, "profile", profile)


@router.get(
    "/{kind}/{code}/themes",
    response_model=TermThemesOut,
    responses=NOT_FOUND,
    name="getTermThemes",
)
def get_term_themes(
    request: Request, state: State, kind: TermKind, code: str, filter: Filter
) -> Response:
    """Sub-themes: the term's trials (up to 4,000) clustered by their vectors, laid out in
    two dimensions and named by their titles' distinctive words."""
    return _analysis(
        request,
        state,
        kind,
        code,
        filter,
        "themes",
        lambda scope: themes(scope, list(narrower_terms(scope))),
    )


@router.get(
    "/{kind}/{code}/similar",
    response_model=TermSimilarOut,
    responses=NOT_FOUND,
    name="getTermSimilar",
)
def get_term_similar(request: Request, state: State, kind: TermKind, code: str) -> Response:
    """Terms whose trials read most like the term's: the nearest average trial vectors,
    across the whole registry (there's no filter). The first request after a new data
    version builds every term's average, which takes a few seconds."""

    def compute(scope: Scope) -> Any:
        index = scope.index
        vectors = state.term_vectors.get(scope.conn, index)
        return similar(scope, vectors, list(narrower_terms(scope)))

    return _analysis(request, state, kind, code, EVERY_TRIAL, "similar", compute)
