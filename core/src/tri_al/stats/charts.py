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
- ``stacked``: one bar per row (``x``), split into its ``series``, each part shown as its
  share of the bar: what a whole is made of, such as participants by race in each phase
- ``forest``: estimates with confidence intervals, one row each: ``x`` names it, ``y`` is the
  estimate, ``low`` and ``high`` its interval, drawn on a log scale around 1 (ratios); its
  ``series`` are columns of numbers beside each row

A chart's ``format`` says how its numbers read: ``number``, or ``percent`` for fractions (0.25
is 25%). A series can have its own, and a ``stat`` row its own ``format`` key; ``bar`` and
``table`` take ``series`` too, for bars side by side and the table's number columns.

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
    "stacked",
    "forest",
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
    "stacked",
    "forest",
)
SERIES_WIDGETS: tuple[Widget, ...] = ("line", "area", "bar", "table", "stacked", "forest")

type Format = Literal["number", "percent"]
FORMATS: tuple[Format, ...] = ("number", "percent")

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
    """One of several lines, areas, bars or columns in a chart: the row key for its number,
    its name, and how it reads (None: as the chart's ``format``)."""

    key: str
    label: str
    format: Format | None = None

    def __post_init__(self) -> None:
        if self.format is not None and self.format not in FORMATS:
            raise ValueError(f"unknown format {self.format!r}; use one of {', '.join(FORMATS)}")


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
    series: tuple[Series, ...] = ()  # several numbers per row, not just ``y``
    format: Format = "number"  # how the numbers read: "percent" for fractions
    plugin: str = ""  # set by the registry

    def __post_init__(self) -> None:
        if self.widget not in WIDGETS:
            raise ValueError(f"unknown widget {self.widget!r}; use one of {', '.join(WIDGETS)}")
        if self.page not in PAGES:
            raise ValueError(f"unknown page {self.page!r}; use one of {', '.join(PAGES)}")
        if self.series and self.widget not in SERIES_WIDGETS:
            raise ValueError(
                f"{self.widget!r} charts have no series; {', '.join(SERIES_WIDGETS)} do"
            )
        if self.format not in FORMATS:
            raise ValueError(f"unknown format {self.format!r}; use one of {', '.join(FORMATS)}")


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
