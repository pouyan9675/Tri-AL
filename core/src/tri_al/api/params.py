"""Query parameters: ``TrialFilter`` and paging, the same on every data endpoint (§5.5).

A field is repeated for several values (``status=RECRUITING&status=COMPLETED``), never
comma-separated, since names may hold commas. Ranges are ``from..to`` with either end open:
``start=2020..2023``, ``enrollment=100..``. Plugin filter fields are read the same way under
their own names.
"""

from typing import Annotated

from fastapi import HTTPException, Query, Request, status

from tri_al.filters import DateRange, IntRange, TrialFilter
from tri_al.storage import SORT_KEYS, Sort

Values = Annotated[list[str] | None, Query()]
DateRangeParam = Annotated[
    str | None, Query(description="`from..to`, either end open: `2020..2023`, `2024-06..`")
]


def _range[R: (DateRange, IntRange)](kind: type[R], name: str, text: str | None) -> R | None:
    if text is None or not text.strip():
        return None
    try:
        return kind.parse(text)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{name}: {exc}") from None


def trial_filter(
    request: Request,
    status_: Annotated[
        list[str] | None, Query(alias="status", description="Overall status codes: RECRUITING, ...")
    ] = None,
    phase: Annotated[list[str] | None, Query(description="PHASE1, PHASE2_PHASE3, NA, ...")] = None,
    study_type: Annotated[list[str] | None, Query(description="INTERVENTIONAL, ...")] = None,
    conditions: Annotated[list[str] | None, Query(description="Condition names")] = None,
    mesh: Annotated[
        list[str] | None, Query(description="MeSH descriptor codes; narrower terms match too")
    ] = None,
    interventions: Annotated[list[str] | None, Query(description="Intervention names")] = None,
    intervention_types: Annotated[list[str] | None, Query(description="DRUG, DEVICE, ...")] = None,
    sponsors: Annotated[list[str] | None, Query(description="Lead or collaborator names")] = None,
    sponsor_class: Annotated[
        list[str] | None, Query(description="The lead sponsor's class: INDUSTRY, NIH, ...")
    ] = None,
    countries: Annotated[list[str] | None, Query(description="ISO 3166-1 alpha-2 codes")] = None,
    start: DateRangeParam = None,
    completion: DateRangeParam = None,
    first_posted: DateRangeParam = None,
    last_update: DateRangeParam = None,
    enrollment: Annotated[
        str | None, Query(description="`from..to`, either end open: `100..500`, `1000..`")
    ] = None,
    has_results: bool | None = None,
    q: Annotated[
        str | None,
        Query(description="Full-text: every word must match; or trial IDs, which find those"),
    ] = None,
) -> TrialFilter:
    fields = request.app.state.tri_al.filter_fields
    extra = tuple(
        (field, tuple(values))
        for name, field in fields.items()
        if (values := request.query_params.getlist(name))
    )
    try:
        return TrialFilter(
            status=tuple(status_ or ()),
            phase=tuple(phase or ()),
            study_type=tuple(study_type or ()),
            conditions=tuple(conditions or ()),
            mesh=tuple(mesh or ()),
            interventions=tuple(interventions or ()),
            intervention_types=tuple(intervention_types or ()),
            sponsors=tuple(sponsors or ()),
            sponsor_class=tuple(sponsor_class or ()),
            countries=tuple(countries or ()),
            start=_range(DateRange, "start", start),
            completion=_range(DateRange, "completion", completion),
            first_posted=_range(DateRange, "first_posted", first_posted),
            last_update=_range(DateRange, "last_update", last_update),
            enrollment=_range(IntRange, "enrollment", enrollment),
            has_results=has_results,
            q=q,
            extra=extra,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


def sort_param(
    sort: Annotated[
        str,
        Query(
            description=f"One of {', '.join(SORT_KEYS)}; a leading `-` sorts descending",
            pattern=f"^-?({'|'.join(SORT_KEYS)})$",
        ),
    ] = "-last_update",
) -> Sort:
    return Sort.parse(sort)
