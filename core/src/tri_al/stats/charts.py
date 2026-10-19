"""Chart specs that plugins add with ``registry.add_chart`` (docs/design.md §5.5 and §7).

A chart is data, not drawing: ``query`` returns rows (JSON-compatible dicts) for one
filter, and the front end draws them with the widget named in ``widget``. Each widget reads
the rows' ``x`` and ``y`` keys:

- ``bar``, ``pie``: one row per category, ``label`` and ``value``
- ``line``, ``area``: one row per point, in order; with ``series``, a number per series
- ``stat``: one row per tile, ``label`` and ``value``
- ``map``: one row per country, ``code`` (ISO 3166-1 alpha-2), ``label`` and ``value``
- ``table``: any columns
- ``trends``: ranked lists of what is rising, in columns (``group``) for each of a few time
  windows (``window``). A row with ``type: "window"`` describes a window (``label``,
  ``since``, ``until``, ``trials``, ``baseline_since``, ``baseline_trials``); a row with
  ``type: "item"`` is one entry: ``label``, ``value`` (trials in the window), ``baseline``,
  ``expected``, ``growth`` (adjusted for small counts), ``raw_growth`` (null: none before),
  ``confidence`` (``high``, ``medium`` or ``low``) from ``p`` and ``q`` (corrected for the
  ``tested`` entries), ``new``, ``sponsors``, ``series`` (trials per month, oldest first; the
  last ``recent`` are the window) and ``filter`` (query parameters that list its trials)
- ``scatter``: semantic trial points (``x``, ``y``), grouped by ``cluster`` and
  ``cluster_label``; a leading ``type: "summary"`` row describes coverage
- ``scatter3d``: the same in three dimensions, drawn with WebGL. A ``type: "summary"`` row
  first, then a ``type: "cluster"`` row per cluster (``cluster``, ``label``, ``size`` under the
  filter, ``color``: 0 to 7 or null), then a ``type: "point"`` row per trial (``x``, ``y``,
  ``z``, ``cluster``, ``title``, ``source_id``)

A chart's ``page`` says where it's shown: the dashboard, or the analysis page for larger,
interactive views.

Charts marked ``precompute`` are computed with no filter in the same transaction as each
update and stored in ``stats``; filtered views are computed on request and cached.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import Connection

from tri_al.filters import TrialFilter
from tri_al.stats.counts import Count, Counts

type Widget = Literal[
    "bar", "line", "area", "pie", "stat", "table", "map", "trends", "scatter", "scatter3d"
]
WIDGETS: tuple[Widget, ...] = (
    "bar",
    "line",
    "area",
    "pie",
    "stat",
    "table",
    "map",
    "trends",
    "scatter",
    "scatter3d",
)

type Page = Literal["dashboard", "analysis"]
PAGES: tuple[Page, ...] = ("dashboard", "analysis")

type Rows = list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class Layout:
    """Where the dashboard puts a chart: a grid four columns wide, lower ``order`` first."""

    width: int = 2
    height: int = 1
    order: int = 100

    def __post_init__(self) -> None:
        if not 1 <= self.width <= 4 or not 1 <= self.height <= 4:
            raise ValueError(f"width and height must be 1 to 4, not {self.width}x{self.height}")


@dataclass(frozen=True, slots=True)
class Series:
    """One of several lines or areas in a chart: the row key for its number, and its name."""

    key: str
    label: str


@dataclass(frozen=True, slots=True)
class ChartContext:
    """What a chart's query gets: the read transaction, and counts for any filter.

    ``counts(filter)`` uses the API worker's in-memory index when it is ready and SQLite
    otherwise; use ``conn`` for anything ``Counts`` doesn't cover.
    """

    conn: Connection
    counts: Callable[[TrialFilter], Counts]


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class Chart:
    id: str
    title: str
    widget: Widget
    query: Callable[[ChartContext, TrialFilter], Rows]
    precompute: bool = True
    layout: Layout = field(default_factory=Layout)
    description: str = ""
    section: str = ""  # the page section it goes in; "" is the first, untitled one
    page: Page = "dashboard"
    x: str = "label"  # the row key for categories, points or tiles
    y: str = "value"  # the row key for the number
    series: tuple[Series, ...] = ()  # line and area: several numbers per point, not just ``y``
    plugin: str = ""  # set by the registry

    def __post_init__(self) -> None:
        if self.widget not in WIDGETS:
            raise ValueError(f"unknown widget {self.widget!r}; use one of {', '.join(WIDGETS)}")
        if self.page not in PAGES:
            raise ValueError(f"unknown page {self.page!r}; use one of {', '.join(PAGES)}")
        if self.series and self.widget not in ("line", "area"):
            raise ValueError(f"only line and area charts have series, not {self.widget!r}")


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class Derived:
    """Plugin tables rebuilt from the whole dataset before charts are precomputed.

    ``build(conn, data_version)`` runs in the transaction of each install, update or
    embedding backfill that recomputes the stats, just before the precomputed charts, so
    charts can read what it wrote and readers get both with the new data. One that raises is
    rolled back and listed in the run summary's ``stats_errors``. For work too slow to do
    per request, such as laying out a map of every recent trial; filtered views then read
    the table.
    """

    name: str
    build: Callable[[Connection, int], None]
    plugin: str = ""  # set by the registry


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class Facet:
    """Counts beside each option of a filter field, under the rest of the filter.

    ``query(ctx, filter, limit)`` gets the filter without its own field, so choosing one
    status still shows the counts of the others.
    """

    field: str  # the TrialFilter field the options are for
    title: str
    query: Callable[[ChartContext, TrialFilter, int], list[Count]]
    plugin: str = ""
