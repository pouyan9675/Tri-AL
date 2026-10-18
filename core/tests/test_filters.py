from datetime import date

import pytest
from sqlalchemy import true

from tri_al.filters import EVERY_TRIAL, DateRange, FilterField, IntRange, TrialFilter, parse_date


@pytest.mark.parametrize(
    ("text", "end", "expected"),
    [
        ("2024", False, date(2024, 1, 1)),
        ("2024", True, date(2024, 12, 31)),
        ("2024-02", True, date(2024, 2, 29)),
        ("2023-02", True, date(2023, 2, 28)),
        ("2024-06-15", True, date(2024, 6, 15)),
    ],
)
def test_partial_dates(text: str, end: bool, expected: date) -> None:
    assert parse_date(text, end=end) == expected


@pytest.mark.parametrize("text", ["24", "2024-1", "June", "2024-13-01", ""])
def test_bad_dates(text: str) -> None:
    with pytest.raises(ValueError, match=r"date|month"):
        parse_date(text)


def test_date_ranges() -> None:
    assert DateRange.parse("2020..2023") == DateRange(date(2020, 1, 1), date(2023, 12, 31))
    assert DateRange.parse("2024-06..") == DateRange(date(2024, 6, 1), None)
    assert DateRange.parse("..2019-03") == DateRange(None, date(2019, 3, 31))
    assert DateRange.parse("2021") == DateRange(date(2021, 1, 1), date(2021, 12, 31))
    assert str(DateRange.parse("2020..")) == "2020-01-01.."
    with pytest.raises(ValueError, match="starts after it ends"):
        DateRange.parse("2024..2020")


def test_int_ranges() -> None:
    assert IntRange.parse("100..500") == IntRange(100, 500)
    assert IntRange.parse("1000..") == IntRange(1000, None)
    assert IntRange.parse("..50") == IntRange(None, 50)
    assert IntRange.parse("7") == IntRange(7, 7)
    assert str(IntRange(None, 50)) == "..50"
    with pytest.raises(ValueError, match="starts after it ends"):
        IntRange.parse("9..1")


def test_filters_that_mean_the_same_are_equal() -> None:
    one = TrialFilter(status=("RECRUITING", "COMPLETED", "RECRUITING"), countries=("us", "de"))
    other = TrialFilter(status=("COMPLETED", "RECRUITING"), countries=("DE", "US"), q="  ")

    assert one == other
    assert hash(one) == hash(other)
    assert one.countries == ("DE", "US")
    assert other.q is None


def test_active_fields_and_without() -> None:
    field = FilterField(name="x_score", title="Score", clause=lambda values: true())
    filter = TrialFilter(phase=("PHASE3",), has_results=False, q="tau", extra=((field, ("1",)),))

    assert filter.active == ("phase", "has_results", "q", "x_score")
    assert filter.without("phase").active == ("has_results", "q", "x_score")
    assert filter.without("x_score").active == ("phase", "has_results", "q")
    assert filter.without("status") == filter
    assert filter.without("nothing") == filter
    assert EVERY_TRIAL.is_empty
    assert not filter.is_empty


def test_to_params() -> None:
    filter = TrialFilter(
        status=("RECRUITING",),
        conditions=("Alzheimer Disease", "Dementia"),
        start=DateRange.parse("2020.."),
        enrollment=IntRange(None, 50),
        has_results=True,
        q="amyloid",
    )

    assert filter.to_params() == [
        ("status", "RECRUITING"),
        ("conditions", "Alzheimer Disease"),
        ("conditions", "Dementia"),
        ("start", "2020-01-01.."),
        ("enrollment", "..50"),
        ("has_results", "true"),
        ("q", "amyloid"),
    ]


def test_a_plugin_field_once() -> None:
    field = FilterField(name="x_score", title="Score", clause=lambda values: true())

    with pytest.raises(ValueError, match="given twice"):
        TrialFilter(extra=((field, ("1",)), (field, ("2",))))
    assert TrialFilter(extra=((field, ("", " ")),)).is_empty
