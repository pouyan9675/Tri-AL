"""The ClinicalTrials.gov source: the bulk JSON download for installs, API v2 for updates."""

import time
import zipfile
import zlib
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field
from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx
import orjson

from tri_al.pipeline import FetchContext, FetchError
from tri_al.schema import TrialRecord
from tri_al_ctgov import normalize as ctgov
from tri_al_ctgov.client import Client, read_download

BASE_URL = "https://clinicaltrials.gov/api/v2"
BULK_FILE = "ctg-studies.json.zip"
MAX_PAGE_SIZE = 1_000  # the API caps pageSize here


@dataclass(frozen=True)
class CtgovSource:
    """ClinicalTrials.gov API v2.

    ``fetch_all`` downloads ``ctg-studies.json.zip`` (one JSON file per study, about 2.7 GB
    in October 2026) into ``ctx.downloads`` and reads the studies straight out of it,
    without extracting it. ``fetch_changed`` pages through ``/studies`` filtered on
    ``LastUpdatePostDate``.

    ``transport`` and ``sleep`` replace the network and waiting in tests.
    """

    base_url: str = BASE_URL
    page_size: int = MAX_PAGE_SIZE
    timeout: float = 60.0
    transport: httpx.BaseTransport | None = field(default=None, repr=False, compare=False)
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False, compare=False)

    @property
    def name(self) -> str:
        return ctgov.SOURCE

    def fetch_all(self, ctx: FetchContext) -> Generator[bytes]:
        path = ctx.from_file or self._download(ctx)
        yield from read_bulk(path, ctx)

    def fetch_changed(self, since: date, ctx: FetchContext) -> Generator[bytes]:
        params: dict[str, str | int] = {
            "format": "json",
            "filter.advanced": f"AREA[LastUpdatePostDate]RANGE[{since.isoformat()},MAX]",
            "pageSize": self.page_size,
        }
        pages = 0
        with self._client() as client:
            token: str | None = None
            while pages == 0 or token:
                extra = {"pageToken": token} if token else {"countTotal": "true"}
                page = client.get_json("/studies", params | extra)
                if pages == 0:
                    ctx.total = page.get("totalCount")
                pages += 1
                for study in page.get("studies", []):
                    raw = orjson.dumps(study)
                    if "data_date" not in ctx.notes:
                        ctx.notes["data_date"] = _release_date(raw)
                    yield raw
                token = page.get("nextPageToken")
        ctx.notes["pages"] = pages

    def normalize(self, raw: dict[str, Any]) -> TrialRecord:
        return ctgov.normalize(raw)

    def hashable(self, raw: dict[str, Any]) -> Any:
        return ctgov.hashable(raw)

    def _client(self) -> Client:
        return Client(
            self.base_url,
            timeout=self.timeout,
            transport=self.transport,
            sleep=self.sleep,
            user_agent=f"tri-al-ctgov/{version('tri-al-ctgov')}",
        )

    def _download(self, ctx: FetchContext) -> Path:
        dest = ctx.downloads / BULK_FILE
        if ctx.reuse_download and (earlier := read_download(dest)) is not None:
            ctx.notes["download"] = earlier.notes() | {"reused": True}
            return dest
        with self._client() as client:
            download = client.download(
                "/studies/download", {"format": "json.zip"}, dest, ctx.progress
            )
        ctx.notes["download"] = download.notes()
        return dest


def read_bulk(path: Path, ctx: FetchContext) -> Iterator[bytes]:
    """Each study's JSON in the bulk zip at ``path``, in NCT number order.

    Members are read one at a time, so nothing is extracted to disk. Sets ``ctx.total`` to
    the number of studies and notes the data's release date.
    """
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise FetchError(f"{path} isn't a readable zip file: {exc}") from exc
    with archive:
        # The zip spreads studies over folders by their last two digits ("35/NCT02807935.json");
        # NCT order gives trials ids in registration order.
        members = sorted(
            (info for info in archive.infolist() if info.filename.endswith(".json")),
            key=lambda info: info.filename.rsplit("/", 1)[-1],
        )
        ctx.total = len(members)
        ctx.notes.update(file=str(path), studies=len(members))
        for i, info in enumerate(members):
            try:
                raw = archive.read(info)
            except (OSError, zipfile.BadZipFile, zlib.error) as exc:
                raise FetchError(f"{path} is damaged at {info.filename}: {exc}") from exc
            if i == 0:
                ctx.notes["data_date"] = _release_date(raw)
            yield raw


def _release_date(raw: bytes) -> str | None:
    """The data release a study document comes from (``versionHolder``), if it says."""
    try:
        misc = orjson.loads(raw)["derivedSection"]["miscInfoModule"]
    except (orjson.JSONDecodeError, KeyError, TypeError):
        return None
    value = misc.get("versionHolder") if isinstance(misc, dict) else None
    return value if isinstance(value, str) else None
