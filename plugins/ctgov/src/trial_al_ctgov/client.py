"""HTTP for ClinicalTrials.gov API v2: polite retries, and the bulk download.

Rate limits (429) and server errors (5xx) are retried with exponential backoff, honoring
``Retry-After``; so are dropped connections and timeouts. Anything else fails at once.
"""

import email.utils
import hashlib
import json
import os
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import httpx
import orjson

from trial_al.pipeline import FetchError, Progress, ProgressCallback

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 6
MAX_DELAY = 60.0
CHUNK_SIZE = 1 << 20
PROGRESS_EVERY = 16 << 20  # bytes between download progress reports


@dataclass(frozen=True, slots=True)
class Download:
    """A finished bulk download, as recorded beside it in ``<file>.json``."""

    path: Path
    url: str
    bytes: int
    sha256: str
    etag: str | None
    downloaded_at: str
    seconds: float | None = None  # how long it took; not kept in the record

    def notes(self) -> dict[str, Any]:
        notes = {
            "file": str(self.path),
            "bytes": self.bytes,
            "sha256": self.sha256,
            "etag": self.etag,
            "downloaded_at": self.downloaded_at,
        }
        return notes if self.seconds is None else notes | {"seconds": self.seconds}


class Client:
    """A small client for the API; use it as a context manager so it closes."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        user_agent: str = "trial-al-ctgov",
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": user_agent},
            follow_redirects=True,
        )
        self._sleep = sleep

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def get_json(self, path: str, params: Mapping[str, str | int]) -> Any:
        """GET ``path`` and parse the JSON, retrying politely."""

        def attempt() -> Any:
            response = self._http.get(path, params=dict(params))
            _check(response)
            try:
                return orjson.loads(response.content)
            except orjson.JSONDecodeError as exc:
                raise FetchError(f"{response.url} didn't return JSON: {exc}") from exc

        return self._retrying(f"GET {path}", attempt)

    def download(
        self,
        path: str,
        params: Mapping[str, str | int],
        dest: Path,
        progress: ProgressCallback,
    ) -> Download:
        """Stream ``path`` to ``dest``, recording its size and SHA-256 in ``<dest>.json``.

        The file is written to ``<dest>.part`` and renamed when complete, so ``dest`` is
        never half-written. ClinicalTrials.gov doesn't honor ``Range`` on the bulk download
        (checked 2026-10-17: a Range request gets 200 and the whole file), so a dropped
        download starts over.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")

        def attempt() -> tuple[int, str, str, str | None]:
            # The file is a zip already; gzipping it again only costs the server time.
            headers = {"Accept-Encoding": "identity"}
            with self._http.stream("GET", path, params=dict(params), headers=headers) as response:
                _check(response)
                size, digest = _save(response.iter_bytes(CHUNK_SIZE), part, progress)
                return size, digest, str(response.url), response.headers.get("etag")

        started = time.monotonic()
        size, digest, url, etag = self._retrying(f"downloading {path}", attempt)
        download = Download(
            path=dest,
            url=url,
            bytes=size,
            sha256=digest,
            etag=etag,
            downloaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
            seconds=round(time.monotonic() - started, 1),
        )
        os.replace(part, dest)
        record = {
            key: value for key, value in download.notes().items() if key not in {"file", "seconds"}
        }
        sidecar(dest).write_text(json.dumps({"url": url, **record}, indent=2) + "\n")
        return download

    def _retrying[T](self, what: str, attempt: Callable[[], T]) -> T:
        for number in range(1, MAX_ATTEMPTS + 1):
            try:
                return attempt()
            except _Retry as retry:
                if number == MAX_ATTEMPTS:
                    raise FetchError(f"{what}: {retry.reason}, {number} times") from None
                self._sleep(_backoff(number, retry.retry_after))
            except httpx.TransportError as exc:
                if number == MAX_ATTEMPTS:
                    raise FetchError(f"{what} failed {number} times: {exc!r}") from exc
                self._sleep(_backoff(number, None))
        raise AssertionError("unreachable")


class _Retry(Exception):
    def __init__(self, reason: str, retry_after: str | None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


def _check(response: httpx.Response) -> None:
    """Raise _Retry for a status worth retrying, FetchError for other errors."""
    if response.status_code in RETRY_STATUSES:
        raise _Retry(f"HTTP {response.status_code}", response.headers.get("retry-after"))
    if response.is_error:
        response.read()
        raise FetchError(
            f"{response.request.url} returned HTTP {response.status_code}: {response.text[:300]}"
        )


def sidecar(path: Path) -> Path:
    """Where a download's record is kept: ``<file>.json``."""
    return path.with_name(path.name + ".json")


def read_download(path: Path) -> Download | None:
    """The complete download at ``path``, or None if there isn't one (or it was cut short)."""
    try:
        record = json.loads(sidecar(path).read_text())
        size = path.stat().st_size
    except (OSError, ValueError):
        return None
    if record.get("bytes") != size:
        return None
    return Download(
        path=path,
        url=record["url"],
        bytes=size,
        sha256=record["sha256"],
        etag=record.get("etag"),
        downloaded_at=record["downloaded_at"],
    )


def _save(chunks: Iterator[bytes], part: Path, progress: ProgressCallback) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = reported = 0
    progress(Progress("download", 0, None, "bytes"))
    with part.open("wb") as file:
        for chunk in chunks:
            file.write(chunk)
            digest.update(chunk)
            size += len(chunk)
            if size - reported >= PROGRESS_EVERY:
                reported = size
                progress(Progress("download", size, None, "bytes"))
    progress(Progress("download", size, None, "bytes", "done"))
    return size, digest.hexdigest()


def _backoff(attempt: int, retry_after: str | None) -> float:
    """Seconds to wait before attempt ``attempt + 1``: what the server asked, or 2, 4, 8..."""
    if retry_after:
        if retry_after.strip().isdigit():
            return min(float(retry_after), MAX_DELAY)
        when = email.utils.parsedate_to_datetime(retry_after)
        if when is not None:
            return min(max((when - datetime.now(UTC)).total_seconds(), 0.0), MAX_DELAY)
    return min(2.0**attempt, MAX_DELAY)
