"""The source contract suite (docs/design.md §5.6, §7 and §11).

Every source plugin must pass it. Subclass ``SourceContract`` in a test module and
override the fixtures:

- ``source``: the source, as the plugin registers it.
- ``samples``: raw documents the source's fetches yield, covering its edge cases.
- ``offline_source`` and ``fetch_context``: a source and context under which ``fetch_all``
  and ``fetch_changed`` read local data instead of the network (a local bulk file in
  ``FetchContext.from_file``, a mocked HTTP client, ...).
- ``since``: the date the ``fetch_changed`` test asks for.
"""

import copy
import pickle
from datetime import date
from pathlib import Path

import orjson
import pytest

from trial_al.pipeline import FetchContext, Source, content_hash, prepare
from trial_al.pipeline.prepare import prepared
from trial_al.plugins.plugin import NAME_PATTERN
from trial_al.schema import TrialRecord, without_repeats
from trial_al.storage import SQLiteStorage
from trial_al.testing.storage import as_stored


def records_of(source: Source, raws: list[bytes]) -> list[TrialRecord]:
    """``raws`` prepared, failing the test on the first that doesn't become a record."""
    records = []
    for raw in raws:
        result = prepare(source, raw)
        assert result.record is not None, f"{result.error} (in {raw[:120]!r}...)"
        records.append(result.record)
    return records


class SourceContract:
    @pytest.fixture
    def source(self) -> Source:
        raise NotImplementedError("override the source fixture")

    @pytest.fixture
    def samples(self) -> list[bytes]:
        raise NotImplementedError("override the samples fixture")

    @pytest.fixture
    def offline_source(self, source: Source) -> Source:
        return source

    @pytest.fixture
    def fetch_context(self, tmp_path: Path) -> FetchContext:
        return FetchContext(downloads=tmp_path / "downloads")

    @pytest.fixture
    def since(self) -> date:
        return date(2000, 1, 1)

    # --- the source -------------------------------------------------------------------------

    def test_is_a_source_with_a_simple_name(self, source: Source) -> None:
        assert isinstance(source, Source)
        assert NAME_PATTERN.fullmatch(source.name), source.name

    def test_survives_pickling(self, source: Source, samples: list[bytes]) -> None:
        copied = pickle.loads(pickle.dumps(source))

        assert records_of(copied, samples) == records_of(source, samples)

    # --- normalize --------------------------------------------------------------------------

    def test_normalize_makes_records_of_this_source(
        self, source: Source, samples: list[bytes]
    ) -> None:
        records = records_of(source, samples)

        assert all(record.source == source.name for record in records)
        assert all(record.source_id and record.title for record in records)
        assert len({record.source_id for record in records}) == len(records)

    def test_normalize_is_pure(self, source: Source, samples: list[bytes]) -> None:
        for raw in samples:
            parsed = orjson.loads(raw)
            untouched = copy.deepcopy(parsed)

            assert source.normalize(parsed) == source.normalize(orjson.loads(raw))
            assert parsed == untouched

    def test_hashable_is_pure_and_stable(self, source: Source, samples: list[bytes]) -> None:
        for raw in samples:
            parsed = orjson.loads(raw)
            untouched = copy.deepcopy(parsed)
            reordered = dict(reversed(parsed.items()))

            assert content_hash(source, parsed) == content_hash(source, reordered)
            assert parsed == untouched

    def test_records_store_and_read_back(
        self, source: Source, samples: list[bytes], tmp_path: Path
    ) -> None:
        records = records_of(source, samples)

        with SQLiteStorage.open(tmp_path / "trials.db") as storage:
            ids = storage.upsert_batch(records)
            for record, trial_id in zip(records, ids, strict=True):
                stored = storage.get_trial(trial_id)
                assert stored == as_stored(without_repeats(record), stored)

    def test_prepares_in_worker_processes(self, source: Source, samples: list[bytes]) -> None:
        results = list(prepared(source, samples, workers=1))

        assert [result.record for result in results] == records_of(source, samples)

    # --- fetching ---------------------------------------------------------------------------

    def test_fetch_all(self, offline_source: Source, fetch_context: FetchContext) -> None:
        raws = list(offline_source.fetch_all(fetch_context))

        records = records_of(offline_source, raws)
        assert records
        assert len({record.source_id for record in records}) == len(records)
        assert fetch_context.total in {None, len(raws)}

    def test_fetch_changed(
        self, offline_source: Source, fetch_context: FetchContext, since: date
    ) -> None:
        raws = list(offline_source.fetch_changed(since, fetch_context))

        records = records_of(offline_source, raws)
        assert records
        assert all(r.last_update is not None and r.last_update >= since for r in records)
