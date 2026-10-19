import math
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tri_al.filters import DateRange, TrialFilter
from tri_al.plugins import Registry
from tri_al.plugins.registry import Contributions
from tri_al.schema import MeshTerm, Sponsor, TrialRecord
from tri_al.stats import ChartContext, Rows, SqlCounts, TrialIndex
from tri_al.storage import SQLiteReader, SQLiteStorage
from tri_al_insights import SECTION, Settings, charts, plugin
from tri_al_insights.trends import (
    Options,
    confidence,
    false_discovery,
    growths,
    months_before,
    rise_p,
)

LATEST = date(2026, 10, 16)
HEMOPHILIA = MeshTerm("D002836", "Hemophilia B", "condition")
SUNBURN = MeshTerm("D013471", "Sunburn", "condition")
NOVEL = MeshTerm("C000000001", "Novel Syndrome", "condition")
OLD = MeshTerm("D000001", "Old Disease", "condition")
OTHER = MeshTerm("D009369", "Neoplasms", "condition")
DRUG = MeshTerm("C000000002", "drugzumab", "intervention")

_ids = iter(range(10_000_000))


def trial(
    posted: date,
    terms: list[MeshTerm],
    sponsor: str = "Uni",
    country: str = "US",
    status: str = "RECRUITING",
) -> TrialRecord:
    return TrialRecord(
        source="ctgov",
        source_id=f"NCT{next(_ids):08d}",
        title="A trial",
        status=status,
        first_posted=posted,
        mesh_terms=terms,
        sponsors=[Sponsor(sponsor, "lead", "OTHER")],
        countries=[country],
    )


def dataset() -> list[TrialRecord]:
    trials = [
        # Ten trials a month of something else for two years, from many sponsors.
        trial(LATEST - timedelta(days=3 * i), [OTHER], f"Sponsor {i % 7}", status="COMPLETED")
        for i in range(240)
    ]
    # Rising: one trial in the baseline, then six in the last three months.
    trials.append(trial(date(2025, 10, 1), [HEMOPHILIA], "A"))
    trials += [
        trial(date(2026, 8, 1) + timedelta(days=9 * i), [HEMOPHILIA, DRUG], "ABC"[i % 3])
        for i in range(6)
    ]
    # One sponsor's series: not a trend.
    trials += [trial(date(2026, 9, 1) + timedelta(days=i), [SUNBURN], "Solo") for i in range(5)]
    # First seen in the last two months.
    trials += [trial(date(2026, 8, 20) + timedelta(days=i), [NOVEL], f"N{i}") for i in range(3)]
    # Back after years away: not new.
    trials += [trial(date(2018, 3, 1), [OLD], "Old")]
    trials += [
        trial(date(2026, 9, 10) + timedelta(days=i), [OLD], f"O{i}", country="DE") for i in range(4)
    ]
    return trials


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SQLiteStorage]:
    path = tmp_path_factory.mktemp("insights") / "trials.db"
    with SQLiteStorage.open(path) as storage:
        storage.upsert_batch(dataset())
        yield storage


def run(reader: SQLiteReader, filter: TrialFilter, *, index: bool, **settings: Any) -> Rows:
    chart = next(chart for chart in charts(Settings(**settings)) if chart.id == "emerging_trends")
    conn = reader.connection
    if index:
        built = TrialIndex.build(conn, reader.data_version())
        ctx = ChartContext(conn, lambda f: built.counts(conn, built.mask(conn, f)))
    else:
        ctx = ChartContext(conn, lambda f: SqlCounts(conn, f))
    return chart.query(ctx, filter)


def items(rows: Rows, window: str, group: str = "Conditions") -> dict[str, dict[str, Any]]:
    return {
        row["label"]: row
        for row in rows
        if row["type"] == "item" and row["window"] == window and row["group"] == group
    }


def windows(rows: Rows) -> dict[str, dict[str, Any]]:
    return {row["window"]: row for row in rows if row["type"] == "window"}


def test_registers_the_chart_in_its_section() -> None:
    contributions = Contributions()

    plugin.register(Registry("insights", Settings(), contributions))

    assert list(contributions.charts) == [
        "emerging_trends",
        "research_clusters",
        "research_landscape_3d",
    ]
    chart = contributions.charts["emerging_trends"]
    assert (chart.id, chart.widget, chart.section, chart.plugin) == (
        "emerging_trends",
        "trends",
        SECTION,
        "insights",
    )
    assert chart.precompute
    assert chart.layout.width == 4
    clusters = contributions.charts["research_clusters"]
    assert (clusters.widget, clusters.section, clusters.layout.width) == ("scatter", SECTION, 4)
    assert clusters.page == "dashboard"
    solid = contributions.charts["research_landscape_3d"]
    assert (solid.widget, solid.page, solid.precompute) == ("scatter3d", "analysis", True)


def test_settings() -> None:
    assert Settings(windows=[6, 3, 6]).windows == [3, 6]
    with pytest.raises(ValidationError):
        Settings(windows=[0])
    with pytest.raises(ValidationError):
        Settings(windows=[])
    with pytest.raises(ValidationError):
        Settings.model_validate({"top": 3, "extra": 1})


@pytest.mark.parametrize(
    ("day", "months", "expected"),
    [
        (date(2026, 10, 17), 3, date(2026, 7, 17)),
        (date(2026, 10, 17), 10, date(2025, 12, 17)),
        (date(2026, 3, 31), 1, date(2026, 2, 28)),
        (date(2024, 3, 31), 1, date(2024, 2, 29)),
        (date(2026, 1, 15), 13, date(2024, 12, 15)),
    ],
)
def test_months_before(day: date, months: int, expected: date) -> None:
    assert months_before(day, months) == expected


# On the whole registry, a 6-month window against the year before:
TOTALS = (26_479, 46_445)


def test_a_few_trials_dont_make_dramatic_growth() -> None:
    adjusted, raw = growths(9, 1, *TOTALS)
    assert raw == pytest.approx(15.79, abs=0.01)
    assert adjusted == pytest.approx(3.0, abs=0.05)
    # Many trials keep their growth.
    adjusted, raw = growths(451, 573, *TOTALS)
    assert raw is not None
    assert adjusted == pytest.approx(raw, rel=0.02)
    # None before is still a finite growth, and more trials make it larger.
    few, none_before = growths(3, 0, *TOTALS)
    assert none_before is None
    assert 1 < few < 2 < growths(16, 0, *TOTALS)[0] < 6
    # No change stays at 1.
    assert growths(26, 46, *TOTALS)[0] == pytest.approx(1, abs=0.02)


def test_rise_p_is_the_binomial_upper_tail() -> None:
    assert rise_p(3, 3, 0.5) == pytest.approx(0.125)
    assert rise_p(2, 3, 0.5) == pytest.approx(0.5)
    assert rise_p(1, 3, 0.5) == 1  # no more than usual
    assert rise_p(0, 0, 0.36) == 1

    def exact(r: int, n: int, u: float) -> float:
        return sum(math.comb(n, k) * u**k * (1 - u) ** (n - k) for k in range(r, n + 1))

    for r, n in ((45, 70), (9, 10), (11, 14), (40, 100)):
        assert rise_p(r, n, 0.363) == pytest.approx(exact(r, n, 0.363), rel=1e-9)
    # Large counts stay in range.
    assert 0 < rise_p(626, 1522, 0.363) < 1e-3


def test_false_discovery() -> None:
    assert false_discovery([]) == []
    assert false_discovery([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.02, 0.04, 0.04, 0.02])
    assert false_discovery([0.5]) == [0.5]
    assert false_discovery([0.2, 0.9]) == pytest.approx([0.4, 0.9])


def test_confidence() -> None:
    assert [confidence(q) for q in (0.001, 0.049, 0.05, 0.2, 0.25, 0.9)] == [
        "high",
        "high",
        "medium",
        "medium",
        "low",
        "low",
    ]


@pytest.mark.parametrize("index", [False, True], ids=["sql", "index"])
def test_emerging_trends(storage: SQLiteStorage, index: bool) -> None:
    with storage.read() as reader:
        rows = run(reader, TrialFilter(), index=index)

    by_window = windows(rows)
    assert by_window["3m"] == {
        "type": "window",
        "window": "3m",
        "label": "3 months",
        "since": "2026-07-17",
        "until": "2026-10-16",
        "baseline_since": "2025-07-17",
        "trials": by_window["3m"]["trials"],
        "baseline_trials": by_window["3m"]["baseline_trials"],
    }
    assert by_window["6m"]["since"] == "2026-04-17"
    assert by_window["6m"]["baseline_since"] == "2025-04-17"

    recent = items(rows, "3m")
    assert "Sunburn" not in recent  # one sponsor
    assert "Neoplasms" not in recent  # steady
    hemophilia = recent["Hemophilia B"]
    total, baseline_total = by_window["3m"]["trials"], by_window["3m"]["baseline_trials"]
    assert hemophilia["value"] == 6
    assert hemophilia["baseline"] == 1
    assert hemophilia["sponsors"] == 3
    assert hemophilia["raw_growth"] == round((6 / total) / (1 / baseline_total), 2)
    assert hemophilia["growth"] == round(growths(6, 1, total, baseline_total)[0], 2)
    assert hemophilia["growth"] < hemophilia["raw_growth"]
    assert hemophilia["confidence"] == "high"
    assert hemophilia["q"] < 0.05
    assert hemophilia["p"] <= hemophilia["q"]
    assert hemophilia["tested"] == 4  # with Novel Syndrome, Old Disease and the steady Neoplasms
    assert not hemophilia["new"]
    assert hemophilia["filter"] == {"mesh": ["D002836"], "first_posted": "2026-07-17.."}
    assert len(hemophilia["series"]) == 15
    assert sum(hemophilia["series"][-3:]) == 6
    assert hemophilia["recent"] == 3

    assert recent["Novel Syndrome"]["new"]
    assert recent["Novel Syndrome"]["raw_growth"] is None
    assert recent["Novel Syndrome"]["growth"] > 1
    assert not recent["Old Disease"]["new"]
    assert items(rows, "6m")["Novel Syndrome"]["new"]

    assert items(rows, "3m", "Interventions")["drugzumab"]["value"] == 6
    # By confidence, then growth.
    order = {"high": 0, "medium": 1, "low": 2}
    keys = [(order[row["confidence"]], -row["growth"]) for row in recent.values()]
    assert keys == sorted(keys)


@pytest.mark.parametrize("index", [False, True], ids=["sql", "index"])
def test_follows_the_filter(storage: SQLiteStorage, index: bool) -> None:
    with storage.read() as reader:
        us = run(reader, TrialFilter(countries=("US",)), index=index)
        completed = run(reader, TrialFilter(status=("COMPLETED",)), index=index)
        recent_only = run(
            reader, TrialFilter(first_posted=DateRange.parse("2026-08..")), index=index
        )

    assert set(items(us, "3m")) == {"Hemophilia B", "Novel Syndrome"}
    assert [row for row in completed if row["type"] == "item"] == []  # nothing but the usual
    # Without trials before the window there is nothing to compare with.
    assert windows(recent_only)["3m"]["baseline_trials"] == 0
    assert [row for row in recent_only if row["type"] == "item"] == []


@pytest.mark.parametrize(
    ("filter", "settings"),
    [
        (TrialFilter(), {}),
        (TrialFilter(status=("RECRUITING",)), {"windows": [2, 4], "baseline_months": 6}),
        (TrialFilter(countries=("US",)), {"min_sponsors": 1, "top": 2}),
    ],
)
def test_the_index_and_sqlite_agree(
    storage: SQLiteStorage, filter: TrialFilter, settings: dict[str, Any]
) -> None:
    with storage.read() as reader:
        assert run(reader, filter, index=True, **settings) == run(
            reader, filter, index=False, **settings
        )


def test_no_trials(tmp_path: Path) -> None:
    with SQLiteStorage.open(tmp_path / "trials.db") as storage, storage.read() as reader:
        assert run(reader, TrialFilter(), index=False) == []
        assert run(reader, TrialFilter(), index=True) == []


def test_options_match_the_settings() -> None:
    assert Settings().options() == Options()
