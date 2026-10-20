"""The registry methods milestone 4 added: charts, filter fields, search, routes, jobs, access."""

import pytest
from fastapi import APIRouter
from sqlalchemy import Connection, true

from tri_al.access import AllowAll
from tri_al.filters import FilterField, TrialFilter
from tri_al.jobs import JobType
from tri_al.plugins import PluginError, Registry
from tri_al.plugins.registry import Contributions
from tri_al.search import Hit, ProviderResult, merge
from tri_al.stats import Chart, ChartContext, Layout, Rows, Series


def rows(ctx: ChartContext, filter: TrialFilter) -> Rows:
    return []


class Semantic:
    name = "semantic"

    def search(self, conn: Connection, q: str, filter: TrialFilter, limit: int) -> ProviderResult:
        return ProviderResult([])


def registry(plugin: str, contributions: Contributions) -> Registry:
    return Registry(plugin, None, contributions)


def test_charts_are_recorded_with_their_plugin() -> None:
    contributions = Contributions()
    registry("a", contributions).add_chart(Chart(id="x", title="X", widget="bar", query=rows))

    assert contributions.charts["x"].plugin == "a"
    with pytest.raises(PluginError, match="already added by plugin 'a'"):
        registry("b", contributions).add_chart(Chart(id="x", title="X", widget="pie", query=rows))
    with pytest.raises(PluginError, match=r"isn.t a tri_al\.stats\.Chart"):
        registry("b", contributions).add_chart("x")  # type: ignore[arg-type]


def test_chart_specs_are_checked() -> None:
    with pytest.raises(ValueError, match="unknown widget"):
        Chart(id="x", title="X", widget="radar", query=rows)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="1 to 4"):
        Layout(width=5)
    with pytest.raises(ValueError, match="'pie' charts have no series"):
        Chart(id="x", title="X", widget="pie", query=rows, series=(Series("a", "A"),))
    assert Chart(id="x", title="X", widget="bar", query=rows, series=(Series("a", "A"),))
    with pytest.raises(ValueError, match="unknown format"):
        Chart(id="x", title="X", widget="bar", query=rows, format="money")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown format"):
        Series("a", "A", "money")  # type: ignore[arg-type]
    assert Chart(id="x", title="X", widget="bar", query=rows).page == "dashboard"
    with pytest.raises(ValueError, match="unknown page"):
        Chart(id="x", title="X", widget="bar", query=rows, page="report")  # type: ignore[arg-type]


def test_filter_fields_cant_take_core_names() -> None:
    contributions = Contributions()
    field = FilterField(name="x_score", title="Score", clause=lambda values: true())
    registry("x", contributions).add_filter_field(field)

    assert contributions.filter_fields["x_score"].plugin == "x"
    for name in ("status", "sort", "x_score"):
        with pytest.raises(PluginError, match=r"core name|already added"):
            registry("y", contributions).add_filter_field(
                FilterField(name=name, title="?", clause=lambda values: true())
            )


def test_search_providers_routes_jobs_and_access() -> None:
    contributions = Contributions()
    plugin = registry("p", contributions)
    plugin.add_search_provider(Semantic())
    plugin.add_routes(APIRouter())
    plugin.add_job(JobType(name="reindex", run=lambda ctx: None))
    plugin.set_access_policy(AllowAll())

    assert list(contributions.search_providers) == ["semantic"]
    assert list(contributions.routes) == ["p"]
    assert contributions.jobs["reindex"].plugin == "p"
    assert contributions.access_policy is not None
    assert contributions.access_policy[0] == "p"
    other = registry("q", contributions)
    with pytest.raises(PluginError, match="already added"):
        other.add_search_provider(Semantic())
    with pytest.raises(PluginError, match="already exists"):
        other.add_job(JobType(name="update", run=lambda ctx: None))
    with pytest.raises(PluginError, match="already set the access policy"):
        other.set_access_policy(AllowAll())
    with pytest.raises(PluginError, match="already added routes"):
        plugin.add_routes(APIRouter())
    with pytest.raises(NotImplementedError):
        other.add_enricher(object())


def test_merging_search_providers() -> None:
    fts = ProviderResult([Hit(1, 9.0), Hit(2, 5.0), Hit(3, 1.0)])
    semantic = ProviderResult([Hit(3, 0.9), Hit(4, 0.8)])

    assert merge({"fts": fts}, 2) == [Hit(1, 9.0), Hit(2, 5.0)]
    merged = merge({"fts": fts, "semantic": semantic}, 4)
    assert [hit.id for hit in merged] == [3, 1, 2, 4]  # 3 is in both lists
    assert merge({}, 5) == []
