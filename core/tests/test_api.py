import contextlib
import gzip
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx2 as httpx
import orjson
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import text

from tri_al.api import create_app
from tri_al.api import models as m
from tri_al.config import Config
from tri_al.filters import TrialFilter
from tri_al.jobs import JobQueue, Worker, core_job_types
from tri_al.pipeline import Pipeline
from tri_al.plugins import API_VERSION, LoadedPlugins, Plugin, Registry
from tri_al.plugins.registry import Contributions
from tri_al.stats import Chart, ChartContext, Rows
from tri_al.storage import SQLiteStorage, open_app_db
from tri_al.testing import FakeSource, fake_study

HEADERS = {"X-Tri-AL": "1"}
BASE_URL = "http://127.0.0.1:8000"

STUDIES = (
    fake_study(
        "F1",
        "Donepezil in mild Alzheimer disease",
        updated="2026-09-01",
        status="RECRUITING",
        conditions=["Alzheimer Disease"],
        countries=["US"],
        enrollment=120,
    ),
    fake_study(
        "F2",
        "Aducanumab and amyloid",
        updated="2026-10-14",
        status="COMPLETED",
        conditions=["Alzheimer Disease", "Dementia"],
        countries=["US", "JP"],
        enrollment=40,
    ),
    fake_study(
        "F3",
        "Sleep and memory",
        updated="2026-10-15",
        status="COMPLETED",
        conditions=["Sleep"],
        countries=["DE"],
    ),
)
CHANGED = (
    fake_study(
        "F3",
        "Sleep, memory and mood",
        updated="2026-10-16",
        status="COMPLETED",
        conditions=["Sleep"],
        countries=["DE"],
    ),
)


def by_status(ctx: ChartContext, filter: TrialFilter) -> Rows:
    by = ctx.counts(filter).by("status")
    return [{"label": str(code), "value": count} for code, count in sorted(by.items(), key=str)]


CHART = Chart(id="by_status", title="By status", widget="bar", query=by_status)


def plugins_for(source: FakeSource, *extra: Plugin) -> LoadedPlugins:
    contributions = Contributions()
    fake = Plugin(name="fake", version="1.0", api_version=API_VERSION, register=lambda r: None)
    Registry("fake", None, contributions).add_source(source)
    Registry("fake", None, contributions).add_chart(CHART)
    for plugin in extra:
        plugin.register(Registry(plugin.name, None, contributions))
    return LoadedPlugins(plugins=[fake, *extra], settings={}, contributions=contributions)


class Served:
    def __init__(
        self,
        tmp_path: Path,
        *,
        install: bool = True,
        use_index: bool = True,
        extra: tuple[Plugin, ...] = (),
    ) -> None:
        self.data_dir = tmp_path / "data"
        self.config_file = tmp_path / "tri-al.toml"
        self.source = FakeSource(studies=STUDIES, changed=CHANGED)
        self.pipeline = Pipeline(
            data_dir=self.data_dir, sources=[self.source], workers=0, charts=[CHART]
        )
        if install:
            self.pipeline.run_install()
        self.config = Config.model_validate({"data": {"dir": str(self.data_dir)}})
        self.app = create_app(
            self.config,
            plugins_for(self.source, *extra),
            config_file=self.config_file,
            use_index=use_index,
        )

    def worker(self, queue: JobQueue) -> Worker:
        return Worker(
            queue, core_job_types(lambda: self.pipeline), config=self.config, data_dir=self.data_dir
        )

    def wait_for_index(self) -> None:
        state = self.app.state.tri_al
        if state.use_index and state.storage() is not None:
            with state.read() as reader:
                state.stats().wait_for_index(reader.data_version())


@pytest.fixture(params=[True, False], ids=["index", "sql"])
def served(request: pytest.FixtureRequest, tmp_path: Path) -> Served:
    return Served(tmp_path, use_index=request.param)


@pytest.fixture
def client(served: Served) -> Iterator[TestClient]:
    with TestClient(served.app, base_url=BASE_URL) as client:
        served.wait_for_index()
        yield client


def body[M: BaseModel](response: httpx.Response, model: type[M], code: int = 200) -> M:
    assert response.status_code == code, response.text
    return model.model_validate(response.json())


def ids(page: m.TrialPageOut) -> list[str]:
    return [item.source_id for item in page.items]


# --- meta and trials ----------------------------------------------------------------------


def test_meta(client: TestClient) -> None:
    meta = body(client.get("/api/meta"), m.MetaOut)

    assert (meta.installed, meta.data_version, meta.trials) == (True, 1, 3)
    assert meta.last_run is not None
    assert (meta.last_run.kind, meta.last_run.new) == ("install", 3)
    assert meta.sources == {"fake": "2026-10-15"}
    assert meta.plugins == ["fake"]


def test_before_an_install(tmp_path: Path) -> None:
    served = Served(tmp_path, install=False)
    with TestClient(served.app, base_url=BASE_URL) as client:
        meta = body(client.get("/api/meta"), m.MetaOut)
        assert (meta.installed, meta.trials) == (False, 0)
        assert client.get("/api/trials").status_code == 503
        assert client.post("/api/jobs/update", headers=HEADERS).status_code == 409


def test_trial_list_filters_sorts_and_pages(client: TestClient) -> None:
    newest = body(client.get("/api/trials"), m.TrialPageOut)
    assert ids(newest) == ["F3", "F2", "F1"]
    assert newest.total == 3
    assert newest.items[0].conditions == ["Sleep"]

    first = body(client.get("/api/trials", params={"sort": "id", "limit": 2}), m.TrialPageOut)
    assert ids(first) == ["F1", "F2"]
    assert first.next_cursor is not None
    second = body(
        client.get("/api/trials", params={"sort": "id", "limit": 2, "cursor": first.next_cursor}),
        m.TrialPageOut,
    )
    assert (ids(second), second.next_cursor, second.total) == (["F3"], None, None)

    completed = body(
        client.get("/api/trials", params=[("status", "COMPLETED"), ("countries", "jp")]),
        m.TrialPageOut,
    )
    assert (ids(completed), completed.total) == (["F2"], 1)
    big = body(client.get("/api/trials", params={"enrollment": "100.."}), m.TrialPageOut)
    assert ids(big) == ["F1"]


@pytest.mark.parametrize(
    ("params", "code", "detail"),
    [
        ({"cursor": "nonsense!"}, 400, "invalid cursor"),
        ({"sort": "title"}, 422, ""),
        ({"start": "2024..2020"}, 422, "starts after it ends"),
        ({"enrollment": "lots"}, 422, "enrollment"),
        ({"limit": 0}, 422, ""),
    ],
)
def test_trial_list_rejects_bad_parameters(
    client: TestClient, params: dict[str, Any], code: int, detail: str
) -> None:
    response = client.get("/api/trials", params=params)

    assert response.status_code == code
    assert detail in response.text


def test_a_cursor_belongs_to_its_sort(client: TestClient) -> None:
    page = body(client.get("/api/trials", params={"sort": "id", "limit": 1}), m.TrialPageOut)

    response = client.get("/api/trials", params={"sort": "-id", "cursor": page.next_cursor})

    assert response.status_code == 400
    assert "another sort" in response.text


def test_trial_detail_and_changes(client: TestClient, served: Served) -> None:
    detail = body(client.get("/api/trials/F2"), m.TrialDetailOut)
    assert (detail.title, detail.status, detail.countries) == (
        "Aducanumab and amyloid",
        "COMPLETED",
        ["US", "JP"],
    )
    assert detail.location_scope == "BOTH"
    assert client.get("/api/trials/NOPE").status_code == 404
    assert client.get("/api/trials/F2", params={"source": "other"}).status_code == 404

    served.pipeline.run_update()
    changes = body(client.get("/api/trials/F3/changes"), m.ChangesOut)

    assert changes.data_version == 2
    assert [(c.field, c.old, c.new) for c in changes.changes] == [
        ("title", "Sleep and memory", "Sleep, memory and mood")
    ]


# --- search, facets and stats -------------------------------------------------------------


def test_search(client: TestClient) -> None:
    result = body(client.get("/api/search", params={"q": "alzheimer"}), m.SearchOut)

    assert sorted(hit.source_id for hit in result.hits) == ["F1", "F2"]
    assert (result.candidates, result.capped) == (2, False)
    assert [(n.kind, n.name) for n in result.names] == [("condition", "Alzheimer Disease")]
    assert any(part.match for part in result.hits[0].snippet)
    within = body(
        client.get("/api/search", params={"q": "alzheimer", "status": "RECRUITING"}), m.SearchOut
    )
    assert [hit.source_id for hit in within.hits] == ["F1"]
    assert client.get("/api/search").status_code == 422


def test_facets(client: TestClient) -> None:
    facets = body(client.get("/api/facets", params={"status": "COMPLETED"}), m.FacetsOut)

    assert facets.total == 2
    # The status facet ignores the status filter; the others don't.
    assert [(f.value, f.count) for f in facets.facets["status"]] == [
        ("COMPLETED", 2),
        ("RECRUITING", 1),
    ]
    assert [(f.value, f.count) for f in facets.facets["countries"]] == [
        ("DE", 1),
        ("JP", 1),
        ("US", 1),
    ]
    some = body(
        client.get("/api/facets", params=[("fields", "conditions"), ("limit", "1")]), m.FacetsOut
    )
    assert list(some.facets) == ["conditions"]
    assert [f.label for f in some.facets["conditions"]] == ["Alzheimer Disease"]
    assert client.get("/api/facets", params={"fields": "colour"}).status_code == 422


def test_dashboard_and_chart_data(client: TestClient) -> None:
    dashboard = body(client.get("/api/dashboard"), m.DashboardOut)
    assert [chart.id for chart in dashboard.charts] == ["by_status"]
    assert dashboard.charts[0].plugin == "fake"
    assert "conditions" in [facet.field for facet in dashboard.facets]

    plain = body(client.get("/api/stats/by_status"), m.StatsOut)
    assert (plain.filtered, plain.rows) == (
        False,
        [{"label": "COMPLETED", "value": 2}, {"label": "RECRUITING", "value": 1}],
    )
    us = body(client.get("/api/stats/by_status", params={"countries": "US"}), m.StatsOut)
    assert (us.filtered, us.rows) == (
        True,
        [{"label": "COMPLETED", "value": 1}, {"label": "RECRUITING", "value": 1}],
    )
    assert client.get("/api/stats/nope").status_code == 404


# --- HTTP: ETags, gzip, OpenAPI ----------------------------------------------------------


def test_etags_follow_the_data_version(client: TestClient, served: Served) -> None:
    first = client.get("/api/trials")
    etag = first.headers["etag"]
    assert etag.startswith('W/"1-')
    assert first.headers["cache-control"] == "no-cache"
    assert first.headers["server-timing"].startswith("app;dur=")

    again = client.get("/api/trials", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""

    served.pipeline.run_update()
    changed = client.get("/api/trials", headers={"If-None-Match": etag})
    assert changed.status_code == 200
    assert changed.headers["etag"].startswith('W/"2-')
    assert client.get("/api/jobs").headers["cache-control"] == "no-store"


def test_responses_are_gzipped(client: TestClient) -> None:
    raw = httpx.Client(transport=client._transport, base_url=BASE_URL)  # doesn't decode
    with raw.stream("GET", "/api/openapi.json", headers={"Accept-Encoding": "gzip"}) as big:
        assert big.headers["content-encoding"] == "gzip"
        content = b"".join(big.iter_raw())
    assert "paths" in orjson.loads(gzip.decompress(content))

    small = client.get("/api/facets", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in small.headers  # under a kilobyte: not worth it


def test_the_openapi_schema_names_every_operation(client: TestClient) -> None:
    schema = client.get("/api/openapi.json").json()

    operations = {op["operationId"] for path in schema["paths"].values() for op in path.values()}
    assert operations == {
        "getMeta",
        "listTrials",
        "getTrial",
        "getTrialChanges",
        "search",
        "getFacets",
        "getDashboard",
        "getChartData",
        "streamEvents",
        "startUpdate",
        "listJobs",
        "getJob",
        "cancelJob",
        "listPlugins",
        "updatePlugin",
    }
    assert "TrialPageOut" in schema["components"]["schemas"]
    params = {p["name"] for p in schema["paths"]["/api/trials"]["get"]["parameters"]}
    assert {"status", "conditions", "countries", "start", "q", "sort", "cursor", "limit"} <= params


# --- browser protections and access -------------------------------------------------------


@pytest.mark.parametrize(
    ("headers", "code", "detail"),
    [
        ({}, 403, "X-Tri-AL"),
        ({**HEADERS, "Origin": "https://evil.example"}, 403, "evil.example"),
        ({**HEADERS, "Origin": "null"}, 403, "null"),
        ({**HEADERS, "Sec-Fetch-Site": "cross-site"}, 403, "cross-site"),
        ({**HEADERS, "Host": "evil.example:8000"}, 400, "Host"),
        ({**HEADERS, "Origin": "http://localhost:5173"}, 202, ""),
        (HEADERS, 202, ""),
    ],
)
def test_changing_routes_are_protected(
    client: TestClient, headers: dict[str, str], code: int, detail: str
) -> None:
    response = client.post("/api/jobs/update", headers=headers)

    assert response.status_code == code, response.text
    assert detail in response.text


def test_reads_check_the_host_too(client: TestClient) -> None:
    assert client.get("/api/meta", headers={"Host": "rebound.example"}).status_code == 400
    assert client.get("/api/meta", headers={"Host": "localhost:8000"}).status_code == 200


def test_allowed_hosts(tmp_path: Path) -> None:
    served = Served(tmp_path)
    served.app = create_app(
        Config.model_validate(
            {"data": {"dir": str(served.data_dir)}, "server": {"allowed_hosts": ["tri-al.lan"]}}
        ),
        plugins_for(served.source),
        config_file=served.config_file,
    )
    with TestClient(served.app, base_url="http://tri-al.lan") as client:
        assert client.get("/api/meta").status_code == 200


def test_an_access_plugin_decides(tmp_path: Path) -> None:
    class ReadOnly:
        def allows(self, request: object, action: str) -> bool:
            return action == "read"

    def register(registry: Registry) -> None:
        registry.set_access_policy(ReadOnly())

    auth = Plugin(name="auth", version="1.0", api_version=API_VERSION, register=register)
    served = Served(tmp_path, extra=(auth,))
    with TestClient(served.app, base_url=BASE_URL) as client:
        assert client.get("/api/meta").status_code == 200
        response = client.post("/api/jobs/update", headers=HEADERS)
        assert response.status_code == 403
        assert "jobs.update" in response.text


# --- jobs ---------------------------------------------------------------------------------


def test_start_an_update_and_run_it(client: TestClient, served: Served) -> None:
    job = body(client.post("/api/jobs/update", headers=HEADERS), m.JobOut, 202)
    assert (job.type, job.status, job.origin) == ("update", "queued", "api")

    conflict = body(client.post("/api/jobs/update", headers=HEADERS), m.JobConflictOut, 409)
    assert conflict.job.id == job.id

    engine = open_app_db(served.data_dir / "app.db")
    try:
        ended = served.worker(JobQueue(engine)).run_once()
    finally:
        engine.dispose()
    assert ended is not None
    assert ended.status == "succeeded", ended.error

    done = body(client.get(f"/api/jobs/{job.id}"), m.JobOut)
    assert (done.status, done.stage) == ("succeeded", "commit")
    assert done.result is not None
    assert done.result["sources"]["fake"]["updated"] == 1
    assert [j.id for j in body(client.get("/api/jobs"), m.JobsOut).jobs] == [job.id]
    assert body(client.get("/api/meta"), m.MetaOut).data_version == 2
    assert client.get("/api/jobs/999").status_code == 404


def test_cancel_a_queued_job(client: TestClient) -> None:
    job = body(client.post("/api/jobs/update", headers=HEADERS), m.JobOut, 202)

    cancelled = body(client.post(f"/api/jobs/{job.id}/cancel", headers=HEADERS), m.JobOut)

    assert cancelled.status == "cancelled"
    assert client.post("/api/jobs/999/cancel", headers=HEADERS).status_code == 404


def read_events(lines: Iterator[str], count: int) -> list[tuple[str, Any]]:
    events: list[tuple[str, Any]] = []
    name = None
    for line in lines:
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: ") and name is not None:
            events.append((name, orjson.loads(line.removeprefix("data: "))))
            if len(events) == count:
                break
    return events


@contextmanager
def running(app: FastAPI) -> Iterator[str]:
    """``app`` in a real uvicorn server on a free port; yields its base URL.

    TestClient waits for a whole response, so it can't read an event stream as it goes.
    """
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
    thread.start()
    try:
        while not server.started:
            time.sleep(0.01)
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()


def finished(seen: list[tuple[str, Any]]) -> bool:
    """Whether the update's end and the new data version have both been seen."""
    succeeded = any(name == "job" and data["status"] == "succeeded" for name, data in seen)
    return succeeded and ("data_version", {"data_version": 2}) in seen


def test_events_stream_job_progress_and_data_versions(tmp_path: Path) -> None:
    served = Served(tmp_path)
    engine = open_app_db(served.data_dir / "app.db")
    with (
        running(served.app) as url,
        httpx.Client(base_url=url, timeout=10) as client,
        client.stream("GET", "/api/events") as stream,
    ):
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert "content-encoding" not in stream.headers
        lines = stream.iter_lines()
        assert read_events(lines, 1) == [("hello", {"data_version": 1, "jobs": []})]

        job = client.post("/api/jobs/update", headers=HEADERS).json()
        worker = threading.Thread(target=served.worker(JobQueue(engine)).run_once)
        worker.start()
        seen: list[tuple[str, Any]] = []
        with contextlib.suppress(httpx.ReadTimeout):
            while not finished(seen):
                seen += read_events(lines, 1)
        worker.join(10)
    engine.dispose()

    assert finished(seen), seen
    # A poll reports each changed job once, as it is then: a fast job may skip stages.
    statuses = [data["status"] for name, data in seen if name == "job"]
    assert statuses[-1] == "succeeded"
    assert {data["id"] for name, data in seen if name == "job"} == {job["id"]}


def test_events_stop_after_max_events(tmp_path: Path) -> None:
    served = Served(tmp_path)
    with (
        running(served.app) as url,
        httpx.Client(base_url=url, timeout=10) as client,
        client.stream("GET", "/api/events", params={"max_events": 1}) as stream,
    ):
        lines = stream.iter_lines()
        assert read_events(lines, 1)[0][0] == "hello"  # hello doesn't count
        client.post("/api/jobs/update", headers=HEADERS)
        rest = list(lines)  # ends: the server closes the stream after one event

    assert [line for line in rest if line.startswith("event:")] == ["event: job"]


# --- plugins ------------------------------------------------------------------------------


def test_list_and_change_plugins(client: TestClient, served: Served) -> None:
    listed = body(client.get("/api/plugins"), m.PluginsOut)
    sample = next(p for p in listed.plugins if p.name == "sample")
    assert (sample.enabled, sample.loaded, sample.settings) == (True, False, {})

    changed = body(
        client.patch(
            "/api/plugins/sample",
            json={"settings": {"greeting": "Hi"}, "enabled": False},
            headers=HEADERS,
        ),
        m.PluginChangedOut,
    )
    assert changed.restart_required
    assert (changed.plugin.enabled, changed.plugin.settings) == (False, {"greeting": "Hi"})
    assert 'greeting = "Hi"' in served.config_file.read_text()

    removed = body(
        client.patch("/api/plugins/sample", json={"settings": {"greeting": None}}, headers=HEADERS),
        m.PluginChangedOut,
    )
    assert removed.plugin.settings == {}


@pytest.mark.parametrize(
    ("name", "patch", "code"),
    [
        ("sample", {"settings": {"colour": "red"}}, 422),
        ("sample", {"settings": {"enabled": True}}, 422),
        ("sample", {"wrong": 1}, 422),
        ("nobody", {"enabled": True}, 404),
    ],
)
def test_plugin_changes_are_checked(
    client: TestClient, served: Served, name: str, patch: dict[str, Any], code: int
) -> None:
    response = client.patch(f"/api/plugins/{name}", json=patch, headers=HEADERS)

    assert response.status_code == code, response.text
    assert not served.config_file.exists()


def test_plugin_routes_are_mounted(tmp_path: Path) -> None:
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/hello")
    def hello() -> dict[str, str]:
        return {"hello": "world"}

    def register(registry: Registry) -> None:
        registry.add_routes(router)

    served = Served(
        tmp_path,
        extra=(Plugin(name="greet", version="1", api_version=API_VERSION, register=register),),
    )
    with TestClient(served.app, base_url=BASE_URL) as client:
        assert client.get("/api/x/greet/hello").json() == {"hello": "world"}


def test_a_new_install_shows_up(tmp_path: Path) -> None:
    served = Served(tmp_path, install=False)
    with TestClient(served.app, base_url=BASE_URL) as client:
        assert client.get("/api/trials").status_code == 503
        served.pipeline.run_install()
        assert body(client.get("/api/trials"), m.TrialPageOut).total == 3


def test_reads_after_a_direct_write(client: TestClient, served: Served) -> None:
    with SQLiteStorage.open(served.pipeline.trials_db) as storage, storage.engine.begin() as conn:
        conn.execute(text("UPDATE meta SET value = '7' WHERE key = 'data_version'"))

    assert body(client.get("/api/trials"), m.TrialPageOut).data_version == 7
