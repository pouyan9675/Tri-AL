"""Display names for the coded fields of ``TrialRecord``, as ClinicalTrials.gov shows them.

Facets and charts send these along with the codes, so the front end needs no copy. A code
without a label here (a newer one, or another registry's) is shown as the code itself.
"""

from collections.abc import Mapping

STATUS: Mapping[str, str] = {
    "RECRUITING": "Recruiting",
    "NOT_YET_RECRUITING": "Not yet recruiting",
    "ENROLLING_BY_INVITATION": "Enrolling by invitation",
    "ACTIVE_NOT_RECRUITING": "Active, not recruiting",
    "SUSPENDED": "Suspended",
    "TERMINATED": "Terminated",
    "COMPLETED": "Completed",
    "WITHDRAWN": "Withdrawn",
    "UNKNOWN": "Unknown status",
    "AVAILABLE": "Available",
    "NO_LONGER_AVAILABLE": "No longer available",
    "TEMPORARILY_NOT_AVAILABLE": "Temporarily not available",
    "APPROVED_FOR_MARKETING": "Approved for marketing",
    "WITHHELD": "Withheld",
}

PHASE: Mapping[str, str] = {
    "EARLY_PHASE1": "Early phase 1",
    "PHASE1": "Phase 1",
    "PHASE1_PHASE2": "Phase 1/2",
    "PHASE2": "Phase 2",
    "PHASE2_PHASE3": "Phase 2/3",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "NA": "Not applicable",
}
"""In the order phases come in, which charts keep."""

STUDY_TYPE: Mapping[str, str] = {
    "INTERVENTIONAL": "Interventional",
    "OBSERVATIONAL": "Observational",
    "EXPANDED_ACCESS": "Expanded access",
}

SPONSOR_CLASS: Mapping[str, str] = {
    "INDUSTRY": "Industry",
    "NIH": "NIH",
    "FED": "Other U.S. federal agency",
    "OTHER_GOV": "Other government",
    "NETWORK": "Network",
    "INDIV": "Individual",
    "OTHER": "Other",
    "AMBIG": "Ambiguous",
    "UNKNOWN": "Unknown",
}

INTERVENTION_TYPE: Mapping[str, str] = {
    "DRUG": "Drug",
    "BIOLOGICAL": "Biological",
    "DEVICE": "Device",
    "PROCEDURE": "Procedure",
    "BEHAVIORAL": "Behavioral",
    "DIETARY_SUPPLEMENT": "Dietary supplement",
    "DIAGNOSTIC_TEST": "Diagnostic test",
    "RADIATION": "Radiation",
    "GENETIC": "Genetic",
    "COMBINATION_PRODUCT": "Combination product",
    "OTHER": "Other",
}

PRIMARY_PURPOSE: Mapping[str, str] = {
    "TREATMENT": "Treatment",
    "PREVENTION": "Prevention",
    "DIAGNOSTIC": "Diagnostic",
    "SUPPORTIVE_CARE": "Supportive care",
    "SCREENING": "Screening",
    "HEALTH_SERVICES_RESEARCH": "Health services research",
    "BASIC_SCIENCE": "Basic science",
    "DEVICE_FEASIBILITY": "Device feasibility",
    "ECT": "Educational/counseling/training",
    "OTHER": "Other",
}

ARM_TYPE: Mapping[str, str] = {
    "EXPERIMENTAL": "Experimental",
    "ACTIVE_COMPARATOR": "Active comparator",
    "PLACEBO_COMPARATOR": "Placebo comparator",
    "SHAM_COMPARATOR": "Sham comparator",
    "NO_INTERVENTION": "No intervention",
    "OTHER": "Other",
}

ALLOCATION: Mapping[str, str] = {
    "RANDOMIZED": "Randomized",
    "NON_RANDOMIZED": "Non-randomized",
    "NA": "Not applicable",
}

INTERVENTION_MODEL: Mapping[str, str] = {
    "PARALLEL": "Parallel assignment",
    "SINGLE_GROUP": "Single group assignment",
    "CROSSOVER": "Crossover assignment",
    "FACTORIAL": "Factorial assignment",
    "SEQUENTIAL": "Sequential assignment",
}

OBSERVATIONAL_MODEL: Mapping[str, str] = {
    "COHORT": "Cohort",
    "CASE_CONTROL": "Case-control",
    "CASE_ONLY": "Case-only",
    "CASE_CROSSOVER": "Case-crossover",
    "ECOLOGIC_OR_COMMUNITY": "Ecologic or community",
    "FAMILY_BASED": "Family-based",
    "DEFINED_POPULATION": "Defined population",
    "NATURAL_HISTORY": "Natural history",
    "OTHER": "Other",
}

TIME_PERSPECTIVE: Mapping[str, str] = {
    "PROSPECTIVE": "Prospective",
    "RETROSPECTIVE": "Retrospective",
    "CROSS_SECTIONAL": "Cross-sectional",
    "OTHER": "Other",
}

MASKING: Mapping[str, str] = {
    "NONE": "Open label",
    "SINGLE": "Single-blind",
    "DOUBLE": "Double-blind",
    "TRIPLE": "Triple-blind",
    "QUADRUPLE": "Quadruple-blind",
}

MASKED_ROLE: Mapping[str, str] = {
    "PARTICIPANT": "Participant",
    "CARE_PROVIDER": "Care provider",
    "INVESTIGATOR": "Investigator",
    "OUTCOMES_ASSESSOR": "Outcomes assessor",
}

NOT_GIVEN = "Not given"
"""The label of a missing value, such as a trial with no phase."""


def label(labels: Mapping[str, str], code: str | None) -> str:
    """``code``'s display name, the code itself if it has none, or ``NOT_GIVEN`` for None."""
    if code is None:
        return NOT_GIVEN
    return labels.get(code, code)
