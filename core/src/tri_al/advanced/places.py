"""Trial sites by place, for "within 50 km of Toronto", with no geocoding service.

ClinicalTrials.gov gives each site the coordinates of its city, so the registry is its own
gazetteer: 3.45 million sites with coordinates fall on about 36,000 places. ``Sites`` keeps
each site's trial and place in memory (about 21 MB), built once per data version in each API
worker on first use (about 2 s); a place's name is the commonest of a few of its sites'
spellings. Distances are great-circle, from a place's coordinates.
"""

import json
import math
import threading
from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from sqlalchemy import Connection

from tri_al.advanced.query import Near
from tri_al.storage.countries import COUNTRIES, EXTRA_COUNTRIES

EARTH_KM = 6371.0088
"""The Earth's mean radius."""

NAME_SAMPLES = 5
"""Sites per place whose spelling of its name is read; the commonest wins."""

_CHUNK = 65_536
_SCALE = 10_000  # coordinates are compared to 4 decimals (about 10 m)

type Ids = npt.NDArray[np.int32]

COUNTRY_NAMES: dict[str, tuple[str, str]] = {
    code: (alpha3, name) for code, alpha3, name in (*COUNTRIES, *EXTRA_COUNTRIES)
}
"""Each country code's alpha-3 code and name."""


@dataclass(frozen=True, slots=True)
class Place:
    city: str | None
    state: str | None
    country: str | None  # ISO 3166-1 alpha-2
    lat: float
    lon: float
    sites: int


@dataclass(frozen=True, slots=True)
class Within:
    """The trials with a site in range: ids ascending, the nearest site's distance, and how
    many sites are in range."""

    trials: Ids
    km: npt.NDArray[np.float32]
    sites: npt.NDArray[np.int32]


@dataclass(frozen=True, slots=True)
class NearestSite:
    km: float
    facility: str | None
    city: str | None
    state: str | None
    country: str | None
    sites: int  # the trial's sites in range


class Sites:
    """Every site with coordinates, as (trial, place), and the places, for one data version."""

    def __init__(
        self,
        data_version: int,
        trial: Ids,
        place: npt.NDArray[np.integer[Any]],
        places: list[Place],
    ) -> None:
        self.data_version = data_version
        self.places = places
        self._trial = trial  # ascending
        self._place = place
        self._lat = np.radians([p.lat for p in places])
        self._lon = np.radians([p.lon for p in places])
        self._keys = [_folded(p.city) for p in places]

    @property
    def nbytes(self) -> int:
        return self._trial.nbytes + self._place.nbytes + self._lat.nbytes + self._lon.nbytes

    @classmethod
    def build(cls, conn: Connection, data_version: int) -> "Sites":
        raw = conn.connection.driver_connection
        cursor = raw.execute(  # type: ignore[union-attr]
            "SELECT trial_id, position, lat, lon FROM locations "
            "WHERE lat IS NOT NULL AND lon IS NOT NULL"
        )
        chunks: list[tuple[Any, ...]] = []
        while rows := cursor.fetchmany(_CHUNK):
            columns = list(zip(*rows, strict=True))
            chunks.append(
                (
                    np.fromiter(columns[0], np.int32, len(rows)),
                    np.fromiter(columns[1], np.int32, len(rows)),
                    np.fromiter(columns[2], np.float64, len(rows)),
                    np.fromiter(columns[3], np.float64, len(rows)),
                )
            )
        if not chunks:
            return cls(data_version, np.empty(0, np.int32), np.empty(0, np.int32), [])
        trial, position, lat, lon = (np.concatenate(parts) for parts in zip(*chunks, strict=True))
        lat_q = np.round(lat * _SCALE).astype(np.int64) + 90 * _SCALE
        lon_q = np.round(lon * _SCALE).astype(np.int64) + 180 * _SCALE
        _, first, place, counts = np.unique(
            lat_q * (360 * _SCALE + 1) + lon_q,
            return_index=True,
            return_inverse=True,
            return_counts=True,
        )
        names = _names(raw, trial, position, place, counts)
        places = [
            Place(*names[i], float(lat[first[i]]), float(lon[first[i]]), int(counts[i]))
            for i in range(len(first))
        ]
        kind = np.uint16 if len(places) <= np.iinfo(np.uint16).max else np.int32
        order = np.argsort(trial, kind="stable")  # already in key order; this keeps it so
        return cls(data_version, trial[order], place[order].astype(kind), places)

    # --- places -----------------------------------------------------------------------------

    def find(self, text: str, limit: int = 10) -> list[Place]:
        """Places whose city starts with ``text``, then those with a word starting with it,
        each most sites first (so "toro" is Toronto before Toro). After a comma, the rest
        narrows by state or country (code or name)."""
        city, _, rest = text.partition(",")
        wanted, region = _folded(city), _folded(rest)
        if not wanted:
            return []
        scored: list[tuple[int, int, int]] = []
        for i, key in enumerate(self._keys):
            if key.startswith(wanted):
                rank = 0
            elif f" {wanted}" in f" {key.replace('-', ' ')}":
                rank = 1
            else:
                continue
            place = self.places[i]
            names = (place.state, place.country, *COUNTRY_NAMES.get(place.country or "", ()))
            if region and not any(_folded(value).startswith(region) for value in names):
                continue
            scored.append((rank, -place.sites, i))
        scored.sort()
        return [self.places[i] for _, _, i in scored[:limit]]

    # --- distances --------------------------------------------------------------------------

    def place_km(self, lat: float, lon: float) -> npt.NDArray[np.float64]:
        """Every place's distance from a point."""
        return haversine(np.radians(lat), np.radians(lon), self._lat, self._lon)

    def within(self, near: Near) -> Within:
        """The trials with a site within ``near.km`` of the point."""
        km = self.place_km(near.lat, near.lon)
        close = km <= near.km
        sites = np.flatnonzero(close[self._place])
        if len(sites) == 0:
            empty = np.empty(0, np.int32)
            return Within(empty, np.empty(0, np.float32), empty)
        trials = self._trial[sites]
        distances = km[self._place[sites]].astype(np.float32)
        starts = np.flatnonzero(np.r_[True, trials[1:] != trials[:-1]])
        counts = np.diff(np.r_[starts, len(trials)]).astype(np.int32)
        return Within(trials[starts], np.minimum.reduceat(distances, starts), counts)


def haversine(
    lat: float, lon: float, lats: npt.NDArray[np.float64], lons: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """Great-circle distances in km from one point to many, all in radians."""
    a = np.sin((lats - lat) / 2) ** 2 + math.cos(lat) * np.cos(lats) * np.sin((lons - lon) / 2) ** 2
    distances: npt.NDArray[np.float64] = 2 * EARTH_KM * np.arcsin(np.sqrt(np.minimum(a, 1.0)))
    return distances


def nearest_sites(conn: Connection, near: Near, trial_ids: list[int]) -> dict[int, NearestSite]:
    """Each trial's site nearest the point, if one is in range, with its name."""
    if not trial_ids:
        return {}
    rows = conn.exec_driver_sql(
        "SELECT trial_id, facility, city, state, country_code, lat, lon FROM locations "
        "WHERE trial_id IN (SELECT value FROM json_each(?)) AND lat IS NOT NULL "
        "AND lon IS NOT NULL",
        (json.dumps(trial_ids),),
    ).all()
    if not rows:
        return {}
    km = haversine(
        math.radians(near.lat),
        math.radians(near.lon),
        np.radians([row[5] for row in rows]),
        np.radians([row[6] for row in rows]),
    )
    found: dict[int, NearestSite] = {}
    for row, distance in zip(rows, km.tolist(), strict=True):
        if distance > near.km:
            continue
        trial_id = row[0]
        best = found.get(trial_id)
        count = 1 if best is None else best.sites + 1
        if best is None or distance < best.km:
            found[trial_id] = NearestSite(distance, row[1], row[2], row[3], row[4], count)
        else:
            found[trial_id] = NearestSite(
                best.km, best.facility, best.city, best.state, best.country, count
            )
    return found


class SiteCache:
    """One worker's ``Sites``, built on first use for each data version."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sites: Sites | None = None

    def get(self, conn: Connection, data_version: int) -> Sites:
        with self._lock:
            if self._sites is None or self._sites.data_version != data_version:
                self._sites = Sites.build(conn, data_version)
            return self._sites


def _names(
    raw: Any,
    trial: Ids,
    position: Ids,
    place: npt.NDArray[np.int64],
    counts: npt.NDArray[np.int64],
) -> list[tuple[str | None, str | None, str | None]]:
    """Each place's name (city, state, country): the commonest of a few of its sites'."""
    order = np.argsort(place, kind="stable")
    starts = np.r_[0, np.cumsum(counts)[:-1]]
    samples: list[tuple[int, int, int]] = []
    for j in range(NAME_SAMPLES):
        has = counts > j
        picks = order[starts[has] + (j * counts[has]) // np.minimum(counts[has], NAME_SAMPLES)]
        samples += zip(
            np.flatnonzero(has).tolist(),
            trial[picks].tolist(),
            position[picks].tolist(),
            strict=True,
        )
    spellings: list[Counter[tuple[str | None, str | None]]] = [Counter() for _ in counts]
    states: list[Counter[str | None]] = [Counter() for _ in counts]
    for chunk in range(0, len(samples), _CHUNK):
        part = samples[chunk : chunk + _CHUNK]
        rows = raw.execute(
            "SELECT j.key, l.city, l.state, l.country_code FROM json_each(?) AS j "
            "JOIN locations AS l ON l.trial_id = j.value ->> 1 AND l.position = j.value ->> 2",
            (json.dumps(part),),
        )
        for key, city, state, country in rows:
            i = part[key][0]
            spellings[i][(city, country)] += 1
            states[i][state] += 1
    names: list[tuple[str | None, str | None, str | None]] = []
    for spelling, state in zip(spellings, states, strict=True):
        (city, country), _ = spelling.most_common(1)[0] if spelling else ((None, None), 0)
        names.append((city, next((s for s, _ in state.most_common() if s), None), country))
    return names


def _folded(text: str | None) -> str:
    return " ".join((text or "").casefold().split())
