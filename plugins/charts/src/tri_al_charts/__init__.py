"""Tri-AL's default dashboard charts: v1's dashboard set, as chart specs (design §13).

Trials by phase and by status, the top conditions, trials per country (a map) and the top
countries, trials added and updated per day, and stat tiles for trials, interventions,
drugs, conditions and countries. Every chart is precomputed with each update and can be filtered
with any ``TrialFilter``. The front end only draws them. Settings, in ``tri-al.toml``:

    [plugins.charts]
    top = 15           # bars in the top-conditions and top-countries charts
    recent_days = 90   # days in the new-and-updated chart
"""

from collections.abc import Callable
from datetime import timedelta
from importlib.metadata import version

from pydantic import BaseModel, ConfigDict, Field

from tri_al.filters import EVERY_TRIAL, TrialFilter
from tri_al.plugins import Plugin, Registry
from tri_al.schema import labels
from tri_al.stats import Chart, ChartContext, Layout, Rows, Series

type Query = Callable[[ChartContext, TrialFilter], Rows]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top: int = Field(default=15, ge=1, le=100)
    recent_days: int = Field(default=90, ge=7, le=366)


def by_phase(ctx: ChartContext, filter: TrialFilter) -> Rows:
    """Every phase in order, then any other codes, then trials without a phase."""
    by = ctx.counts(filter).by("phase")
    rows: Rows = [
        {"key": code, "label": name, "value": by.get(code, 0)}
        for code, name in labels.PHASE.items()
    ]
    rows += [
        {"key": code, "label": code, "value": count}
        for code, count in sorted(by.items(), key=lambda item: str(item[0]))
        if code is not None and code not in labels.PHASE
    ]
    if by.get(None):
        rows.append({"key": None, "label": labels.NOT_GIVEN, "value": by[None]})
    return rows


def by_status(ctx: ChartContext, filter: TrialFilter) -> Rows:
    by = ctx.counts(filter).by("status")
    return [
        {"key": code, "label": labels.label(labels.STATUS, code), "value": count}
        for code, count in sorted(by.items(), key=lambda item: (-item[1], str(item[0])))
    ]


def top_conditions(top: int) -> Query:
    def query(ctx: ChartContext, filter: TrialFilter) -> Rows:
        return [
            {"key": c.value, "label": c.label, "value": c.count}
            for c in ctx.counts(filter).top("conditions", top)
        ]

    return query


def top_countries(top: int) -> Query:
    def query(ctx: ChartContext, filter: TrialFilter) -> Rows:
        return [
            {"code": c.value, "label": c.label, "value": c.count}
            for c in ctx.counts(filter).top("countries", top)
        ]

    return query


def new_and_updated(days: int) -> Query:
    """Trials first posted (``new``) and last updated (``updated``) per day, over the last
    ``days`` days of data (not of the calendar).

    Days on which no trial was posted or updated are left out: ClinicalTrials.gov posts
    nothing at weekends or on US federal holidays, and those zeros would hide the trend.
    """

    def query(ctx: ChartContext, filter: TrialFilter) -> Rows:
        every = ctx.counts(EVERY_TRIAL)
        latest = every.latest("last_update")
        if latest is None:
            return []
        since = latest - timedelta(days=days - 1)
        posted = {
            *every.per_day("first_posted", since, latest),
            *every.per_day("last_update", since, latest),
        }
        counts = ctx.counts(filter)
        new = counts.per_day("first_posted", since, latest)
        updated = counts.per_day("last_update", since, latest)
        return [
            {"date": day.isoformat(), "new": new.get(day, 0), "updated": updated.get(day, 0)}
            for day in sorted(posted)
        ]

    return query


def totals(ctx: ChartContext, filter: TrialFilter) -> Rows:
    counts = ctx.counts(filter)
    return [
        {"key": "trials", "label": "Trials", "value": counts.total()},
        {
            "key": "interventions",
            "label": "Interventions",
            "value": counts.distinct("interventions"),
        },
        {
            "key": "drugs",
            "label": "Drugs",
            "value": counts.distinct("interventions", intervention_type="DRUG"),
        },
        {"key": "conditions", "label": "Conditions", "value": counts.distinct("conditions")},
        {"key": "countries", "label": "Countries", "value": counts.distinct("countries")},
    ]


def charts(settings: Settings) -> list[Chart]:
    top, days = settings.top, settings.recent_days
    return [
        Chart(
            id="totals",
            title="At a glance",
            widget="stat",
            query=totals,
            layout=Layout(width=4, order=0),
            description="Trials, and the interventions, drugs, conditions and countries in them.",
        ),
        Chart(
            id="trials_by_country",
            title="Trials by country",
            widget="map",
            query=top_countries(300),
            layout=Layout(width=4, height=2, order=10),
            description="Trials with at least one site in each country.",
            x="code",
        ),
        Chart(
            id="top_countries",
            title=f"Top {top} countries",
            widget="bar",
            query=top_countries(top),
            layout=Layout(width=2, order=20),
        ),
        Chart(
            id="trials_by_phase",
            title="Trials by phase",
            widget="bar",
            query=by_phase,
            layout=Layout(width=2, order=30),
        ),
        Chart(
            id="trials_by_status",
            title="Trials by status",
            widget="bar",
            query=by_status,
            layout=Layout(width=2, order=40),
        ),
        Chart(
            id="top_conditions",
            title=f"Top {top} conditions",
            widget="bar",
            query=top_conditions(top),
            layout=Layout(width=2, order=50),
        ),
        Chart(
            id="new_and_updated",
            title="New and updated trials",
            widget="area",
            query=new_and_updated(days),
            layout=Layout(width=4, order=60),
            description=(
                "Trials first posted, and trials last updated (new ones too), each day of the "
                f"last {days} days of data. Days with nothing posted, like weekends and "
                "holidays, are skipped."
            ),
            x="date",
            series=(Series("new", "New"), Series("updated", "Updated")),
        ),
    ]


def register(registry: Registry) -> None:
    settings = registry.settings
    assert isinstance(settings, Settings)
    for chart in charts(settings):
        registry.add_chart(chart)


plugin = Plugin(
    name="charts",
    version=version("tri-al-charts"),
    api_version=1,
    register=register,
    settings=Settings,
    description="Default dashboard charts: phases, statuses, conditions, countries and more.",
)

__all__ = ["Settings", "charts", "plugin"]
