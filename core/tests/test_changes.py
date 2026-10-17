from dataclasses import replace
from datetime import date

import pytest

from tri_al.pipeline.changes import TRACKED_FIELDS, changes, tracked
from tri_al.schema import Intervention, Sponsor, age_in_days
from tri_al.testing.fixtures import phase3_trial


def test_tracked_values_are_json_ready() -> None:
    values = tracked(phase3_trial())

    assert list(values) == list(TRACKED_FIELDS)
    assert values["start_date"] == "2024-03-01"
    assert values["lead_sponsor"] == phase3_trial().lead_sponsor.name  # type: ignore[union-attr]
    assert values["interventions"] == [i.name for i in phase3_trial().interventions]
    assert values["num_sites"] == len(phase3_trial().locations)


def test_changes_lists_what_differs_as_json() -> None:
    old = phase3_trial()
    new = replace(
        old,
        status="COMPLETED",
        completion_date=date(2028, 3, 1),
        enrollment=None,
        last_update=date(2027, 1, 1),  # not tracked
        sponsors=[Sponsor("Someone Else", "lead", "OTHER"), *old.sponsors],
    )

    assert changes(old, new) == [
        ("status", '"RECRUITING"', '"COMPLETED"'),
        ("completion_date", '"2028-01-15"', '"2028-03-01"'),
        ("enrollment", "1800", None),
        ("lead_sponsor", f'"{old.sponsors[0].name}"', '"Someone Else"'),
    ]


def test_repeats_storage_drops_are_not_changes() -> None:
    old = phase3_trial()
    new = replace(
        old,
        conditions=[*old.conditions, old.conditions[0]],
        interventions=[*old.interventions, Intervention(old.interventions[0].name, "OTHER")],
    )

    assert changes(old, new) == []


@pytest.mark.parametrize(
    ("amount", "unit", "days"),
    [
        (18, "Years", 6574),
        (1, "year", 365),
        (12, "Months", 365),
        (6, "MONTHS", 182),
        (36, "Weeks", 252),
        (42, "Days", 42),
        (36, "Hours", 1),
        (5, "Minutes", 0),
    ],
)
def test_age_in_days(amount: int, unit: str, days: int) -> None:
    assert age_in_days(amount, unit) == days


def test_age_in_days_rejects_unknown_units() -> None:
    with pytest.raises(ValueError, match="unknown age unit 'fortnights'"):
        age_in_days(2, "fortnights")
