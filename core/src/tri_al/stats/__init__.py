"""The stats engine (docs/design.md §5.5): chart specs, facets, counts and the trial index."""

from tri_al.stats.charts import WIDGETS, Chart, ChartContext, Facet, Layout, Rows, Widget
from tri_al.stats.counts import (
    CODED_FIELDS,
    LINK_DIMENSIONS,
    CodedField,
    Count,
    Counts,
    DateField,
    LinkDimension,
    SqlCounts,
)
from tri_al.stats.engine import (
    FACET_PREFIX,
    PRECOMPUTED_FACET_LIMIT,
    ChartData,
    ResultCache,
    StatsEngine,
    UnknownChart,
    encode_counts,
    precompute,
)
from tri_al.stats.facets import CORE_FACETS
from tri_al.stats.index import IndexCounts, TrialIndex

__all__ = [
    "CODED_FIELDS",
    "CORE_FACETS",
    "FACET_PREFIX",
    "LINK_DIMENSIONS",
    "PRECOMPUTED_FACET_LIMIT",
    "WIDGETS",
    "Chart",
    "ChartContext",
    "ChartData",
    "CodedField",
    "Count",
    "Counts",
    "DateField",
    "Facet",
    "IndexCounts",
    "Layout",
    "LinkDimension",
    "ResultCache",
    "Rows",
    "SqlCounts",
    "StatsEngine",
    "TrialIndex",
    "UnknownChart",
    "Widget",
    "encode_counts",
    "precompute",
]
