"""An in-memory column index of every trial, for counting under any filter (design §5.5).

SQLite answers a narrow filter quickly, but a broad one (every completed trial, say) makes
it visit hundreds of thousands of rows per chart: "top conditions among completed trials"
takes about 450 ms. Each API worker therefore keeps the columns that filters, facets and
charts use in numpy arrays, about 50 MB at 607k trials, built in a few seconds from one
snapshot of ``trials.db``. A filter becomes a boolean mask over trial ids, and each count is
one vectorized pass: the same question takes about 6 ms.

The index belongs to one ``data_version``; the stats engine builds a new one in the
background after an update and asks SQLite meanwhile.
"""

import itertools
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from functools import partial
from typing import Any

import numpy as np
import numpy.typing as npt
import orjson
from sqlalchemy import Connection, func, select

from tri_al.filters import TrialFilter
from tri_al.stats.counts import (
    DATE_COLUMNS,
    LINKS,
    CodedField,
    Count,
    DateField,
    LinkDimension,
)
from tri_al.storage import Cursor, Sort
from tri_al.storage import tables as t
from tri_al.storage.filtering import match_expression, where

type Mask = npt.NDArray[np.bool_]
type Ids = npt.NDArray[np.int32]

NULL_DAY = np.iinfo(np.int32).min
"""A missing date in a date column (days since 1970-01-01)."""

NULL_NUMBER = -1
"""A missing enrollment."""

_EPOCH = date(1970, 1, 1)
_CHUNK = 65_536

_DATE_FILTERS: dict[str, DateField] = {
    "start": "start_date",
    "completion": "completion_date",
    "first_posted": "first_posted",
    "last_update": "last_update",
}


def day_number(day: date) -> int:
    return (day - _EPOCH).days


def from_day_number(number: int) -> date:
    return _EPOCH + timedelta(days=number)


@dataclass(frozen=True, slots=True)
class _Coded:
    values: npt.NDArray[np.int16]  # by trial id: an index into codes, or -1 for NULL
    codes: tuple[Any, ...]

    def code_of(self, value: Any) -> int | None:
        try:
            return self.codes.index(value)
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class _Linked:
    trial: Ids  # one entry per link row
    value: Ids  # the entity id (or country index) of each row
    size: int  # max value + 1


class TrialIndex:
    """Columns of every trial in memory, as of ``data_version``. Read-only once built."""

    def __init__(
        self,
        data_version: int,
        present: Mask,
        coded: dict[str, _Coded],
        dates: dict[str, npt.NDArray[np.int32]],
        enrollment: npt.NDArray[np.int64],
        links: dict[str, _Linked],
        countries: tuple[str, ...],
        intervention_types: _Linked,
        drug_links: Mask,
        type_codes: tuple[str | None, ...],
    ) -> None:
        self.data_version = data_version
        self.present = present
        self.size = len(present)
        self._coded = coded
        self._dates = dates
        self._enrollment = enrollment
        self._links = links
        self._countries = countries
        self._country_index = {code: i for i, code in enumerate(countries)}
        self._types = intervention_types
        self._type_codes = type_codes
        self._drug_links = drug_links
        self._orders: dict[str, tuple[Ids, npt.NDArray[np.int64]]] = {}

    @property
    def trials(self) -> int:
        return int(self.present.sum())

    @property
    def nbytes(self) -> int:
        """Memory the arrays use."""
        arrays: list[npt.NDArray[Any]] = [self.present, self._enrollment, self._drug_links]
        arrays += [c.values for c in self._coded.values()]
        arrays += list(self._dates.values())
        arrays += [
            a for link in (*self._links.values(), self._types) for a in (link.trial, link.value)
        ]
        return sum(a.nbytes for a in arrays)

    # --- building ---------------------------------------------------------------------------

    @classmethod
    def build(cls, conn: Connection, data_version: int) -> "TrialIndex":
        """Read every trial's indexed columns in ``conn``'s transaction."""
        raw = conn.connection.driver_connection
        size = int(conn.execute(select(func.coalesce(func.max(t.trials.c.id), 0))).scalar_one()) + 1
        present = np.zeros(size, np.bool_)
        coded_columns = ("status", "phase", "study_type", "lead_sponsor_class", "has_results")
        codes: list[dict[Any, int]] = [{} for _ in coded_columns]
        coded = [np.full(size, -1, np.int16) for _ in coded_columns]
        dates: dict[str, npt.NDArray[np.int32]] = {
            name: np.full(size, NULL_DAY, np.int32) for name in DATE_COLUMNS
        }
        enrollment = np.full(size, NULL_NUMBER, np.int64)
        day = "coalesce(CAST(julianday({0}) - 2440587.5 AS INTEGER), {1})"
        cursor = raw.execute(  # type: ignore[union-attr]
            f"SELECT id, {', '.join(coded_columns)}, "
            + ", ".join(day.format(name, NULL_DAY) for name in DATE_COLUMNS)
            + f", coalesce(enrollment, {NULL_NUMBER}) FROM trials"
        )
        while rows := cursor.fetchmany(_CHUNK):
            columns = list(zip(*rows, strict=True))
            ids = np.fromiter(columns[0], np.int32, len(rows))
            present[ids] = True
            for i, values in enumerate(columns[1 : 1 + len(coded_columns)]):
                mapping = codes[i]
                coded[i][ids] = [
                    -1 if value is None else mapping.setdefault(value, len(mapping))
                    for value in values
                ]
            offset = 1 + len(coded_columns)
            for j, name in enumerate(DATE_COLUMNS):
                dates[name][ids] = np.fromiter(columns[offset + j], np.int32, len(rows))
            enrollment[ids] = np.fromiter(columns[-1], np.int64, len(rows))
        names = ("status", "phase", "study_type", "sponsor_class", "has_results")
        coded_by_name = {
            name: _Coded(values, tuple(sorted(mapping, key=mapping.__getitem__)))
            for name, values, mapping in zip(names, coded, codes, strict=True)
        }
        coded_by_name["has_results"] = _Coded(
            coded_by_name["has_results"].values,
            tuple(bool(v) for v in coded_by_name["has_results"].codes),
        )

        links = {
            name: _read_pairs(raw, f"SELECT trial_id, {key} FROM {table}")
            for name, table, key in (
                ("conditions", "trial_conditions", "condition_id"),
                ("sponsors", "trial_sponsors", "sponsor_id"),
            )
        }
        countries = tuple(
            code
            for (code,) in raw.execute("SELECT code FROM countries ORDER BY code")  # type: ignore[union-attr]
        )
        country_index = {code: i for i, code in enumerate(countries)}
        links["countries"] = _read_pairs(
            raw, "SELECT trial_id, country_code FROM trial_countries", country_index.__getitem__
        )
        type_codes: dict[str | None, int] = {}
        chunks: list[npt.NDArray[np.int32]] = []
        cursor = raw.execute("SELECT trial_id, intervention_id, type FROM trial_interventions")  # type: ignore[union-attr]
        while rows := cursor.fetchmany(_CHUNK):
            flat = itertools.chain.from_iterable(
                (trial, intervention, type_codes.setdefault(type_, len(type_codes)))
                for trial, intervention, type_ in rows
            )
            chunks.append(np.fromiter(flat, np.int32, 3 * len(rows)).reshape(-1, 3))
        triples = np.concatenate(chunks) if chunks else np.zeros((0, 3), np.int32)
        trial_arr, type_arr = triples[:, 0].copy(), triples[:, 2].copy()
        intervention_arr = triples[:, 1].copy()
        links["interventions"] = _Linked(
            trial_arr, intervention_arr, int(intervention_arr.max()) + 1 if len(triples) else 0
        )
        type_list = tuple(sorted(type_codes, key=type_codes.__getitem__))
        drug = type_codes.get("DRUG", -1)
        # One row per (trial, type), so a trial with two drugs counts once for DRUG.
        typed = type_arr != type_codes.get(None, -1)
        pairs = np.unique(trial_arr[typed].astype(np.int64) * 64 + type_arr[typed])
        intervention_types = _Linked(
            (pairs // 64).astype(np.int32), (pairs % 64).astype(np.int32), len(type_list)
        )
        return cls(
            data_version,
            present,
            coded_by_name,
            dates,
            enrollment,
            links,
            countries,
            intervention_types,
            type_arr == drug,
            type_list,
        )

    # --- filters ----------------------------------------------------------------------------

    def mask(
        self, conn: Connection, filter: TrialFilter, cached: Callable[..., Mask] | None = None
    ) -> Mask:
        """The trials ``filter`` matches, as a boolean array by trial id.

        Fields the index holds are evaluated in memory. Names (conditions, interventions,
        sponsors) are looked up in ``conn``; MeSH terms, full-text queries and plugin fields
        are asked of SQLite. ``cached(key, make)`` may keep those slower parts.
        """

        def keep(key: tuple[Any, ...], make: Callable[[], Mask]) -> Mask:
            return make() if cached is None else cached(key, make)

        mask = self.present.copy()
        for name in ("status", "phase", "study_type", "sponsor_class"):
            values = getattr(filter, name)
            if values:
                mask &= self._coded_mask(name, values)
        if filter.has_results is not None:
            mask &= self._coded_mask("has_results", (filter.has_results,))
        for name, field in _DATE_FILTERS.items():
            dates = getattr(filter, name)
            if dates is not None:
                days = self._dates[field]
                mask &= days != NULL_DAY
                if dates.since is not None:
                    mask &= days >= day_number(dates.since)
                if dates.until is not None:
                    mask &= days <= day_number(dates.until)
        if filter.enrollment is not None:
            mask &= self._enrollment != NULL_NUMBER
            if filter.enrollment.low is not None:
                mask &= self._enrollment >= filter.enrollment.low
            if filter.enrollment.high is not None:
                mask &= self._enrollment <= filter.enrollment.high
        for name in ("conditions", "interventions", "sponsors"):
            values = getattr(filter, name)
            if values:
                mask &= keep(("names", name, values), partial(self._named, conn, name, values))
        if filter.countries:
            wanted = [self._country_index[c] for c in filter.countries if c in self._country_index]
            mask &= self._linked_mask(self._links["countries"], wanted)
        if filter.intervention_types:
            wanted = [
                i for i, code in enumerate(self._type_codes) if code in filter.intervention_types
            ]
            mask &= self._linked_mask(self._types, wanted)
        if filter.mesh:
            mask &= keep(("mesh", filter.mesh), partial(self._mesh, conn, filter.mesh))
        if filter.q is not None:
            q = filter.q
            mask &= keep(("q", q), lambda: self._full_text(conn, q))
        if filter.extra:
            extra = TrialFilter(extra=filter.extra)
            mask &= keep(("sql", extra), lambda: self._from_sql(conn, extra))
        return mask

    def _coded_mask(self, name: str, values: Iterable[Any]) -> Mask:
        column_ = self._coded[name]
        wanted = [code for value in values if (code := column_.code_of(value)) is not None]
        return np.isin(column_.values, wanted)

    def _linked_mask(self, link: _Linked, wanted: Sequence[int]) -> Mask:
        mask = np.zeros(self.size, np.bool_)
        if wanted:
            mask[link.trial[np.isin(link.value, wanted)]] = True
        return mask

    def _named(self, conn: Connection, name: str, names: Sequence[str]) -> Mask:
        link = LINKS[name]
        ids = (
            conn.execute(select(link.entity_key).where(link.entity.c.name.in_(names)))
            .scalars()
            .all()
        )
        return self._linked_mask(self._links[name], ids)

    def _from_sql(self, conn: Connection, filter: TrialFilter) -> Mask:
        return self._ids_mask(conn.execute(select(t.trials.c.id).where(*where(filter))).scalars())

    def _mesh(self, conn: Connection, codes: Sequence[str]) -> Mask:
        # Straight from the link table's (mesh_term_id, kind, trial_id) index.
        return self._raw_ids(
            conn,
            "SELECT trial_id FROM trial_mesh WHERE mesh_term_id IN "
            "(SELECT id FROM mesh_terms WHERE code IN (SELECT value FROM json_each(?)))",
            (orjson.dumps(list(codes)).decode(),),
        )

    def _full_text(self, conn: Connection, q: str) -> Mask:
        match = match_expression(q)
        if match is None:
            return self.present
        return self._raw_ids(
            conn, "SELECT rowid FROM trials_fts WHERE trials_fts MATCH ?", (match,)
        )

    def _raw_ids(self, conn: Connection, sql: str, params: tuple[Any, ...]) -> Mask:
        """A mask of the ids ``sql`` selects, read on the sqlite3 cursor in bulk.

        A broad text query finds over half a million trials; SQLAlchemy's per-row work
        would cost more than the query.
        """
        cursor = conn.connection.driver_connection.execute(sql, params)  # type: ignore[union-attr]
        mask = np.zeros(self.size, np.bool_)
        while rows := cursor.fetchmany(_CHUNK):
            found = np.fromiter(itertools.chain.from_iterable(rows), np.int64, len(rows))
            mask[found[found < self.size]] = True
        return mask

    def _ids_mask(self, ids: Iterable[int]) -> Mask:
        mask = np.zeros(self.size, np.bool_)
        found = np.fromiter(ids, np.int64)
        mask[found[found < self.size]] = True
        return mask

    # --- counting ---------------------------------------------------------------------------

    def counts(self, conn: Connection, mask: Mask) -> "IndexCounts":
        return IndexCounts(self, conn, mask)

    # --- paging -----------------------------------------------------------------------------

    def page(
        self, mask: Mask, sort: Sort, after: Cursor | None, limit: int
    ) -> tuple[list[int], Cursor | None]:
        """Ids of up to ``limit`` matching trials after ``after``, and the next cursor.

        Orders exactly as ``SQLiteStorage.query_trials`` does, cursors included.
        """
        order, keys = self._order(sort.key)
        if sort.descending:
            end = (
                len(order)
                if after is None
                else int(np.searchsorted(keys, self._key(sort.key, after)))
            )
            candidates = order[:end][::-1]
        else:
            start = (
                0
                if after is None
                else int(np.searchsorted(keys, self._key(sort.key, after), side="right"))
            )
            candidates = order[start:]
        picked = candidates[mask[candidates]][: limit + 1]
        ids = [int(i) for i in picked[:limit]]
        more = len(picked) > limit
        return ids, (self._cursor(sort.key, ids[-1]) if more and ids else None)

    def _order(self, key: str) -> tuple[Ids, npt.NDArray[np.int64]]:
        """Trial ids in ascending ``(value, id)`` order, missing values first, and their keys.

        Descending order is this one reversed: values from the largest, then the trials
        without one, ties by id in the same direction, as in SQLite.
        """
        if key not in self._orders:
            ids = np.flatnonzero(self.present).astype(np.int32)
            if key == "id":
                shifted = np.zeros(len(ids), np.int64)
            else:
                values, missing = self._sort_values(key)
                values, missing = values[ids].astype(np.int64), missing[ids]
                shifted = np.where(missing, 0, values - _VALUE_FLOOR + 1)
            keys = shifted * np.int64(self.size) + ids.astype(np.int64)
            order = np.argsort(keys, kind="stable")
            self._orders[key] = (ids[order], keys[order])
        return self._orders[key]

    def _sort_values(self, key: str) -> tuple[npt.NDArray[Any], Mask]:
        if key == "enrollment":
            return self._enrollment, self._enrollment == NULL_NUMBER
        days = self._dates[key]
        return days, days == NULL_DAY

    def _key(self, key: str, cursor: Cursor) -> int:
        value, trial_id = cursor
        if key == "id" or value is None:
            number = 0
        elif key == "enrollment":
            number = int(value) - _VALUE_FLOOR + 1
        else:
            number = day_number(date.fromisoformat(value)) - _VALUE_FLOOR + 1
        return number * self.size + int(trial_id)

    def _cursor(self, key: str, trial_id: int) -> Cursor:
        if key == "id":
            return (trial_id, trial_id)
        if key == "enrollment":
            value = int(self._enrollment[trial_id])
            return (None if value == NULL_NUMBER else value, trial_id)
        day = int(self._dates[key][trial_id])
        return (None if day == NULL_DAY else from_day_number(day).isoformat(), trial_id)


_VALUE_FLOOR = -1_000_000
"""Below every sort value: dates as days since 1970 (about ±100,000) and enrollments (≥ 0)."""


class IndexCounts:
    """``Counts`` answered from a ``TrialIndex``; names come from ``conn``."""

    def __init__(self, index: TrialIndex, conn: Connection, mask: Mask) -> None:
        self._index = index
        self._conn = conn
        self._mask = mask

    def total(self) -> int:
        return int(np.count_nonzero(self._mask))

    def by(self, field: CodedField) -> dict[Any, int]:
        column_ = self._index._coded[field]
        counts = np.bincount(column_.values[self._mask] + 1, minlength=len(column_.codes) + 1)
        result: dict[Any, int] = {}
        if counts[0]:
            result[None] = int(counts[0])
        for code, count in zip(column_.codes, counts[1:], strict=True):
            if count:
                result[code] = int(count)
        return result

    def _link_counts(self, link: _Linked, rows: Mask | None = None) -> npt.NDArray[np.int64]:
        selected = self._mask[link.trial]
        if rows is not None:
            selected &= rows
        return np.bincount(link.value[selected], minlength=link.size)

    def top(self, dimension: LinkDimension, limit: int) -> list[Count]:
        if limit <= 0:
            return []
        counts = self._link_counts(self._index._links[dimension])
        nonzero = np.flatnonzero(counts)
        if len(nonzero) > limit:
            kth = np.partition(counts[nonzero], -limit)[-limit]
            nonzero = nonzero[counts[nonzero] >= kth]
        chosen = nonzero[np.argsort(-counts[nonzero], kind="stable")][:limit]
        if dimension == "countries":
            codes = [self._index._countries[i] for i in chosen]
            names = dict(
                self._conn.execute(
                    select(t.countries.c.code, t.countries.c.name).where(
                        t.countries.c.code.in_(codes)
                    )
                ).all()
            )
            return [
                Count(code, names[code], int(counts[i]))
                for code, i in zip(codes, chosen, strict=True)
            ]
        link = LINKS[dimension]
        ids = [int(i) for i in chosen]
        names = dict(
            self._conn.execute(
                select(link.entity_key, link.entity.c.name).where(link.entity_key.in_(ids))
            ).all()
        )
        return [Count(names[i], names[i], int(counts[i])) for i in ids]

    def intervention_types(self) -> dict[str, int]:
        types = self._index._types
        counts = self._link_counts(types)
        codes = self._index._type_codes
        result: dict[str, int] = {}
        for i, code in enumerate(codes):
            if code is not None and i < len(counts) and counts[i]:
                result[code] = int(counts[i])
        return result

    def distinct(self, dimension: LinkDimension, *, intervention_type: str | None = None) -> int:
        link = self._index._links[dimension]
        rows = None
        if intervention_type is not None:
            if intervention_type != "DRUG":
                raise ValueError("the index only counts distinct interventions of type DRUG")
            rows = self._index._drug_links
        return int(np.count_nonzero(self._link_counts(link, rows)))

    def per_day(self, field: DateField, since: date, until: date) -> dict[date, int]:
        days = self._index._dates[field][self._mask]
        low, high = day_number(since), day_number(until)
        days = days[(days >= low) & (days <= high)]
        counts = np.bincount(days - low, minlength=high - low + 1)
        return {from_day_number(low + i): int(n) for i, n in enumerate(counts) if n}

    def latest(self, field: DateField) -> date | None:
        days = self._index._dates[field][self._mask]
        days = days[days != NULL_DAY]
        return None if len(days) == 0 else from_day_number(int(days.max()))


def _read_pairs(raw: Any, sql: str, convert: Callable[[Any], int] | None = None) -> _Linked:
    cursor = raw.execute(sql)
    trials: list[npt.NDArray[np.int32]] = []
    values: list[npt.NDArray[np.int32]] = []
    while rows := cursor.fetchmany(_CHUNK):
        flat = itertools.chain.from_iterable(
            rows if convert is None else ((trial, convert(value)) for trial, value in rows)
        )
        pairs = np.fromiter(flat, np.int32, 2 * len(rows)).reshape(-1, 2)
        trials.append(pairs[:, 0])
        values.append(pairs[:, 1])
    trial = np.concatenate(trials) if trials else np.zeros(0, np.int32)
    value = np.concatenate(values) if values else np.zeros(0, np.int32)
    return _Linked(trial, value, int(value.max()) + 1 if len(value) else 0)
