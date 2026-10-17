"""Checks against the real ClinicalTrials.gov API. Opt in with ``uv run pytest -m live``."""

import itertools
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from trial_al.pipeline import FetchContext, prepare
from trial_al_ctgov import CtgovSource
from trial_al_ctgov.source import BASE_URL

pytestmark = pytest.mark.live


def test_fetch_changed_reads_recent_studies(tmp_path: Path) -> None:
    source = CtgovSource(page_size=20)
    since = date.today() - timedelta(days=7)
    ctx = FetchContext(downloads=tmp_path)
    studies = source.fetch_changed(since, ctx)
    try:
        raws = list(itertools.islice(studies, 20))
    finally:
        studies.close()

    results = [prepare(source, raw) for raw in raws]
    assert [result.error for result in results] == [None] * len(raws)
    assert len(raws) == 20
    assert all(r.record and r.record.last_update and r.record.last_update >= since for r in results)
    assert ctx.total is not None
    assert ctx.total >= 20


def test_the_bulk_download_still_ignores_range() -> None:
    """If this fails, the endpoint honors Range now and interrupted downloads could resume."""
    url = f"{BASE_URL}/studies/download"
    with httpx.stream(
        "GET", url, params={"format": "json.zip"}, headers={"Range": "bytes=0-99"}, timeout=60
    ) as response:
        assert response.status_code == 200
        assert "content-length" not in response.headers
        assert response.headers["content-type"] == "application/zip"
