"""The core's facets: counts beside each filter option in the trial explorer (design §5.5)."""

from collections.abc import Callable, Mapping

from tri_al.filters import TrialFilter
from tri_al.schema import labels
from tri_al.stats.charts import ChartContext, Facet
from tri_al.stats.counts import CodedField, Count, LinkDimension


def _ordered(counts: list[Count], limit: int) -> list[Count]:
    """Most trials first, ties by label, "not given" last."""
    known = sorted((c for c in counts if c.value is not None), key=lambda c: (-c.count, c.label))
    unknown = [c for c in counts if c.value is None]
    return (known + unknown)[:limit]


def coded(
    field: CodedField, names: Mapping[str, str]
) -> Callable[[ChartContext, TrialFilter, int], list[Count]]:
    def query(ctx: ChartContext, filter: TrialFilter, limit: int) -> list[Count]:
        by = ctx.counts(filter).by(field)
        return _ordered(
            [Count(code, labels.label(names, code), count) for code, count in by.items()], limit
        )

    return query


def _has_results(ctx: ChartContext, filter: TrialFilter, limit: int) -> list[Count]:
    by = ctx.counts(filter).by("has_results")
    names = {True: ("true", "Has results"), False: ("false", "No results")}
    return _ordered([Count(*names[bool(value)], count) for value, count in by.items()], limit)


def _intervention_types(ctx: ChartContext, filter: TrialFilter, limit: int) -> list[Count]:
    by = ctx.counts(filter).intervention_types()
    return _ordered(
        [
            Count(code, labels.label(labels.INTERVENTION_TYPE, code), count)
            for code, count in by.items()
        ],
        limit,
    )


def linked(dimension: LinkDimension) -> Callable[[ChartContext, TrialFilter, int], list[Count]]:
    def query(ctx: ChartContext, filter: TrialFilter, limit: int) -> list[Count]:
        return ctx.counts(filter).top(dimension, limit)

    return query


CORE_FACETS: tuple[Facet, ...] = (
    Facet(field="status", title="Status", query=coded("status", labels.STATUS)),
    Facet(field="phase", title="Phase", query=coded("phase", labels.PHASE)),
    Facet(field="study_type", title="Study type", query=coded("study_type", labels.STUDY_TYPE)),
    Facet(
        field="sponsor_class",
        title="Lead sponsor type",
        query=coded("sponsor_class", labels.SPONSOR_CLASS),
    ),
    Facet(field="has_results", title="Results", query=_has_results),
    Facet(field="intervention_types", title="Intervention type", query=_intervention_types),
    Facet(field="countries", title="Country", query=linked("countries")),
    Facet(field="conditions", title="Condition", query=linked("conditions")),
    Facet(field="interventions", title="Intervention", query=linked("interventions")),
    Facet(field="sponsors", title="Sponsor", query=linked("sponsors")),
)
