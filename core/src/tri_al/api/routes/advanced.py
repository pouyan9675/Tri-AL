"""Advanced search (``tri_al.advanced``): trials by the words in chosen parts of them, whom
they take, how they're designed and where they run, within the filter.

``/api/search/advanced`` runs one; ``/api/places`` finds the places a search can be near.
Both read the API worker's trial index (the first request after a new data version waits for
it), and a search near a place reads every site's coordinates once per data version. Results
are cached by data version, query, filter and order.
"""

from typing import Annotated, Literal

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from tri_al.access import READ, require
from tri_al.advanced import (
    AdvancedQuery,
    Found,
    Near,
    Order,
    default_order,
    describe,
    find,
)
from tri_al.advanced.places import COUNTRY_NAMES
from tri_al.api.http import data_json, not_modified
from tri_al.api.models import AdvancedSearchOut, PlacesOut
from tri_al.api.params import Values
from tri_al.api.routes.data import NOT_INSTALLED, Filter, State
from tri_al.api.routes.terms import trial_index
from tri_al.filters import IntRange
from tri_al.storage import SORT_KEYS, Sort

router = APIRouter(prefix="/api", dependencies=[Depends(require(READ))], tags=["search"])

_SYNTAX = (
    'Words, all of which must match; `"a phrase"`; `"words near"~5` (within 5 words); '
    "`a OR b`; `prefix*`; `-word` to leave out."
)
Text = Annotated[str | None, Query(max_length=500, description=_SYNTAX)]


def advanced_query(
    text: Annotated[str | None, Query(max_length=500, description="Anywhere. " + _SYNTAX)] = None,
    title: Text = None,
    condition: Annotated[
        str | None, Query(max_length=500, description="In condition names. " + _SYNTAX)
    ] = None,
    intervention: Annotated[
        str | None,
        Query(max_length=500, description="In intervention names and their other names."),
    ] = None,
    summary: Annotated[
        str | None, Query(max_length=500, description="In the summary or description.")
    ] = None,
    eligibility: Annotated[
        str | None, Query(max_length=500, description="In the eligibility criteria.")
    ] = None,
    inclusion: Annotated[
        str | None, Query(max_length=500, description="Under the inclusion criteria heading.")
    ] = None,
    exclusion: Annotated[
        str | None, Query(max_length=500, description="Under the exclusion criteria heading.")
    ] = None,
    outcome: Annotated[
        str | None, Query(max_length=500, description="In outcome measures.")
    ] = None,
    primary_outcome: Annotated[
        str | None, Query(max_length=500, description="In primary outcome measures.")
    ] = None,
    secondary_outcome: Annotated[
        str | None, Query(max_length=500, description="In secondary outcome measures.")
    ] = None,
    age: Annotated[
        str | None,
        Query(
            description="Years: trials that take someone of this age (`70`) or of an age in "
            "the range (`60..80`, `..17`)."
        ),
    ] = None,
    sex: Annotated[
        Literal["FEMALE", "MALE"] | None,
        Query(description="Trials that take this sex (or all, or don't say)."),
    ] = None,
    healthy_volunteers: Annotated[
        bool | None, Query(description="Trials that take healthy volunteers, or don't.")
    ] = None,
    allocation: Values = None,
    masking: Values = None,
    intervention_model: Values = None,
    primary_purpose: Values = None,
    placebo: Annotated[
        bool | None, Query(description="Trials with an intervention named placebo, or without.")
    ] = None,
    near: Annotated[
        str | None,
        Query(description="`latitude,longitude`: trials with a site within `within` km."),
    ] = None,
    within: Annotated[float, Query(gt=0, le=20_000, description="Kilometres from `near`.")] = 50,
) -> AdvancedQuery:
    try:
        return AdvancedQuery.make(
            {
                "text": text,
                "title": title,
                "condition": condition,
                "intervention": intervention,
                "summary": summary,
                "eligibility": eligibility,
                "inclusion": inclusion,
                "exclusion": exclusion,
                "outcome": outcome,
                "primary_outcome": primary_outcome,
                "secondary_outcome": secondary_outcome,
            },
            ages=IntRange.parse(age) if age and age.strip() else None,
            sex=sex,
            healthy_volunteers=healthy_volunteers,
            allocation=tuple(allocation or ()),
            masking=tuple(masking or ()),
            intervention_model=tuple(intervention_model or ()),
            primary_purpose=tuple(primary_purpose or ()),
            placebo=placebo,
            near=Near.parse(near, within) if near else None,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


Query_ = Annotated[AdvancedQuery, Depends(advanced_query)]


def _order(query: AdvancedQuery, sort: str | None) -> Order:
    """The order asked for, if the query allows it; else the query's default."""
    if sort == "relevance" and query.index_expressions()[0] is not None:
        return "relevance"
    if sort == "distance" and query.near is not None:
        return "distance"
    if sort not in (None, "relevance", "distance"):
        return Sort.parse(sort)
    return default_order(query)


@router.get(
    "/search/advanced",
    response_model=AdvancedSearchOut,
    responses=NOT_INSTALLED,
    name="advancedSearch",
)
def advanced_search(
    request: Request,
    state: State,
    filter: Filter,
    query: Query_,
    sort: Annotated[
        str | None,
        Query(
            pattern=f"^(relevance|distance|-?({'|'.join(SORT_KEYS)}))$",
            description="`relevance` (with words to match) or `distance` (with `near`), the "
            "default in that order; or a trial list sort, `-last_update` without either.",
        ),
    ] = None,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Response:
    """Trials within the filter that the fields find, a page at a time.

    Text fields search the full-text index, each in its own part of a trial; inclusion,
    exclusion, primary and secondary outcomes are then checked in the text of the newest
    candidates (`sections` says how many). Each hit says where its words are (`snippets`)
    and, with a place, its nearest site."""
    stats = state.stats()
    order = _order(query, sort)
    with state.read() as reader:
        version = reader.data_version()
        etag = state.etag(version)
        if (cached := not_modified(request, etag)) is not None:
            return cached

        def search() -> Found:
            index = trial_index(state, reader)
            within = index.present if filter.is_empty else stats.mask(reader, index, filter)
            sites = state.sites.get(reader.connection, version) if query.near else None
            return find(
                reader,
                index,
                within,
                query,
                order,
                sites=sites,
                table=state.texts,
                cached=lambda key, make: stats.cached(reader, ("advanced", *key), make),
            )

        def run() -> bytes:
            found: Found = stats.cached(reader, ("advanced-found", query, filter, order), search)
            hits = describe(reader, found, query, state.texts, offset=offset, limit=limit)
            total = len(found.ids)
            return orjson.dumps(
                {
                    "data_version": version,
                    "total": total,
                    "sort": order if isinstance(order, str) else str(order),
                    "ranked": found.ranked if order == "relevance" else None,
                    "sections": found.sections,
                    "read": [
                        {
                            "field": name,
                            "all": [[str(term) for term in group] for group in words.groups],
                            "none": [str(term) for term in words.excluded],
                        }
                        for name, words in query.text
                    ],
                    "offset": offset,
                    "next_offset": offset + limit if offset + limit < total else None,
                    "items": hits,
                }
            )

        key = ("advanced-page", query, filter, order, offset, limit)
        return data_json(stats.cached(reader, key, run), etag)


@router.get("/places", response_model=PlacesOut, responses=NOT_INSTALLED, name="findPlaces")
def find_places(
    request: Request,
    state: State,
    q: Annotated[
        str,
        Query(
            min_length=1,
            max_length=200,
            description="The start of a city's name; after a comma, of its state or country.",
        ),
    ],
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> Response:
    """Places with trial sites, from the sites' own coordinates: cities starting with `q`,
    then with a word starting with it, most sites first."""
    stats = state.stats()
    with state.read() as reader:
        version = reader.data_version()
        etag = state.etag(version)
        if (cached := not_modified(request, etag)) is not None:
            return cached

        def run() -> bytes:
            sites = state.sites.get(reader.connection, version)
            places = [
                {
                    "city": place.city,
                    "state": place.state,
                    "country": place.country,
                    "country_name": COUNTRY_NAMES.get(place.country or "", (None, None))[1],
                    "lat": place.lat,
                    "lon": place.lon,
                    "sites": place.sites,
                }
                for place in sites.find(q, limit)
            ]
            return orjson.dumps({"data_version": version, "places": places})

        return data_json(stats.cached(reader, ("places", q, limit), run), etag)
