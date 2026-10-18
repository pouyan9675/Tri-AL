"""``TrialFilter``: one filter for the trial list, charts, facets and search (design §5.5).

A filter is a set of fields. Within a field, a trial matches any of the values; across
fields, it must match every field that is set. An empty field matches every trial, so
``TrialFilter()`` matches them all.

Filters are frozen and their values are kept sorted and without repeats, so two filters
that mean the same thing are equal and hash the same, which makes them good cache keys.
Storage turns a filter into SQL (``tri_al.storage.filtering``); the stats engine also
evaluates filters in memory (``tri_al.stats.index``).
"""

import calendar
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, fields, replace
from datetime import date
from typing import TYPE_CHECKING, Any, Literal, Self

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement

type FieldName = Literal[
    "status",
    "phase",
    "study_type",
    "conditions",
    "mesh",
    "interventions",
    "intervention_types",
    "sponsors",
    "sponsor_class",
    "countries",
    "start",
    "completion",
    "first_posted",
    "last_update",
    "enrollment",
    "has_results",
    "q",
]

VALUE_FIELDS: tuple[FieldName, ...] = (
    "status",
    "phase",
    "study_type",
    "conditions",
    "mesh",
    "interventions",
    "intervention_types",
    "sponsors",
    "sponsor_class",
    "countries",
)
"""Fields that hold a tuple of values, any of which a trial may match."""

DATE_FIELDS: tuple[FieldName, ...] = ("start", "completion", "first_posted", "last_update")

_PARTIAL_DATE = re.compile(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?")


def parse_date(text: str, *, end: bool = False) -> date:
    """``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD``; partial dates mean their first day.

    With ``end``, a partial date means its last day instead, for the end of a range.
    """
    match = _PARTIAL_DATE.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"{text!r} is not a date; use YYYY, YYYY-MM or YYYY-MM-DD")
    year, month, day = int(match[1]), match[2], match[3]
    if month is None:
        return date(year, 12, 31) if end else date(year, 1, 1)
    if day is None:
        last = calendar.monthrange(year, int(month))[1]
        return date(year, int(month), last if end else 1)
    return date(year, int(month), int(day))


@dataclass(frozen=True, slots=True)
class DateRange:
    """Dates from ``since`` to ``until``, both included; either end may be open (None)."""

    since: date | None = None
    until: date | None = None

    def __post_init__(self) -> None:
        if self.since is not None and self.until is not None and self.since > self.until:
            raise ValueError(f"the range starts after it ends: {self}")

    @classmethod
    def parse(cls, text: str) -> Self:
        """``2020..2024``, ``2020-01-01..``, ``..2024-06`` or a single ``2024`` (that year)."""
        if ".." not in text:
            return cls(parse_date(text), parse_date(text, end=True))
        since, until = text.split("..", 1)
        return cls(
            parse_date(since) if since.strip() else None,
            parse_date(until, end=True) if until.strip() else None,
        )

    def __str__(self) -> str:
        return f"{self.since or ''}..{self.until or ''}"


@dataclass(frozen=True, slots=True)
class IntRange:
    """Whole numbers from ``low`` to ``high``, both included; either end may be open."""

    low: int | None = None
    high: int | None = None

    def __post_init__(self) -> None:
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError(f"the range starts after it ends: {self}")

    @classmethod
    def parse(cls, text: str) -> Self:
        """``100..500``, ``1000..`` or ``..50``."""
        if ".." not in text:
            value = int(text)
            return cls(value, value)
        low, high = text.split("..", 1)
        return cls(int(low) if low.strip() else None, int(high) if high.strip() else None)

    def __str__(self) -> str:
        return f"{'' if self.low is None else self.low}..{'' if self.high is None else self.high}"


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class FilterField:
    """A filter a plugin declares with ``registry.add_filter_field`` (design §5.6).

    ``clause(values)`` returns a SQL condition on ``tri_al.storage.tables.trials`` that
    trials with any of ``values`` meet, usually ``trials.c.id.in_(select(...))`` over the
    plugin's own table. Fields compare by identity, so filters holding them stay hashable.
    """

    name: str
    title: str
    clause: Callable[[tuple[str, ...]], "ColumnElement[bool]"]
    description: str = ""
    plugin: str = ""


def _values(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({value.strip() for value in values if value.strip()}))


@dataclass(frozen=True, slots=True, kw_only=True)
class TrialFilter:
    """Which trials to show. Coded fields use the API v2 codes of ``tri_al.schema``."""

    status: tuple[str, ...] = ()
    phase: tuple[str, ...] = ()
    study_type: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()  # condition names, as the registry lists them
    mesh: tuple[str, ...] = ()  # MeSH descriptor codes; trials tagged below a term match too
    interventions: tuple[str, ...] = ()  # intervention names
    intervention_types: tuple[str, ...] = ()  # DRUG, BIOLOGICAL, BEHAVIORAL, ...
    sponsors: tuple[str, ...] = ()  # lead or collaborator, by name
    sponsor_class: tuple[str, ...] = ()  # the lead sponsor's class: INDUSTRY, NIH, ...
    countries: tuple[str, ...] = ()  # ISO 3166-1 alpha-2
    start: DateRange | None = None
    completion: DateRange | None = None
    first_posted: DateRange | None = None
    last_update: DateRange | None = None
    enrollment: IntRange | None = None
    has_results: bool | None = None
    q: str | None = None  # full-text: every word must match, as in search
    extra: tuple[tuple[FilterField, tuple[str, ...]], ...] = field(default=())

    def __post_init__(self) -> None:
        for name in VALUE_FIELDS:
            values = _values(getattr(self, name))
            if name == "countries":
                values = tuple(sorted({value.upper() for value in values}))
            object.__setattr__(self, name, values)
        q = None if self.q is None else " ".join(self.q.split()) or None
        object.__setattr__(self, "q", q)
        extra = {}
        for filter_field, values in self.extra:
            if filter_field.name in extra:
                raise ValueError(f"filter field {filter_field.name!r} is given twice")
            if cleaned := _values(values):
                extra[filter_field.name] = (filter_field, cleaned)
        object.__setattr__(self, "extra", tuple(extra[name] for name in sorted(extra)))

    @property
    def is_empty(self) -> bool:
        """Whether the filter matches every trial."""
        return not self.active

    @property
    def active(self) -> tuple[str, ...]:
        """The names of the fields that are set, plugin fields included."""
        names = tuple(
            f.name
            for f in fields(self)
            if f.name != "extra" and getattr(self, f.name) not in ((), None)
        )
        return names + tuple(filter_field.name for filter_field, _ in self.extra)

    def without(self, name: str) -> "TrialFilter":
        """This filter with the field ``name`` (core or plugin) cleared."""
        if any(filter_field.name == name for filter_field, _ in self.extra):
            return replace(self, extra=tuple(e for e in self.extra if e[0].name != name))
        if name not in {f.name for f in fields(self)} or name == "extra":
            return self
        default: Any = () if name in VALUE_FIELDS else None
        return replace(self, **{name: default})

    def to_params(self) -> list[tuple[str, str]]:
        """The filter as query parameters, the form ``/api/trials`` and friends read."""
        params: list[tuple[str, str]] = []
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == "extra" or value in ((), None):
                continue
            if isinstance(value, tuple):
                params += ((f.name, item) for item in value)
            elif isinstance(value, bool):
                params.append((f.name, "true" if value else "false"))
            else:
                params.append((f.name, str(value)))
        for filter_field, values in self.extra:
            params += ((filter_field.name, value) for value in values)
        return params


EVERY_TRIAL = TrialFilter()
"""The filter that matches every trial."""
