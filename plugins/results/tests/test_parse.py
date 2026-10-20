from pathlib import Path
from typing import Any

import orjson
import pytest

from tri_al_results.parse import (
    EventSum,
    analyses,
    dropout_kind,
    estimate_key,
    ethnicity_key,
    hypothesis_key,
    organ_key,
    p_value,
    parse,
    race_key,
    summary,
    term_key,
)

FIXTURES = Path(__file__).parent / "fixtures"


def study(source_id: str) -> Any:
    return orjson.loads((FIXTURES / f"{source_id}.json").read_bytes())


def test_a_study_without_results_has_none() -> None:
    assert parse({"protocolSection": {}}) is None
    assert parse({"resultsSection": {}}) is None


def test_a_placebo_controlled_trial() -> None:
    """NCT04102579: valbenazine against placebo, with the standard race categories."""
    results = parse(study("NCT04102579"))
    assert results is not None

    flow = results.flow
    assert flow is not None
    assert [group.title for group in flow.groups] == ["Valbenazine", "Placebo"]
    assert (flow.total("STARTED"), flow.total("COMPLETED", last=True)) == (128, 111)

    baseline = results.baseline
    assert baseline is not None
    assert baseline.total == "BG002"  # "Total"
    assert baseline.participants == {"BG000": 64, "BG001": 63, "BG002": 127}

    ae = results.adverse_events
    assert ae is not None
    assert [(g.title, g.placebo, g.total) for g in ae.groups] == [
        ("Valbenazine", False, False),
        ("Placebo", True, False),
    ]
    assert ae.threshold == 5.0
    assert sum(event.serious for event in ae.events) == 3
    assert ae.events[0].counts["EG001"].affected == 1

    primary = results.outcomes[0]
    assert primary.type == "PRIMARY"
    analysis = primary.analyses[0]
    assert (analysis.method, analysis.p_value, analysis.estimate) == ("MMRM", "<0.0001", "-3.16")
    assert (analysis.ci_lower, analysis.ci_upper) == ("-4.37", "-1.95")

    assert results.agreement is not None
    assert (results.agreement.restrictive, results.agreement.restriction) == (True, "OTHER")
    assert "pointOfContact" not in orjson.dumps(results).decode()


def test_its_summary() -> None:
    results = parse(study("NCT04102579"), outcomes=False)
    assert results is not None
    assert results.outcomes == ()
    s = summary(results)

    assert (s.participants, s.race, s.ethnicity) == (127, "standard", "standard")
    assert s.races == {"white": 122, "black": 1, "asian": 1, "unknown": 3}
    assert s.ethnicities == {"hispanic": 8, "not_hispanic": 119}
    assert (s.female, s.male, s.age) == (69, 58, 53.8)
    assert (s.started, s.completed) == (128, 111)
    assert s.dropouts == {"withdrawal": 7, "lost": 1, "other": 9}
    assert (s.ae_groups, s.placebo_groups) == (2, 1)
    assert (s.at_risk, s.serious, s.deaths_at_risk, s.deaths) == (127, 3, 127, 1)
    assert s.events[0] == EventSum("Psychotic disorder", True, "psychiatric", 0, 64, 1, 63)


def test_custom_categories_and_none_collected() -> None:
    custom = summary(parse(study("NCT01868165")))  # type: ignore[arg-type]
    assert (custom.race, custom.ethnicity, custom.races) == ("custom", "custom", {})
    assert custom.dropouts == {"withdrawal": 36, "physician": 2, "lost": 3, "death": 4}

    none = summary(parse(study("NCT03100617")))  # type: ignore[arg-type]
    assert (none.race, none.ethnicity) == ("not_collected", "not_collected")
    assert (none.participants, none.female, none.male) == (6, 5, 1)


def test_an_arm_called_total_is_still_an_arm() -> None:
    """NCT01993836's arms include "Total Intravenous Anesthesia With Propofol"."""
    s = summary(parse(study("NCT01993836")))  # type: ignore[arg-type]
    assert (s.race, s.ethnicity) == ("standard", "none")
    assert (s.ae_groups, s.at_risk) == (3, 72 + 68 + 51)


def groups_study(*titles: str, at_risk: tuple[int, ...], arms: tuple[Any, ...] = ()) -> Any:
    return {
        "protocolSection": {"armsInterventionsModule": {"armGroups": list(arms)}},
        "resultsSection": {
            "adverseEventsModule": {
                "eventGroups": [
                    {
                        "id": f"EG{i:03d}",
                        "title": title,
                        "seriousNumAtRisk": n,
                        "seriousNumAffected": "1",
                    }
                    for i, (title, n) in enumerate(zip(titles, at_risk, strict=True))
                ],
                "seriousEvents": [
                    {
                        "term": "Fall",
                        "organSystem": "INJURY, POISONING AND PROCEDURAL COMPLICATIONS",
                        "stats": [
                            {"groupId": f"EG{i:03d}", "numAffected": "1", "numAtRisk": str(n)}
                            for i, n in enumerate(at_risk)
                        ],
                    }
                ],
            }
        },
    }


def test_groups_of_everyone_are_left_out() -> None:
    by_title = parse(groups_study("Drug", "Placebo", "Total", at_risk=(10, 8, 18)))
    by_sum = parse(groups_study("Low dose", "High dose", "Everyone", at_risk=(10, 8, 18)))

    for results in (by_title, by_sum):
        assert results is not None
        assert results.adverse_events is not None
        assert [g.total for g in results.adverse_events.groups] == [False, False, True]
    s = summary(by_title)  # type: ignore[arg-type]
    assert (s.ae_groups, s.placebo_groups, s.at_risk, s.serious) == (2, 1, 18, 2)
    assert s.events == (EventSum("Fall", True, "injury", 1, 10, 1, 8),)


@pytest.mark.parametrize(
    ("title", "arms", "placebo"),
    [
        ("Placebo", (), True),
        ("Matching Placebo", (), True),
        ("Sham Stimulation", (), True),
        ("Placebo Then Drug X", (), False),
        ("Placebo to Drug X (Extension)", (), False),
        ("Drug X + Placebo", (), False),
        (
            "Cohort A: Control",
            ({"label": "Cohort A: Control", "type": "PLACEBO_COMPARATOR"},),
            True,
        ),
    ],
)
def test_placebo_groups(title: str, arms: tuple[Any, ...], placebo: bool) -> None:
    results = parse(groups_study("Drug X", title, at_risk=(10, 10), arms=arms))
    assert results is not None
    assert results.adverse_events is not None
    assert results.adverse_events.groups[1].placebo is placebo


def test_without_both_kinds_of_arm_nothing_is_compared() -> None:
    s = summary(parse(groups_study("Placebo", at_risk=(5,))))  # type: ignore[arg-type]
    assert s.placebo_groups == 0
    assert s.events == (EventSum("Fall", True, "injury", 1, 5),)


@pytest.mark.parametrize(
    ("title", "key"),
    [
        ("White", "white"),
        ("Caucasian", "white"),
        ("Black or African American", "black"),
        ("Black", "black"),
        ("American Indian or Alaska Native", "aian"),
        ("Native Hawaiian or Other Pacific Islander", "nhpi"),
        ("Hawaiian", "nhpi"),
        ("More than one race", "multiple"),
        ("Unknown or Not Reported", "unknown"),
        ("Other: Indian Ocean Islander", "other"),
        ("", None),
    ],
)
def test_race_categories(title: str, key: str | None) -> None:
    assert race_key(title) == key


def test_ethnicity_categories() -> None:
    assert ethnicity_key("Hispanic or Latino") == "hispanic"
    assert ethnicity_key("Not Hispanic or Latino") == "not_hispanic"
    assert ethnicity_key("Non-Hispanic") == "not_hispanic"
    assert ethnicity_key("Unknown or Not Reported") == "unknown"


def test_names_fold_together() -> None:
    assert dropout_kind("Withdrawal by Subject") == "withdrawal"
    assert dropout_kind("Adverse Event") == "adverse_event"
    assert dropout_kind("Lack of Efficacy") == "lack_of_efficacy"
    assert dropout_kind("Surgery Cancelled") == "other"
    assert organ_key("General disorders") == "general"
    assert organ_key("GASTROINTESTINAL DISORDERS") == "gastrointestinal"
    assert organ_key("Not an organ") is None
    assert term_key("  Upper  respiratory tract infection. ") == "upper respiratory tract infection"


def test_counts_as_text_or_numbers() -> None:
    raw = groups_study("Drug", at_risk=(1,))
    group = raw["resultsSection"]["adverseEventsModule"]["eventGroups"][0]
    group.update(seriousNumAtRisk="1,234", seriousNumAffected=12, deathsNumAffected="NA")
    results = parse(raw)
    assert results is not None
    assert results.adverse_events is not None
    parsed = results.adverse_events.groups[0]
    assert (parsed.serious_at_risk, parsed.serious_affected, parsed.deaths) == (1234, 12, None)


def test_outcome_analyses() -> None:
    (first, *_) = analyses(study("NCT04102579"))
    assert (first.kind, first.p, first.p_bound) == ("PRIMARY", 0.0001, "<")
    assert (first.estimate_type, first.estimate) == ("mean_difference", -3.16)
    assert (first.ci_lower, first.ci_upper) == (-4.37, -1.95)
    assert p_value("= .05") == (0.05, None)
    assert p_value(">0.99") == (0.99, ">")
    assert p_value("NA") == (None, None)
    assert p_value("1.5") == (None, None)
    assert estimate_key("Hazard Ratio (HR)") == "hazard_ratio"
    assert estimate_key("Spearman Correlation") == "other"
    assert hypothesis_key("NON_INFERIORITY_OR_EQUIVALENCE_LEGACY") == "non_inferiority"
    assert hypothesis_key(None) is None
