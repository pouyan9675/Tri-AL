"""An in-memory column index of every trial, for counting under any filter (design §5.5).

SQLite answers a narrow filter quickly, but a broad one (every completed trial, say) makes
it visit hundreds of thousands of rows per chart: "top conditions among completed trials"
takes about 450 ms. Each API worker therefore keeps the columns that filters, facets,
charts and the term analyses (``tri_al.terms``) use in numpy arrays, built in a few seconds
from one snapshot of ``trials.db``. A filter becomes a boolean mask over trial ids, and each
count is one vectorized pass: the same question takes about 6 ms.

The index belongs to one ``data_version``; the stats engine builds a new one in the
background after an update and asks SQLite meanwhile.
"""

import itertools
from collections.abc import Callable, Iterable, Mapping, Sequence
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
    Timeline,
)
from tri_al.storage import Cursor, Sort
from tri_al.storage import tables as t
from tri_al.storage.filtering import text_query, where

type Mask = npt.NDArray[np.bool_]
type Ids = npt.NDArray[np.int32]

NULL_DAY = np.iinfo(np.int32).min
"""A missing date in a date column (days since 1970-01-01)."""

NULL_NUMBER = -1
"""A missing number: enrollment, an age."""

NO_SPONSOR = -1
"""A trial without a lead sponsor."""

_EPOCH = date(1970, 1, 1)
_CHUNK = 65_536

CODED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("status", "status"),
    ("phase", "phase"),
    ("study_type", "study_type"),
    ("sponsor_class", "lead_sponsor_class"),
    ("has_results", "has_results"),
    ("start_date_type", "start_date_type"),
    ("primary_completion_date_type", "primary_completion_date_type"),
    ("allocation", "allocation"),
    ("masking", "masking"),
    ("intervention_model", "intervention_model"),
    ("primary_purpose", "primary_purpose"),
    ("sex", "sex"),
    ("healthy_volunteers", "healthy_volunteers"),
)
"""Coded columns the index keeps: its name for each, and the ``trials`` column."""

INDEX_DATES: tuple[str, ...] = (*DATE_COLUMNS, "primary_completion_date", "results_first_posted")
"""Date columns the index keeps: the ones ``Counts`` asks about, and two for analyses."""

NUMBERS: tuple[str, ...] = ("enrollment", "min_age_days", "max_age_days", "num_sites")
"""Number columns the index keeps; a missing one is ``NULL_NUMBER``."""

_BOOLEANS = ("has_results", "healthy_volunteers")

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
class CodedColumn:
    """A coded ``trials`` column: each trial's value as an index into ``codes``."""

    values: npt.NDArray[np.int16]  # by trial id: an index into codes, or -1 for NULL
    codes: tuple[Any, ...]

    def code_of(self, value: Any) -> int | None:
        try:
            return self.codes.index(value)
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class LinkColumn:
    """A link table (conditions, MeSH terms, countries, ...): one entry per link row."""

    trial: Ids  # one entry per link row
    value: Ids  # the entity id (or country index) of each row
    size: int  # max value + 1


class TrialIndex:
    """Columns of every trial in memory, as of ``data_version``. Read-only once built."""

    def __init__(
        self,
        data_version: int,
        present: Mask,
        coded: dict[str, CodedColumn],
        dates: dict[str, npt.NDArray[np.int32]],
        numbers: dict[str, npt.NDArray[np.int32]],
        lead_sponsors: Ids,
        links: dict[str, LinkColumn],
        countries: tuple[str, ...],
        intervention_types: LinkColumn,
        drug_links: Mask,
        type_codes: tuple[str | None, ...],
        placebo: Mask,
    ) -> None:
        self.data_version = data_version
        self.present = present
        self.size = len(present)
        self._coded = coded
        self._dates = dates
        self._numbers = numbers
        self._enrollment = numbers["enrollment"]
        self._lead_sponsors = lead_sponsors
        self._links = links
        self._countries = countries
        self._country_index = {code: i for i, code in enumerate(countries)}
        self._types = intervention_types
        self._type_codes = type_codes
        self._drug_links = drug_links
        self._placebo = placebo
        self._orders: dict[str, tuple[Ids, npt.NDArray[np.int64]]] = {}

    @property
    def trials(self) -> int:
        return int(self.present.sum())

    @property
    def nbytes(self) -> int:
        """Memory the arrays use."""
        arrays: list[npt.NDArray[Any]] = [
            self.present,
            self._lead_sponsors,
            self._drug_links,
            self._placebo,
        ]
        arrays += [c.values for c in self._coded.values()]
        arrays += list(self._dates.values())
        arrays += list(self._numbers.values())
        arrays += [
            a for link in (*self._links.values(), self._types) for a in (link.trial, link.value)
        ]
        return sum(a.nbytes for a in arrays)

    # --- columns, for analyses -------------------------------------------------------------

    def coded(self, name: str) -> CodedColumn:
        """A coded column by its name in ``CODED_COLUMNS``: status, phase, sex, ..."""
        return self._coded[name]

    def dates(self, name: str) -> npt.NDArray[np.int32]:
        """A date column (``INDEX_DATES``) as days since 1970, ``NULL_DAY`` when missing."""
        return self._dates[name]

    def numbers(self, name: str) -> npt.NDArray[np.int32]:
        """A number column (``NUMBERS``), ``NULL_NUMBER`` when missing."""
        return self._numbers[name]

    def link(self, dimension: LinkDimension) -> LinkColumn:
        return self._links[dimension]

    @property
    def lead_sponsors(self) -> Ids:
        """Each trial's lead sponsor id, ``NO_SPONSOR`` for none."""
        return self._lead_sponsors

    @property
    def placebo(self) -> Mask:
        """Trials with an intervention whose name says placebo."""
        return self._placebo

    # --- building ---------------------------------------------------------------------------

    @classmethod
    def build(cls, conn: Connection, data_version: int) -> "TrialIndex":
        """Read every trial's indexed columns in ``conn``'s transaction."""
        raw = conn.connection.driver_connection
        size = int(conn.execute(select(func.coalesce(func.max(t.trials.c.id), 0))).scalar_one()) + 1
        present = np.zeros(size, np.bool_)
        columns_ = [column_ for _, column_ in CODED_COLUMNS]
        codes: list[dict[Any, int]] = [{} for _ in CODED_COLUMNS]
        coded = [np.full(size, -1, np.int16) for _ in CODED_COLUMNS]
        dates: dict[str, npt.NDArray[np.int32]] = {
            name: np.full(size, NULL_DAY, np.int32) for name in INDEX_DATES
        }
        numbers = {name: np.full(size, NULL_NUMBER, np.int32) for name in NUMBERS}
        lead_sponsors = np.full(size, NO_SPONSOR, np.int32)
        day = "coalesce(CAST(julianday({0}) - 2440587.5 AS INTEGER), {1})"
        cursor = raw.execute(  # type: ignore[union-attr]
            f"SELECT id, {', '.join(columns_)}, "
            + ", ".join(day.format(name, NULL_DAY) for name in INDEX_DATES)
            + ", "
            + ", ".join(f"coalesce({name}, {NULL_NUMBER})" for name in NUMBERS)
            + f", coalesce(lead_sponsor_id, {NO_SPONSOR})"
            + " FROM trials"
        )
        while rows := cursor.fetchmany(_CHUNK):
            columns = list(zip(*rows, strict=True))
            ids = np.fromiter(columns[0], np.int32, len(rows))
            present[ids] = True
            for i, values in enumerate(columns[1 : 1 + len(CODED_COLUMNS)]):
                mapping = codes[i]
                coded[i][ids] = [
                    -1 if value is None else mapping.setdefault(value, len(mapping))
                    for value in values
                ]
            offset = 1 + len(CODED_COLUMNS)
            for j, name in enumerate(INDEX_DATES):
                dates[name][ids] = np.fromiter(columns[offset + j], np.int32, len(rows))
            offset += len(INDEX_DATES)
            for j, name in enumerate(NUMBERS):
                numbers[name][ids] = np.fromiter(columns[offset + j], np.int32, len(rows))
            lead_sponsors[ids] = np.fromiter(columns[-1], np.int32, len(rows))
        coded_by_name = {
            name: CodedColumn(
                values,
                tuple(
                    bool(code) if name in _BOOLEANS else code
                    for code in sorted(mapping, key=mapping.__getitem__)
                ),
            )
            for (name, _), values, mapping in zip(CODED_COLUMNS, coded, codes, strict=True)
        }

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
        # Both kinds of MeSH link in one pass over the table; ancestors are left out.
        triples = _read_triples(
            raw,
            "SELECT trial_id, mesh_term_id, kind = 'condition' FROM trial_mesh WHERE NOT ancestor",
        )
        for dimension, is_condition in (("mesh_conditions", 1), ("mesh_interventions", 0)):
            rows = triples[triples[:, 2] == is_condition]
            links[dimension] = LinkColumn(
                rows[:, 0].copy(), rows[:, 1].copy(), int(rows[:, 1].max()) + 1 if len(rows) else 0
            )
        type_codes: dict[str | None, int] = {}
        triples = _read_triples(
            raw,
            "SELECT trial_id, intervention_id, type FROM trial_interventions",
            lambda type_: type_codes.setdefault(type_, len(type_codes)),
        )
        trial_arr, type_arr = triples[:, 0].copy(), triples[:, 2].copy()
        intervention_arr = triples[:, 1].copy()
        links["interventions"] = LinkColumn(
            trial_arr, intervention_arr, int(intervention_arr.max()) + 1 if len(triples) else 0
        )
        type_list = tuple(sorted(type_codes, key=type_codes.__getitem__))
        drug = type_codes.get("DRUG", -1)
        # One row per (trial, type), so a trial with two drugs counts once for DRUG.
        typed = type_arr != type_codes.get(None, -1)
        pairs = np.unique(trial_arr[typed].astype(np.int64) * 64 + type_arr[typed])
        intervention_types = LinkColumn(
            (pairs // 64).astype(np.int32), (pairs % 64).astype(np.int32), len(type_list)
        )
        # Trials with a placebo: an intervention named so ("Placebo", "Placebo oral tablet").
        placebos = [
            key
            for (key,) in raw.execute(  # type: ignore[union-attr]
                "SELECT id FROM interventions WHERE name LIKE '%placebo%'"
            )
        ]
        placebo = np.zeros(size, np.bool_)
        placebo[trial_arr[np.isin(intervention_arr, placebos)]] = True
        return cls(
            data_version,
            present,
            coded_by_name,
            dates,
            numbers,
            lead_sponsors,
            links,
            countries,
            intervention_types,
            type_arr == drug,
            type_list,
            placebo,
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

    def _linked_mask(self, link: LinkColumn, wanted: Sequence[int]) -> Mask:
        mask = np.zeros(self.size, np.bool_)
        if wanted:
            mask[link.trial[np.isin(link.value, wanted)]] = True
        return mask

    def _named(self, conn: Connection, name: str, names: Sequence[str]) -> Mask:
        link = LINKS[name]
        ids = conn.execute(select(link.entity_key).where(link.value.in_(names))).scalars().all()
        return self._linked_mask(self._links[name], ids)

    def _from_sql(self, conn: Connection, filter: TrialFilter) -> Mask:
        return self._ids_mask(conn.execute(select(t.trials.c.id).where(*where(filter))).scalars())

    def _mesh(self, conn: Connection, codes: Sequence[str]) -> Mask:
        # Straight from the link table's (mesh_term_id, kind, trial_id) index.
        return self.select_mask(
            conn,
            "SELECT trial_id FROM trial_mesh WHERE mesh_term_id IN "
            "(SELECT id FROM mesh_terms WHERE code IN (SELECT value FROM json_each(?)))",
            (orjson.dumps(list(codes)).decode(),),
        )

    def _full_text(self, conn: Connection, q: str) -> Mask:
        query = text_query(q)
        if query is None:
            return self.present
        return self.select_mask(conn, *query)

    def select_mask(
        self, conn: Connection, sql: str, params: tuple[Any, ...] | Mapping[str, Any]
    ) -> Mask:
        """A mask of the trial ids ``sql`` selects, read on the sqlite3 cursor in bulk.

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

    def ordered(self, mask: Mask, sort: Sort) -> Ids:
        """Every trial ``mask`` holds, in ``sort``'s order: the order ``page`` pages in."""
        order, _ = self._order(sort.key)
        picked = order[mask[order]]
        return picked[::-1] if sort.descending else picked

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

    def _link_counts(self, link: LinkColumn, rows: Mask | None = None) -> npt.NDArray[np.int64]:
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
        ids = [int(i) for i in chosen]
        names = self._names(dimension, ids)
        return [Count(*names[i], int(counts[i])) for i in ids]

    def _names(self, dimension: LinkDimension, ids: Sequence[int]) -> dict[int, tuple[Any, str]]:
        """The value a filter takes and the label of each entity id (not for countries)."""
        link = LINKS[dimension]
        return {
            key: (value, label)
            for key, value, label in self._conn.execute(
                select(link.entity_key, link.value, link.label).where(link.entity_key.in_(ids))
            )
        }

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

    def timelines(
        self,
        dimension: LinkDimension,
        field: DateField,
        edges: Sequence[date],
        *,
        recent: int = 1,
        at_least: int = 1,
    ) -> list[Timeline]:
        periods = len(edges) - 1
        if periods < 1:
            return []
        if dimension == "countries":
            raise ValueError("the index has no timelines of countries")
        link = self._index._links[dimension]
        bounds = np.array([day_number(edge) for edge in edges], np.int64)
        rows = self._mask[link.trial]
        trials = link.trial[rows]
        days = self._index._dates[field][trials].astype(np.int64)
        inside = (days >= bounds[0]) & (days < bounds[-1])
        trials, days = trials[inside], days[inside]
        period = np.searchsorted(bounds, days, side="right") - 1
        # Entity ids in ascending order, and each link row's place among them.
        found, entity = np.unique(link.value[rows][inside], return_inverse=True)
        cells = len(found) * periods
        by_entity = np.bincount(entity * periods + period, minlength=cells).reshape(-1, periods)
        recent_trials = by_entity[:, max(periods - recent, 0) :].sum(axis=1)
        chosen = np.flatnonzero(recent_trials >= max(at_least, 1))
        chosen = chosen[np.argsort(-recent_trials[chosen], kind="stable")]
        if len(chosen) == 0:
            return []
        # Each (entity, lead sponsor) pair counts once, in the latest period it appears in.
        sponsor = self._index._lead_sponsors[trials].astype(np.int64)
        has = sponsor != NO_SPONSOR
        pair_entity, pair_sponsor, pair_period = entity[has], sponsor[has], period[has]
        order = np.lexsort((pair_period, pair_sponsor, pair_entity))
        pair_entity, pair_sponsor = pair_entity[order], pair_sponsor[order]
        pair_period = pair_period[order]
        last = np.ones(len(order), np.bool_)
        last[:-1] = (pair_entity[1:] != pair_entity[:-1]) | (pair_sponsor[1:] != pair_sponsor[:-1])
        latest = np.bincount(
            pair_entity[last] * periods + pair_period[last], minlength=cells
        ).reshape(-1, periods)
        names = self._names(dimension, [int(found[i]) for i in chosen])
        return [
            Timeline(
                *names[int(found[i])],
                tuple(int(n) for n in by_entity[i]),
                tuple(int(n) for n in latest[i]),
            )
            for i in chosen
        ]

    def first_dates(
        self, dimension: LinkDimension, field: DateField, values: Sequence[str]
    ) -> dict[str, date]:
        if not values:
            return {}
        if dimension == "countries":
            raise ValueError("the index has no first dates of countries")
        link = LINKS[dimension]
        ids = dict(
            self._conn.execute(
                select(link.entity_key, link.value).where(link.value.in_(values))
            ).all()
        )
        linked = self._index._links[dimension]
        rows = self._mask[linked.trial] & np.isin(linked.value, list(ids))
        days = self._index._dates[field][linked.trial[rows]]
        entities = linked.value[rows]
        dated = days != NULL_DAY
        first = np.full(linked.size, np.iinfo(np.int32).max, np.int32)
        np.minimum.at(first, entities[dated], days[dated])
        return {
            ids[key]: from_day_number(int(first[key]))
            for key in ids
            if first[key] != np.iinfo(np.int32).max
        }


def _read_triples(
    raw: Any, sql: str, convert: Callable[[Any], int] | None = None
) -> npt.NDArray[np.int32]:
    """Rows of three integers, the third converted by ``convert``, as an (n, 3) array."""
    cursor = raw.execute(sql)
    chunks: list[npt.NDArray[np.int32]] = []
    while rows := cursor.fetchmany(_CHUNK):
        flat = itertools.chain.from_iterable(
            rows if convert is None else ((a, b, convert(c)) for a, b, c in rows)
        )
        chunks.append(np.fromiter(flat, np.int32, 3 * len(rows)).reshape(-1, 3))
    return np.concatenate(chunks) if chunks else np.zeros((0, 3), np.int32)


def _read_pairs(raw: Any, sql: str, convert: Callable[[Any], int] | None = None) -> LinkColumn:
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
    return LinkColumn(trial, value, int(value.max()) + 1 if len(value) else 0)
