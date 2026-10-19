"""A source that serves made-up studies from memory, for pipeline tests.

It lives here rather than in a test module so the pipeline's worker processes can import
it, and so plugins can use it to test their event handlers.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any

import orjson

from tri_al.pipeline.source import FetchContext
from tri_al.schema import TrialRecord


def fake_study(
    source_id: str,
    title: str | None = None,
    *,
    updated: str = "2026-10-01",
    snapshot: str = "2026-10-16",
    **fields: Any,
) -> bytes:
    """A raw document for ``FakeSource``.

    ``snapshot`` stands for a field that changes with every data release but not with the
    study (like ClinicalTrials.gov's ``versionHolder``), so ``FakeSource.hashable`` leaves it
    out. Other ``fields``: ``status``, ``enrollment``, ``conditions``, ``countries``,
    ``first_posted`` (``YYYY-MM-DD``), and ``broken=True`` to make normalizing fail.
    """
    study = {"id": source_id, "title": title or f"Study {source_id}", "updated": updated}
    return orjson.dumps(study | {"snapshot": snapshot} | fields)


@dataclass(frozen=True)
class FakeSource:
    """``fetch_all`` serves ``studies``; ``fetch_changed`` serves ``changed`` studies whose
    ``updated`` date is on or after ``since``. Picklable, so it works in worker processes."""

    name: str = "fake"
    studies: tuple[bytes, ...] = ()
    changed: tuple[bytes, ...] = ()

    def fetch_all(self, ctx: FetchContext) -> Iterator[bytes]:
        ctx.total = len(self.studies)
        ctx.notes["studies"] = len(self.studies)
        yield from self.studies

    def fetch_changed(self, since: date, ctx: FetchContext) -> Iterator[bytes]:
        for raw in self.changed:
            if date.fromisoformat(orjson.loads(raw)["updated"]) >= since:
                yield raw

    def normalize(self, raw: dict[str, Any]) -> TrialRecord:
        if raw.get("broken"):
            raise ValueError(f"{raw['id']}: this study is broken")
        return TrialRecord(
            source=self.name,
            source_id=raw["id"],
            title=raw["title"],
            status=raw.get("status"),
            enrollment=raw.get("enrollment"),
            last_update=date.fromisoformat(raw["updated"]),
            first_posted=date.fromisoformat(raw["first_posted"]) if "first_posted" in raw else None,
            conditions=list(raw.get("conditions", [])),
            countries=list(raw.get("countries", [])),
        )

    def hashable(self, raw: dict[str, Any]) -> Any:
        return {key: value for key, value in raw.items() if key != "snapshot"}
