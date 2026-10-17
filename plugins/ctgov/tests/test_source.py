from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import orjson
import pytest

from trial_al.pipeline import FetchContext, FetchError, Progress, Source
from trial_al.testing import SourceContract
from trial_al_ctgov import CtgovSource, Settings, plugin
from trial_al_ctgov.client import MAX_ATTEMPTS
from trial_al_ctgov.source import BULK_FILE

if TYPE_CHECKING:
    from tests.conftest import FakeApi, Sleeps, ZipMaker

SINCE = date(2026, 10, 16)  # what the recorded pages asked for
STUDIES = Path(__file__).parent / "fixtures" / "studies"


def offline(api: FakeApi, sleeps: Sleeps | None = None) -> CtgovSource:
    wait = (lambda _: None) if sleeps is None else sleeps
    return CtgovSource(transport=httpx.MockTransport(api), sleep=wait)


def nct_ids(raws: list[bytes]) -> list[str]:
    return [orjson.loads(raw)["protocolSection"]["identificationModule"]["nctId"] for raw in raws]


class TestCtgovSourceContract(SourceContract):
    @pytest.fixture
    def source(self) -> Source:
        return CtgovSource()

    @pytest.fixture
    def samples(self) -> list[bytes]:
        return [path.read_bytes() for path in sorted(STUDIES.glob("*.json"))]

    @pytest.fixture
    def offline_source(self, api: FakeApi) -> Source:
        return offline(api)

    @pytest.fixture
    def fetch_context(self, tmp_path: Path, bulk_zip: Path) -> FetchContext:
        return FetchContext(downloads=tmp_path / "downloads", from_file=bulk_zip)

    @pytest.fixture
    def since(self) -> date:
        return SINCE


def test_the_plugin_registers_the_source_with_its_settings() -> None:
    from trial_al.plugins import Registry
    from trial_al.plugins.registry import Contributions

    contributions = Contributions()
    settings = Settings(page_size=250, timeout=5)

    plugin.register(Registry("ctgov", settings, contributions))

    assert contributions.sources == {"ctgov": CtgovSource(page_size=250, timeout=5)}


# --- fetch_changed --------------------------------------------------------------------------


def test_fetch_changed_pages_through_the_results(api: FakeApi, tmp_path: Path) -> None:
    ctx = FetchContext(downloads=tmp_path)

    raws = list(offline(api).fetch_changed(SINCE, ctx))

    assert nct_ids(raws) == [
        "NCT01834001",
        "NCT07708831",
        "NCT07823400",
        "NCT06565195",
        "NCT04886245",
        "NCT00001154",
    ]
    assert (ctx.total, ctx.notes) == (1591, {"data_date": "2026-10-16", "pages": 2})


def test_fetch_changed_asks_for_studies_posted_since_a_date(api: FakeApi, tmp_path: Path) -> None:
    list(offline(api).fetch_changed(SINCE, FetchContext(downloads=tmp_path)))

    first, second = (dict(request.url.params) for request in api.requests)
    assert first == {
        "format": "json",
        "filter.advanced": "AREA[LastUpdatePostDate]RANGE[2026-10-16,MAX]",
        "pageSize": "1000",
        "countTotal": "true",
    }
    assert second["pageToken"] == "ZVNj7o2Elu8o3lpzXcinvarumpOQJJxuZfSk2_g"
    assert "countTotal" not in second
    assert api.requests[0].url.path == "/api/v2/studies"
    assert api.requests[0].headers["user-agent"].startswith("trial-al-ctgov/")


def test_fetch_changed_yields_each_study_as_its_own_document(api: FakeApi, tmp_path: Path) -> None:
    from tests.conftest import recorded_page

    raws = list(offline(api).fetch_changed(SINCE, FetchContext(downloads=tmp_path)))

    assert orjson.loads(raws[0]) == recorded_page(1)["studies"][0]


def test_rate_limits_and_server_errors_are_retried(
    api: FakeApi, sleeps: Sleeps, tmp_path: Path
) -> None:
    api.failures.extend(
        [
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(503),
            httpx.Response(502),
        ]
    )

    raws = list(offline(api, sleeps).fetch_changed(SINCE, FetchContext(downloads=tmp_path)))

    assert len(raws) == 6
    assert sleeps == [7.0, 4.0, 8.0]


def test_retry_after_can_be_a_date(api: FakeApi, sleeps: Sleeps, tmp_path: Path) -> None:
    api.failures.append(
        httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
    )

    list(offline(api, sleeps).fetch_changed(SINCE, FetchContext(downloads=tmp_path)))

    assert sleeps == [0.0]  # that date is long past


def test_dropped_connections_are_retried(api: FakeApi, sleeps: Sleeps, tmp_path: Path) -> None:
    api.failures.append(httpx.ConnectError("connection refused"))

    raws = list(offline(api, sleeps).fetch_changed(SINCE, FetchContext(downloads=tmp_path)))

    assert (len(raws), sleeps) == (6, [2.0])


def test_retries_give_up_eventually(api: FakeApi, sleeps: Sleeps, tmp_path: Path) -> None:
    api.failures.extend(httpx.Response(503) for _ in range(MAX_ATTEMPTS))
    source = offline(api, sleeps)

    with pytest.raises(FetchError, match=f"GET /studies: HTTP 503, {MAX_ATTEMPTS} times"):
        list(source.fetch_changed(SINCE, FetchContext(downloads=tmp_path)))

    assert sleeps == [2.0, 4.0, 8.0, 16.0, 32.0]


def test_other_errors_fail_at_once(api: FakeApi, sleeps: Sleeps, tmp_path: Path) -> None:
    api.failures.append(httpx.Response(400, text="bad filter"))
    source = offline(api, sleeps)

    with pytest.raises(FetchError, match="returned HTTP 400: bad filter"):
        list(source.fetch_changed(SINCE, FetchContext(downloads=tmp_path)))

    assert sleeps == []


def test_a_page_that_isnt_json(api: FakeApi, tmp_path: Path) -> None:
    api.failures.append(httpx.Response(200, text="<html>maintenance</html>"))

    with pytest.raises(FetchError, match="didn't return JSON"):
        list(offline(api).fetch_changed(SINCE, FetchContext(downloads=tmp_path)))


# --- fetch_all ------------------------------------------------------------------------------


def test_fetch_all_reads_a_bulk_file_in_nct_order(
    bulk_zip: Path, samples: list[bytes], tmp_path: Path
) -> None:
    ctx = FetchContext(downloads=tmp_path, from_file=bulk_zip)

    raws = list(CtgovSource().fetch_all(ctx))

    assert raws == sorted(samples, key=lambda raw: nct_ids([raw]))
    assert ctx.total == 6
    assert ctx.notes == {"file": str(bulk_zip), "studies": 6, "data_date": "2026-10-16"}


def test_fetch_all_downloads_the_bulk_file(api: FakeApi, tmp_path: Path) -> None:
    reports: list[Progress] = []
    ctx = FetchContext(downloads=tmp_path / "downloads", progress=reports.append)

    raws = list(offline(api).fetch_all(ctx))

    path = tmp_path / "downloads" / BULK_FILE
    assert len(raws) == 6
    assert path.read_bytes() == api.bulk
    assert [request.url.path for request in api.requests] == ["/api/v2/studies/download"]
    assert dict(api.requests[0].url.params) == {"format": "json.zip"}
    assert api.requests[0].headers["accept-encoding"] == "identity"
    assert ctx.notes["download"]["seconds"] >= 0
    record = json.loads((tmp_path / "downloads" / f"{BULK_FILE}.json").read_text())
    assert record["bytes"] == len(api.bulk)
    assert record["sha256"] == hashlib.sha256(api.bulk).hexdigest()
    assert record["etag"] == '"0/0.34.1/test"'
    assert ctx.notes["download"]["sha256"] == record["sha256"]
    assert reports[0] == Progress("download", 0, None, "bytes")
    assert reports[-1] == Progress("download", len(api.bulk), None, "bytes", "done")
    assert not (tmp_path / "downloads" / f"{BULK_FILE}.part").exists()


def test_a_resumed_install_reuses_a_complete_download(api: FakeApi, tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    list(offline(api).fetch_all(FetchContext(downloads=downloads)))
    api.requests.clear()
    ctx = FetchContext(downloads=downloads, reuse_download=True)

    raws = list(offline(api).fetch_all(ctx))

    assert (len(raws), api.requests) == (6, [])
    assert ctx.notes["download"]["reused"] is True


def test_a_new_install_downloads_again(api: FakeApi, tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    list(offline(api).fetch_all(FetchContext(downloads=downloads)))

    list(offline(api).fetch_all(FetchContext(downloads=downloads)))

    assert len(api.requests) == 2


def test_a_download_that_was_cut_short_isnt_reused(api: FakeApi, tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    list(offline(api).fetch_all(FetchContext(downloads=downloads)))
    with (downloads / BULK_FILE).open("ab") as file:
        file.write(b"extra")  # no longer the size its record says

    list(offline(api).fetch_all(FetchContext(downloads=downloads, reuse_download=True)))

    assert len(api.requests) == 2
    assert (downloads / BULK_FILE).read_bytes() == api.bulk


def test_a_failed_download_leaves_no_file(api: FakeApi, sleeps: Sleeps, tmp_path: Path) -> None:
    api.failures.extend(httpx.Response(500) for _ in range(MAX_ATTEMPTS))
    ctx = FetchContext(downloads=tmp_path / "downloads")

    with pytest.raises(FetchError, match="downloading /studies/download: HTTP 500"):
        list(offline(api, sleeps).fetch_all(ctx))

    assert not (tmp_path / "downloads" / BULK_FILE).exists()


def test_a_bulk_file_that_isnt_a_zip(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"<html>not a zip</html>")

    with pytest.raises(FetchError, match="isn't a readable zip file"):
        list(CtgovSource().fetch_all(FetchContext(downloads=tmp_path, from_file=bad)))


def test_a_damaged_bulk_file(tmp_path: Path, zip_maker: ZipMaker, samples: list[bytes]) -> None:
    path = zip_maker(tmp_path / "bulk.zip", samples[:1])
    data = bytearray(path.read_bytes())
    data[60:70] = b"\0" * 10  # inside the first member's compressed data
    path.write_bytes(bytes(data))

    with pytest.raises(FetchError, match="is damaged at"):
        list(CtgovSource().fetch_all(FetchContext(downloads=tmp_path, from_file=path)))
