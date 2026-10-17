"""Fixtures: real API v2 study documents and recorded responses, served without the network.

``fixtures/studies`` holds six real studies (``/api/v2/studies/<id>``, 2026-10-17):

- NCT01662882: results, phases 2 and 3, month-only dates
- NCT01245725: withdrawn, no locations
- NCT05026866: 216 sites in the US, Puerto Rico and Japan, with coordinates
- NCT06082674: ages in minutes and hours
- NCT07187596: observational (no phase), up to 130 years old
- NCT06716476: a site in Kosovo, which has no ISO 3166-1 code

``fixtures/responses`` holds two recorded pages of ``/api/v2/studies`` filtered on
``LastUpdatePostDate`` from 2026-10-16 (``pageSize=3``), and the API's list of country names.
"""

import zipfile
from collections import deque
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import httpx
import orjson
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
STUDIES = FIXTURES / "studies"
RESPONSES = FIXTURES / "responses"


def study_bytes(nct_id: str) -> bytes:
    return (STUDIES / f"{nct_id}.json").read_bytes()


def study(nct_id: str) -> dict[str, Any]:
    parsed: dict[str, Any] = orjson.loads(study_bytes(nct_id))
    return parsed


def sample_bytes() -> list[bytes]:
    return [path.read_bytes() for path in sorted(STUDIES.glob("*.json"))]


def recorded_page(number: int) -> dict[str, Any]:
    page: dict[str, Any] = orjson.loads((RESPONSES / f"changed_page{number}.json").read_bytes())
    return page


def make_bulk_zip(path: Path, raws: Iterable[bytes]) -> Path:
    """A zip laid out like ``ctg-studies.json.zip``: ``<last two digits>/<NCT id>.json``."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        # Reverse NCT order, so tests see the reader sort.
        for raw in sorted(raws, reverse=True):
            nct_id = orjson.loads(raw)["protocolSection"]["identificationModule"]["nctId"]
            archive.writestr(f"{nct_id[-2:]}/{nct_id}.json", raw)
    return path


class FakeApi:
    """Answers like ClinicalTrials.gov API v2, from the recorded responses.

    ``/studies`` serves recorded page 1, then page 2 for page 1's token (its own token
    removed, so paging ends). ``/studies/download`` serves ``bulk``. ``failures`` is a queue
    of responses (or exceptions) to give first, whatever was asked.
    """

    def __init__(self, bulk: bytes = b"") -> None:
        self.bulk = bulk
        self.failures: deque[httpx.Response | Exception] = deque()
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failures:
            failure = self.failures.popleft()
            if isinstance(failure, Exception):
                raise failure
            return failure
        if request.url.path == "/api/v2/studies/download":
            headers = {"content-type": "application/zip", "etag": '"0/0.34.1/test"'}
            return httpx.Response(200, content=self.bulk, headers=headers)
        if request.url.path == "/api/v2/studies":
            first = recorded_page(1)
            if request.url.params.get("pageToken") == first["nextPageToken"]:
                second = recorded_page(2)
                del second["nextPageToken"]
                return httpx.Response(200, content=orjson.dumps(second))
            return httpx.Response(200, content=orjson.dumps(first))
        return httpx.Response(404, text="not found")


class Sleeps(list[float]):
    """Records waits instead of waiting."""

    def __call__(self, seconds: float) -> None:
        self.append(seconds)


type StudyLoader = Callable[[str], dict[str, Any]]
type ZipMaker = Callable[[Path, Iterable[bytes]], Path]


@pytest.fixture
def samples() -> list[bytes]:
    return sample_bytes()


@pytest.fixture
def load_study() -> StudyLoader:
    """Parse ``fixtures/studies/<NCT id>.json``."""
    return study


@pytest.fixture
def zip_maker() -> ZipMaker:
    return make_bulk_zip


@pytest.fixture
def bulk_zip(tmp_path: Path) -> Path:
    return make_bulk_zip(tmp_path / "bulk.zip", sample_bytes())


@pytest.fixture
def api(bulk_zip: Path) -> FakeApi:
    return FakeApi(bulk_zip.read_bytes())


@pytest.fixture
def sleeps() -> Sleeps:
    return Sleeps()
