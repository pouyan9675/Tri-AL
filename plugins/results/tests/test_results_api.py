"""The plugin end to end: an install builds its tables and charts; the API serves both."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import orjson
import pytest
from fastapi.testclient import TestClient

from tri_al.api import create_app
from tri_al.api import models as m
from tri_al.config import Config
from tri_al.pipeline import FetchContext, Pipeline
from tri_al.plugins import LoadedPlugins, Registry
from tri_al.plugins.registry import Contributions
from tri_al.schema import TrialRecord
from tri_al_results import Settings, plugin
from tri_al_results.api import TrialResultsOut

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "http://127.0.0.1:8000"
WITHOUT_RESULTS = orjson.dumps(
    {"protocolSection": {"identificationModule": {"nctId": "NCT09999999", "briefTitle": "None"}}}
)


@dataclass(frozen=True)
class Studies:
    """ClinicalTrials.gov studies from the fixtures, read just enough to store them."""

    name: str = "ctgov"
    studies: tuple[bytes, ...] = ()

    def fetch_all(self, ctx: FetchContext) -> Iterator[bytes]:
        ctx.total = len(self.studies)
        yield from self.studies

    def fetch_changed(self, since: date, ctx: FetchContext) -> Iterator[bytes]:
        yield from ()

    def normalize(self, raw: dict[str, Any]) -> TrialRecord:
        ident = raw["protocolSection"]["identificationModule"]
        posted = raw["protocolSection"].get("statusModule", {}).get("resultsFirstPostDateStruct")
        return TrialRecord(
            source=self.name,
            source_id=ident["nctId"],
            title=ident["briefTitle"],
            has_results=bool(raw.get("hasResults")),
            results_first_posted=date.fromisoformat(posted["date"]) if posted else None,
        )

    def hashable(self, raw: dict[str, Any]) -> Any:
        return raw


def loaded() -> LoadedPlugins:
    contributions = Contributions()
    plugin.register(Registry("results", Settings(), contributions))
    return LoadedPlugins(
        plugins=[plugin], settings={"results": Settings()}, contributions=contributions
    )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    plugins = loaded()
    contributions = plugins.contributions
    studies = tuple(path.read_bytes() for path in sorted(FIXTURES.glob("*.json")))
    Pipeline(
        data_dir=tmp_path,
        sources=[Studies(studies=(*studies, WITHOUT_RESULTS))],
        workers=0,
        trials_migrations=contributions.migrations_for("trials"),
        charts=list(contributions.charts.values()),
        derived=list(contributions.derived.values()),
    ).run_install()
    config = Config.model_validate({"data": {"dir": str(tmp_path)}})
    app = create_app(config, plugins, config_file=tmp_path / "tri-al.toml", use_index=False)
    with TestClient(app, base_url=BASE_URL) as client:
        yield client


def test_a_trials_results(client: TestClient) -> None:
    response = client.get("/api/x/results/trials/nct04102579")

    assert response.status_code == 200, response.text
    results = TrialResultsOut.model_validate(response.json())
    assert (results.source, results.source_id) == ("ctgov", "NCT04102579")
    assert results.flow is not None
    assert len(results.flow.groups) == 2
    assert results.baseline is not None
    assert results.baseline.total == "BG002"
    assert len(results.outcomes) == 5
    assert results.outcomes[0].analyses[0].p_value == "<0.0001"
    assert results.adverse_events is not None
    assert [g.placebo for g in results.adverse_events.groups] == [False, True]
    assert "medinfo@" not in response.text  # no point of contact

    again = client.get(
        "/api/x/results/trials/NCT04102579", headers={"If-None-Match": response.headers["etag"]}
    )
    assert again.status_code == 304


def test_trials_without_results(client: TestClient) -> None:
    for source_id in ("NCT09999999", "NCT00000000"):
        response = client.get(f"/api/x/results/trials/{source_id}")
        assert response.status_code == 404
        m.ErrorOut.model_validate(response.json())


def test_the_install_built_the_charts(client: TestClient) -> None:
    dashboard = m.DashboardOut.model_validate(client.get("/api/dashboard").json())
    specs = {chart.id: chart for chart in dashboard.charts}
    assert specs["results_race"].format == "percent"
    assert specs["results_race"].page == "results"
    assert specs["results_signals"].widget == "forest"
    sections = [chart.section for chart in dashboard.charts if chart.plugin == "results"]
    assert list(dict.fromkeys(sections)) == [
        "Who took part",
        "Safety",
        "Did it work",
        "Who finished",
    ]

    people = m.StatsOut.model_validate(client.get("/api/stats/results_people").json())
    tiles = {row["key"]: row["value"] for row in people.rows}
    assert tiles["trials"] == 4
    assert tiles["participants"] == 127 + 292 + 6 + 156

    reporting = m.StatsOut.model_validate(client.get("/api/stats/results_race_reporting").json())
    assert sum(sum(v for k, v in row.items() if k != "year") for row in reporting.rows) == 4


def test_the_routes_have_their_own_openapi_schema() -> None:
    from tri_al.api.openapi import plugin_schema

    exported = plugin_schema("results")

    assert list(exported["paths"]) == ["/api/x/results/trials/{source_id}"]
    operation = exported["paths"]["/api/x/results/trials/{source_id}"]["get"]
    assert operation["operationId"] == "getTrialResults"
    assert "TrialResultsOut" in exported["components"]["schemas"]
