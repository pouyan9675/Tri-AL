"""A study's posted results (ClinicalTrials.gov's ``resultsSection``) as plain data.

Results come in five modules: the participant flow, baseline characteristics, outcome
measures, adverse events, and more information (limitations and publication agreements).
Each module names its own groups (``FG000`` in the flow, ``BG000`` in the baseline, ``OG000``
in each outcome, ``EG000`` in adverse events), so counts are keyed by group id within their
module. Counts arrive as JSON numbers or as text and are read as ints; measured values are
kept as the text given ("NA", "<0.001"), since that is what the registry shows.

``parse`` reads a whole study (the arms tell which adverse-event groups took placebo);
``summary`` boils results down to what the plugin's tables keep. The point of contact (a
person's name, email and phone) is left out on purpose.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

type Json = Mapping[str, Any]
type Reporting = Literal["standard", "custom", "not_collected", "none"]

RACE: Mapping[str, str] = {
    "white": "White",
    "black": "Black or African American",
    "asian": "Asian",
    "aian": "American Indian or Alaska Native",
    "nhpi": "Native Hawaiian or Other Pacific Islander",
    "multiple": "More than one race",
    "other": "Other",
    "unknown": "Unknown or not reported",
}
"""The NIH/OMB race categories, in the order charts show them."""

ETHNICITY: Mapping[str, str] = {
    "hispanic": "Hispanic or Latino",
    "not_hispanic": "Not Hispanic or Latino",
    "unknown": "Unknown or not reported",
}

REPORTING: Mapping[Reporting, str] = {
    "standard": "Standard categories",
    "custom": "Own categories",
    "not_collected": "Not collected",
    "none": "Not reported",
}
"""How a trial reported race or ethnicity: the NIH/OMB categories ClinicalTrials.gov asks
for, categories of its own, a statement that it didn't collect them, or nothing."""

DROPOUTS: Mapping[str, str] = {
    "adverse_event": "Adverse event",
    "death": "Death",
    "lack_of_efficacy": "Lack of efficacy",
    "progression": "Disease progression",
    "withdrawal": "Withdrew",
    "lost": "Lost to follow-up",
    "physician": "Physician decision",
    "protocol": "Protocol violation",
    "ineligible": "Not eligible",
    "sponsor": "Sponsor ended it",
    "pregnancy": "Pregnancy",
    "other": "Other",
}
"""Why participants left, as kinds; the registry's reasons are free text (32,000 of them),
though most use its suggested wording."""

ORGANS: Mapping[str, str] = {
    "blood": "Blood and lymphatic system",
    "cardiac": "Cardiac",
    "congenital": "Congenital, familial and genetic",
    "ear": "Ear and labyrinth",
    "endocrine": "Endocrine",
    "eye": "Eye",
    "gastrointestinal": "Gastrointestinal",
    "general": "General and administration site",
    "hepatobiliary": "Hepatobiliary",
    "immune": "Immune system",
    "infections": "Infections and infestations",
    "injury": "Injury, poisoning and procedural",
    "investigations": "Investigations",
    "metabolism": "Metabolism and nutrition",
    "musculoskeletal": "Musculoskeletal and connective tissue",
    "neoplasms": "Neoplasms",
    "nervous": "Nervous system",
    "pregnancy": "Pregnancy and perinatal",
    "product": "Product issues",
    "psychiatric": "Psychiatric",
    "renal": "Renal and urinary",
    "reproductive": "Reproductive system and breast",
    "respiratory": "Respiratory, thoracic and mediastinal",
    "skin": "Skin and subcutaneous tissue",
    "social": "Social circumstances",
    "surgical": "Surgical and medical procedures",
    "vascular": "Vascular",
}
"""MedDRA's 27 system organ classes, keyed by their first word. Trials spell them about a
hundred ways (case, "General disorders" for the full name, CTCAE's names); each folds into
one of these by its first word, or into none."""

ORGAN_CODES: Mapping[str, int] = {key: i + 1 for i, key in enumerate(ORGANS)}
"""Each organ class as a small number, which the events table stores."""


@dataclass(frozen=True, slots=True)
class Group:
    id: str
    title: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class Milestone:
    label: str  # STARTED, COMPLETED, NOT COMPLETED, or a milestone of the trial's own
    counts: dict[str, int]  # participants, by flow group


@dataclass(frozen=True, slots=True)
class Dropout:
    reason: str  # as the trial gave it
    kind: str  # a key of DROPOUTS
    counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class Period:
    title: str
    milestones: tuple[Milestone, ...]
    dropouts: tuple[Dropout, ...]


@dataclass(frozen=True, slots=True)
class Flow:
    groups: tuple[Group, ...]
    periods: tuple[Period, ...]
    recruitment: str | None = None
    pre_assignment: str | None = None

    def total(self, label: str, *, last: bool = False) -> int | None:
        """Everyone at a milestone, in the first period (the last with ``last``)."""
        if not self.periods:
            return None
        period = self.periods[-1] if last else self.periods[0]
        for milestone in period.milestones:
            if milestone.label == label:
                return sum(milestone.counts.values())
        return None


@dataclass(frozen=True, slots=True)
class Value:
    value: str | None
    spread: str | None = None
    lower: str | None = None
    upper: str | None = None
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class Category:
    title: str
    values: dict[str, Value]  # by group


@dataclass(frozen=True, slots=True)
class MeasureClass:
    title: str
    categories: tuple[Category, ...]


@dataclass(frozen=True, slots=True)
class Measure:
    """A baseline characteristic: sex, age, race, region of enrollment, a score, ..."""

    title: str
    param: str | None  # MEAN, MEDIAN, COUNT_OF_PARTICIPANTS, ...
    dispersion: str | None  # STANDARD_DEVIATION, ...
    unit: str | None
    classes: tuple[MeasureClass, ...]
    description: str | None = None
    population: str | None = None


@dataclass(frozen=True, slots=True)
class Baseline:
    groups: tuple[Group, ...]
    total: str | None  # the group of everyone ("Total"), or the only group
    participants: dict[str, int]  # analysed, by group
    measures: tuple[Measure, ...]
    population: str | None = None


@dataclass(frozen=True, slots=True)
class Analysis:
    """A statistical comparison of an outcome's groups."""

    groups: tuple[str, ...]
    method: str | None = None
    p_value: str | None = None
    estimate_type: str | None = None  # "Hazard Ratio (HR)", "Mean Difference (Final Values)", ...
    estimate: str | None = None
    ci_percent: str | None = None
    ci_lower: str | None = None
    ci_upper: str | None = None
    hypothesis: str | None = None  # SUPERIORITY, NON_INFERIORITY, EQUIVALENCE, ...
    description: str | None = None


@dataclass(frozen=True, slots=True)
class OutcomeResult:
    type: str  # PRIMARY, SECONDARY, OTHER_PRE_SPECIFIED, POST_HOC
    title: str
    groups: tuple[Group, ...]
    participants: dict[str, int]  # analysed, by group
    classes: tuple[MeasureClass, ...]
    analyses: tuple[Analysis, ...] = ()
    description: str | None = None
    time_frame: str | None = None
    population: str | None = None
    param: str | None = None
    dispersion: str | None = None
    unit: str | None = None
    posted: bool = True  # False: the trial says the data come later


@dataclass(frozen=True, slots=True)
class EventGroup:
    """An arm as adverse events were counted in it."""

    id: str
    title: str
    description: str | None = None
    placebo: bool = False
    total: bool = False  # everyone, as well as each arm: left out of sums and comparisons
    serious_affected: int | None = None
    serious_at_risk: int | None = None
    other_affected: int | None = None
    other_at_risk: int | None = None
    deaths: int | None = None
    deaths_at_risk: int | None = None


@dataclass(frozen=True, slots=True)
class EventCount:
    affected: int | None
    at_risk: int | None
    events: int | None = None


@dataclass(frozen=True, slots=True)
class Event:
    term: str
    serious: bool
    counts: dict[str, EventCount]  # by event group
    organ: str | None = None  # as given
    organ_key: str | None = None  # a key of ORGANS
    vocabulary: str | None = None
    systematic: bool | None = None


@dataclass(frozen=True, slots=True)
class AdverseEvents:
    groups: tuple[EventGroup, ...]
    events: tuple[Event, ...]  # serious ones first
    threshold: float | None = None  # % above which other (not serious) events are listed
    time_frame: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class Agreement:
    """What the sponsor's agreement lets investigators publish."""

    pi_sponsor_employee: bool | None = None
    restrictive: bool | None = None
    restriction: str | None = None  # LTE60, GT60 (days of review) or OTHER
    details: str | None = None


@dataclass(frozen=True, slots=True)
class Results:
    flow: Flow | None = None
    baseline: Baseline | None = None
    outcomes: tuple[OutcomeResult, ...] = ()
    adverse_events: AdverseEvents | None = None
    limitations: str | None = None
    agreement: Agreement | None = None


def parse(study: Json, *, outcomes: bool = True) -> Results | None:
    """The study's results, or None if it has none; without ``outcomes``, no outcome measures
    (most of the work, which ``summary`` doesn't need)."""
    section = study.get("resultsSection")
    if not isinstance(section, Mapping) or not section:
        return None
    more = _map(section, "moreInfoModule")
    agreement = _map(more, "certainAgreement")
    return Results(
        flow=_flow(_map(section, "participantFlowModule")),
        baseline=_baseline(_map(section, "baselineCharacteristicsModule")),
        outcomes=tuple(
            _outcome(om) for om in _list(_map(section, "outcomeMeasuresModule"), "outcomeMeasures")
        )
        if outcomes
        else (),
        adverse_events=_adverse_events(_map(section, "adverseEventsModule"), _placebo_arms(study)),
        limitations=_text(_map(more, "limitationsAndCaveats"), "description"),
        agreement=(
            Agreement(
                pi_sponsor_employee=_bool(agreement.get("piSponsorEmployee")),
                restrictive=_bool(agreement.get("restrictiveAgreement")),
                restriction=_text(agreement, "restrictionType"),
                details=_text(agreement, "otherDetails"),
            )
            if agreement
            else None
        ),
    )


# --- what the tables keep ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Summary:
    """One trial's results in numbers: who took part, who left, and its adverse events."""

    participants: int | None = None
    race: Reporting = "none"
    ethnicity: Reporting = "none"
    races: dict[str, int] = field(default_factory=dict)  # standard categories only
    ethnicities: dict[str, int] = field(default_factory=dict)
    female: int | None = None
    male: int | None = None
    age: float | None = None  # mean age in years, of everyone
    started: int | None = None
    completed: int | None = None
    dropouts: dict[str, int] = field(default_factory=dict)  # by DROPOUTS kind
    ae_groups: int = 0  # arms, not counting a group of everyone
    placebo_groups: int = 0
    at_risk: int | None = None  # for serious events
    serious: int | None = None
    deaths_at_risk: int | None = None
    deaths: int | None = None
    other_at_risk: int | None = None
    other: int | None = None
    threshold: float | None = None
    events: tuple["EventSum", ...] = ()


@dataclass(frozen=True, slots=True)
class EventSum:
    """An event over a trial's arms: those on placebo apart, when it has both kinds."""

    term: str
    serious: bool
    organ: str | None  # a key of ORGANS
    affected: int  # in the other arms (all of them, if none took placebo)
    at_risk: int
    placebo_affected: int | None = None
    placebo_at_risk: int | None = None


def summary(results: Results) -> Summary:
    out: dict[str, Any] = {}
    if results.baseline is not None:
        out.update(_people(results.baseline))
    if results.flow is not None:
        out["started"] = results.flow.total("STARTED")
        out["completed"] = results.flow.total("COMPLETED", last=True)
        dropouts: dict[str, int] = {}
        for period in results.flow.periods:
            for dropout in period.dropouts:
                count = sum(dropout.counts.values())
                if count:
                    dropouts[dropout.kind] = dropouts.get(dropout.kind, 0) + count
        out["dropouts"] = dropouts
    if results.adverse_events is not None:
        out.update(_safety(results.adverse_events))
    return Summary(**out)


def _people(baseline: Baseline) -> dict[str, Any]:
    out: dict[str, Any] = {}
    total = baseline.total
    if total is not None:
        out["participants"] = baseline.participants.get(total)
    titles = {measure.title for measure in baseline.measures}
    custom_race = custom_ethnicity = False
    for measure in baseline.measures:
        title = measure.title
        if title == "Race (NIH/OMB)":
            out["races"] = _categories(measure, total, race_key)
        elif title == "Ethnicity (NIH/OMB)":
            out["ethnicities"] = _categories(measure, total, ethnicity_key)
        elif title in ("Race/Ethnicity, Customized", "Race, Customized"):
            custom_race = True
            custom_ethnicity = custom_ethnicity or title == "Race/Ethnicity, Customized"
        elif title == "Ethnicity, Customized":
            custom_ethnicity = True
        elif title != "Race and Ethnicity Not Collected":
            # Older trials name the measure themselves: "Race", "Ethnicity", "Race/Ethnicity".
            custom_race = custom_race or bool(_RACE_WORD.search(title))
            custom_ethnicity = custom_ethnicity or bool(_ETHNIC_WORD.search(title))
        if title in ("Sex: Female, Male", "Gender", "Sex"):
            sexes = _categories(measure, total, _sex)
            if sexes:
                out["female"], out["male"] = sexes.get("female", 0), sexes.get("male", 0)
        if out.get("age") is None and _AGE.match(title) and measure.param == "MEAN":
            out["age"] = _years(measure, total)
    not_collected = "Race and Ethnicity Not Collected" in titles

    def reporting(standard: bool, custom: bool) -> Reporting:
        if standard:
            return "standard"
        if custom:
            return "custom"
        return "not_collected" if not_collected else "none"

    out["race"] = reporting("Race (NIH/OMB)" in titles, custom_race)
    out["ethnicity"] = reporting("Ethnicity (NIH/OMB)" in titles, custom_ethnicity)
    return out


def _categories(measure: Measure, group: str | None, key: Any) -> dict[str, int]:
    """Participants in ``group`` per category key, from a count measure."""
    counts: dict[str, int] = {}
    if group is None:
        return counts
    for cls in measure.classes:
        for category in cls.categories:
            code = key(category.title or cls.title)
            value = category.values.get(group)
            number = _int(value.value) if value is not None else None
            if code is not None and number:
                counts[code] = counts.get(code, 0) + number
    return counts


def _years(measure: Measure, group: str | None) -> float | None:
    if group is None or not measure.classes or not measure.classes[0].categories:
        return None
    value = measure.classes[0].categories[0].values.get(group)
    number = _float(value.value) if value is not None else None
    if number is None:
        return None
    unit = (measure.unit or "years").lower()
    for word, per_year in (("month", 12), ("week", 52.18), ("day", 365.25)):
        if word in unit:
            return number / per_year
    return number if "year" in unit or not unit.strip() else None


def _safety(ae: AdverseEvents) -> dict[str, Any]:
    arms = [group for group in ae.groups if not group.total]
    placebo = {group.id for group in arms if group.placebo}
    # Placebo apart only when there are other arms to compare it with.
    compare = bool(placebo) and len(placebo) < len(arms)
    arm_ids = {group.id for group in arms}

    def total(name: str) -> int | None:
        values = [getattr(group, name) for group in arms]
        known = [value for value in values if value is not None]
        return sum(known) if known else None

    events: list[EventSum] = []
    for event in ae.events:
        sums = [0, 0, 0, 0]  # affected, at risk, placebo affected, placebo at risk
        for group_id, count in event.counts.items():
            if group_id not in arm_ids or count.at_risk is None:
                continue
            side = 2 if compare and group_id in placebo else 0
            sums[side] += count.affected or 0
            sums[side + 1] += count.at_risk
        if sums[1] == 0 and sums[3] == 0:
            continue
        events.append(
            EventSum(
                event.term,
                event.serious,
                event.organ_key,
                sums[0],
                sums[1],
                sums[2] if compare else None,
                sums[3] if compare else None,
            )
        )
    return {
        "ae_groups": len(arms),
        "placebo_groups": len(placebo) if compare else 0,
        "at_risk": total("serious_at_risk"),
        "serious": total("serious_affected"),
        "deaths_at_risk": total("deaths_at_risk"),
        "deaths": total("deaths"),
        "other_at_risk": total("other_at_risk"),
        "other": total("other_affected"),
        "threshold": ae.threshold,
        "events": tuple(events),
    }


# --- outcome analyses, for the tables ------------------------------------------------------

ESTIMATES: Mapping[str, str] = {
    "hazard_ratio": "Hazard ratio",
    "odds_ratio": "Odds ratio",
    "risk_ratio": "Risk ratio",
    "risk_difference": "Risk difference",
    "mean_difference": "Mean difference",
    "other": "Other",
}
"""Kinds of effect estimate; trials name them 6,600 ways ("LS Mean Difference", ...)."""

HYPOTHESES: Mapping[str, str] = {
    "superiority": "Superiority",
    "superiority_or_other": "Superiority or other",
    "non_inferiority": "Non-inferiority",
    "equivalence": "Equivalence",
    "other": "Other",
}
RATIOS = ("hazard_ratio", "odds_ratio", "risk_ratio")


@dataclass(frozen=True, slots=True)
class AnalysisSum:
    """One statistical analysis of an outcome, in numbers."""

    outcome: int  # the outcome's place among the trial's outcome measures
    analysis: int  # its place among the outcome's analyses
    kind: str  # PRIMARY, SECONDARY, OTHER_PRE_SPECIFIED, POST_HOC
    p: float | None = None
    p_bound: str | None = None  # "<" or ">" when the p-value is a bound ("<0.001")
    estimate_type: str | None = None  # a key of ESTIMATES
    estimate: float | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    hypothesis: str | None = None  # a key of HYPOTHESES


def analyses(study: Json) -> tuple[AnalysisSum, ...]:
    """Every analysis of the study's outcome measures, read straight from the JSON (much less
    work than ``parse``)."""
    module = _map(_map(study, "resultsSection"), "outcomeMeasuresModule")
    out: list[AnalysisSum] = []
    for i, measure in enumerate(_list(module, "outcomeMeasures")):
        kind = _text(measure, "type") or "OTHER"
        for j, analysis in enumerate(_list(measure, "analyses")):
            p, bound = p_value(_text(analysis, "pValue"))
            estimate_kind = _text(analysis, "paramType")
            out.append(
                AnalysisSum(
                    outcome=i,
                    analysis=j,
                    kind=kind,
                    p=p,
                    p_bound=bound,
                    estimate_type=estimate_key(estimate_kind) if estimate_kind else None,
                    estimate=_float(analysis.get("paramValue")),
                    ci_lower=_float(analysis.get("ciLowerLimit")),
                    ci_upper=_float(analysis.get("ciUpperLimit")),
                    hypothesis=hypothesis_key(_text(analysis, "nonInferiorityType")),
                )
            )
    return tuple(out)


def p_value(text: str | None) -> tuple[float | None, str | None]:
    """A p-value as written ("<0.001", "0.032", "= .05", "≥0.99") as a number, and whether
    it's an upper or lower bound; (None, None) if it isn't one."""
    match = _P_VALUE.match(text or "")
    if not match:
        return None, None
    value = float(match[2])
    if not 0 <= value <= 1:
        return None, None
    sign = match[1]
    return value, "<" if sign in ("<", "≤") else ">" if sign in (">", "≥") else None


def estimate_key(name: str) -> str:
    text = name.lower()
    for pattern, key in _ESTIMATES:
        if pattern.search(text):
            return key
    return "other"


def hypothesis_key(code: str | None) -> str | None:
    if not code:
        return None
    code = code.upper().removesuffix("_LEGACY")
    if code.startswith("NON_INFERIORITY"):
        return "non_inferiority"
    return {
        "SUPERIORITY": "superiority",
        "SUPERIORITY_OR_OTHER": "superiority_or_other",
        "EQUIVALENCE": "equivalence",
    }.get(code, "other")


_P_VALUE = re.compile(r"^\s*([<>≤≥=]?)\s*=?\s*(\d*\.?\d+(?:[eE]-?\d+)?)")
_ESTIMATES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"hazard"), "hazard_ratio"),
    (re.compile(r"odds"), "odds_ratio"),
    (re.compile(r"(risk|rate|incidence) ratio|relative risk"), "risk_ratio"),
    (re.compile(r"risk difference|difference in (proportion|percent|rate)"), "risk_difference"),
    (re.compile(r"mean|difference|slope|change"), "mean_difference"),
)


# --- normalizing names ---------------------------------------------------------------------


def race_key(title: str) -> str | None:
    """A race category's key, from the standard name or a common variant; None if blank."""
    text = title.strip().lower()
    if not text:
        return None
    for pattern, key in _RACES:
        if pattern.search(text):
            return key
    return "other"


def ethnicity_key(title: str) -> str | None:
    text = title.strip().lower()
    if not text:
        return None
    if _UNKNOWN.search(text):
        return "unknown"
    if re.search(r"\bnot?\b|\bnon[- ]?", text):
        return "not_hispanic"
    if re.search(r"hispanic|latin", text):
        return "hispanic"
    return "unknown"


def dropout_kind(reason: str) -> str:
    text = reason.lower()
    for pattern, kind in _DROPOUT_KINDS:
        if pattern.search(text):
            return kind
    return "other"


def organ_key(name: str | None) -> str | None:
    if not name:
        return None
    first = re.match(r"[a-z]+", name.strip().lower())
    return first.group() if first and first.group() in ORGANS else None


def term_key(term: str) -> str:
    """The form events are counted under: case and spacing don't make a different event."""
    return " ".join(term.lower().split()).rstrip(".")


_RACE_WORD = re.compile(r"\brac(e|ial)\b", re.I)
_ETHNIC_WORD = re.compile(r"\bethnic", re.I)
_AGE = re.compile(r"^age\b,?\s*(continuous)?$", re.I)
_UNKNOWN = re.compile(
    r"unknown|not reported|not available|missing|declin|refus|prefer not|not collected"
    r"|not provided|unavailable|not specified|not stated",
)
_RACES: tuple[tuple[re.Pattern[str], str], ...] = (
    (_UNKNOWN, "unknown"),
    (re.compile(r"more than one|multi|mixed|two or more|biracial"), "multiple"),
    (re.compile(r"hawaii|pacific"), "nhpi"),
    (re.compile(r"american indian|alaska|native american|first nations"), "aian"),
    (re.compile(r"black|african"), "black"),
    (re.compile(r"\basian"), "asian"),  # not "caucasian"
    (re.compile(r"white|caucasian"), "white"),
)
_DROPOUT_KINDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"adverse|side effect|toxicit|intoleran"), "adverse_event"),
    (re.compile(r"death|died|deceased"), "death"),
    (
        re.compile(r"efficacy|lack of (response|benefit|improvement)|ineffective"),
        "lack_of_efficacy",
    ),
    (re.compile(r"progress|relapse|recurren"), "progression"),
    (re.compile(r"lost to follow"), "lost"),
    (
        re.compile(
            r"withdr[ae]w|consent|subject decision|participant decision|patient decision"
            r"|patient choice|personal reason"
        ),
        "withdrawal",
    ),
    (re.compile(r"physician|investigator"), "physician"),
    (re.compile(r"protocol (violation|deviation)|non-?complian"), "protocol"),
    (re.compile(r"eligib|inclusion|exclusion|criteria|screen fail"), "ineligible"),
    (re.compile(r"sponsor|study (was )?(terminat|stop|clos)|site (terminat|clos)"), "sponsor"),
    (re.compile(r"pregnan"), "pregnancy"),
)
_TOTAL = re.compile(
    r"^\W*(total|overall|all)\W*"
    r"(\(.*\)|\b(participants|subjects|patients|population|groups|arms|cohorts)\b.*)?$",
    re.I,
)
"""A group of everyone ("Total", "All participants"), not an arm called "Total Intravenous
Anesthesia"."""
_PLACEBO = re.compile(r"^\W*(matching\s+)?(placebo|sham|vehicle)\b", re.I)
_NOT_JUST_PLACEBO = re.compile(
    r"\b(then|followed|switch\w*|cross-?over|extension|open[- ]label|to)\b|/|->|→", re.I
)


def _sex(title: str) -> str | None:
    text = title.strip().lower()
    if text in ("female", "females", "women", "woman"):
        return "female"
    if text in ("male", "males", "men", "man"):
        return "male"
    return None


# --- modules -------------------------------------------------------------------------------


def _flow(module: Json) -> Flow | None:
    if not module:
        return None
    periods = []
    for period in _list(module, "periods"):
        milestones = tuple(
            Milestone(
                _text(milestone, "type") or "",
                _counts(_list(milestone, "achievements"), "numSubjects"),
            )
            for milestone in _list(period, "milestones")
        )
        dropouts = tuple(
            Dropout(
                reason := _text(drop, "type") or "Other",
                dropout_kind(reason),
                _counts(_list(drop, "reasons"), "numSubjects"),
            )
            for drop in _list(period, "dropWithdraws")
        )
        periods.append(Period(_text(period, "title") or "Overall Study", milestones, dropouts))
    return Flow(
        _groups(module),
        tuple(periods),
        recruitment=_text(module, "recruitmentDetails"),
        pre_assignment=_text(module, "preAssignmentDetails"),
    )


def _baseline(module: Json) -> Baseline | None:
    if not module:
        return None
    groups = _groups(module)
    total = next((g.id for g in groups if g.title.strip().lower() == "total"), None)
    if total is None and len(groups) == 1:
        total = groups[0].id
    denoms = _list(module, "denoms")
    return Baseline(
        groups,
        total,
        _counts(_list(denoms[0], "counts"), "value") if denoms else {},
        tuple(
            Measure(
                title=_text(measure, "title") or "",
                param=_text(measure, "paramType"),
                dispersion=_text(measure, "dispersionType"),
                unit=_text(measure, "unitOfMeasure"),
                classes=_classes(measure),
                description=_text(measure, "description"),
                population=_text(measure, "populationDescription"),
            )
            for measure in _list(module, "measures")
        ),
        population=_text(module, "populationDescription"),
    )


def _outcome(measure: Json) -> OutcomeResult:
    denoms = _list(measure, "denoms")
    return OutcomeResult(
        type=_text(measure, "type") or "OTHER",
        title=_text(measure, "title") or "",
        groups=_groups(measure),
        participants=_counts(_list(denoms[0], "counts"), "value") if denoms else {},
        classes=_classes(measure),
        analyses=tuple(
            Analysis(
                groups=tuple(str(g) for g in analysis.get("groupIds") or ()),
                method=_text(analysis, "statisticalMethod"),
                p_value=_text(analysis, "pValue"),
                estimate_type=_text(analysis, "paramType"),
                estimate=_text(analysis, "paramValue"),
                ci_percent=_text(analysis, "ciPctValue"),
                ci_lower=_text(analysis, "ciLowerLimit"),
                ci_upper=_text(analysis, "ciUpperLimit"),
                hypothesis=_text(analysis, "nonInferiorityType"),
                description=_text(analysis, "groupDescription"),
            )
            for analysis in _list(measure, "analyses")
        ),
        description=_text(measure, "description"),
        time_frame=_text(measure, "timeFrame"),
        population=_text(measure, "populationDescription"),
        param=_text(measure, "paramType"),
        dispersion=_text(measure, "dispersionType"),
        unit=_text(measure, "unitOfMeasure"),
        posted=_text(measure, "reportingStatus") != "NOT_POSTED",
    )


def _adverse_events(module: Json, placebo_arms: set[str]) -> AdverseEvents | None:
    if not module:
        return None
    raw_groups = _list(module, "eventGroups")
    at_risk = [_int(group.get("seriousNumAtRisk")) for group in raw_groups]
    groups = []
    for i, group in enumerate(raw_groups):
        title = _text(group, "title") or ""
        mine = at_risk[i]
        others = [n for j, n in enumerate(at_risk) if j != i]
        total = bool(_TOTAL.match(title)) or (
            len(raw_groups) >= 3
            and mine is not None
            and mine > 0
            and None not in others
            and mine == sum(n or 0 for n in others)
        )
        placebo = not total and (
            _key(title) in placebo_arms
            or (bool(_PLACEBO.match(title)) and not _NOT_JUST_PLACEBO.search(title))
        )
        groups.append(
            EventGroup(
                id=str(group.get("id") or f"EG{i:03d}"),
                title=title,
                description=_text(group, "description"),
                placebo=placebo,
                total=total,
                serious_affected=_int(group.get("seriousNumAffected")),
                serious_at_risk=at_risk[i],
                other_affected=_int(group.get("otherNumAffected")),
                other_at_risk=_int(group.get("otherNumAtRisk")),
                deaths=_int(group.get("deathsNumAffected")),
                deaths_at_risk=_int(group.get("deathsNumAtRisk")),
            )
        )
    events = [
        Event(
            term=_text(event, "term") or "",
            serious=serious,
            counts={
                str(stat.get("groupId")): EventCount(
                    _int(stat.get("numAffected")),
                    _int(stat.get("numAtRisk")),
                    _int(stat.get("numEvents")),
                )
                for stat in _list(event, "stats")
            },
            organ=(organ := _text(event, "organSystem")),
            organ_key=organ_key(organ),
            vocabulary=_text(event, "sourceVocabulary"),
            systematic=(
                None
                if not event.get("assessmentType")
                else event["assessmentType"] == "SYSTEMATIC_ASSESSMENT"
            ),
        )
        for serious, key in ((True, "seriousEvents"), (False, "otherEvents"))
        for event in _list(module, key)
        if _text(event, "term")
    ]
    return AdverseEvents(
        tuple(groups),
        tuple(events),
        threshold=_float(module.get("frequencyThreshold")),
        time_frame=_text(module, "timeFrame"),
        description=_text(module, "description"),
    )


def _placebo_arms(study: Json) -> set[str]:
    arms = _list(_map(_map(study, "protocolSection"), "armsInterventionsModule"), "armGroups")
    return {
        _key(_text(arm, "label") or "")
        for arm in arms
        if arm.get("type") in ("PLACEBO_COMPARATOR", "SHAM_COMPARATOR")
    } - {""}


def _groups(module: Json) -> tuple[Group, ...]:
    return tuple(
        Group(str(group.get("id") or ""), _text(group, "title") or "", _text(group, "description"))
        for group in _list(module, "groups")
    )


def _classes(measure: Json) -> tuple[MeasureClass, ...]:
    return tuple(
        MeasureClass(
            _text(cls, "title") or "",
            tuple(
                Category(
                    _text(category, "title") or "",
                    {
                        str(m.get("groupId")): Value(
                            _text(m, "value"),
                            _text(m, "spread"),
                            _text(m, "lowerLimit"),
                            _text(m, "upperLimit"),
                            _text(m, "comment"),
                        )
                        for m in _list(category, "measurements")
                    },
                )
                for category in _list(cls, "categories")
            ),
        )
        for cls in _list(measure, "classes")
    )


def _counts(items: Sequence[Json], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        number = _int(item.get(key))
        if number is not None:
            counts[str(item.get("groupId"))] = number
    return counts


# --- reading JSON --------------------------------------------------------------------------
# Documents come from orjson, so objects are dicts: checking for dict, not Mapping, is
# several times faster, and this runs millions of times in a build.


def _map(value: Any, key: str) -> Json:
    child = value.get(key) if isinstance(value, dict) else None
    return child if isinstance(child, dict) else {}


def _list(value: Any, key: str) -> list[Json]:
    child = value.get(key) if isinstance(value, dict) else None
    return [item for item in child if isinstance(item, dict)] if isinstance(child, list) else []


def _text(value: Json, key: str) -> str | None:
    child = value.get(key)
    if child is None:
        return None
    if type(child) is str:
        return child.strip() or None
    if isinstance(child, (dict, list)):
        return None
    return str(child)


def _int(value: Any) -> int | None:
    kind = type(value)
    if kind is int:
        return value  # type: ignore[no-any-return]
    if kind is bool or value is None:
        return None
    number = _float(value)
    return None if number is None else round(number)


def _float(value: Any) -> float | None:
    kind = type(value)
    if kind is bool or value is None:
        return None
    if kind is int or kind is float:
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return None


def _key(title: str) -> str:
    return " ".join(title.lower().split())


__all__ = [
    "DROPOUTS",
    "ESTIMATES",
    "ETHNICITY",
    "HYPOTHESES",
    "ORGANS",
    "ORGAN_CODES",
    "RACE",
    "RATIOS",
    "REPORTING",
    "AdverseEvents",
    "Agreement",
    "Analysis",
    "AnalysisSum",
    "Baseline",
    "Category",
    "Dropout",
    "Event",
    "EventCount",
    "EventGroup",
    "EventSum",
    "Flow",
    "Group",
    "Measure",
    "MeasureClass",
    "Milestone",
    "OutcomeResult",
    "Period",
    "Reporting",
    "Results",
    "Summary",
    "Value",
    "analyses",
    "dropout_kind",
    "estimate_key",
    "ethnicity_key",
    "hypothesis_key",
    "organ_key",
    "p_value",
    "parse",
    "race_key",
    "summary",
    "term_key",
]
