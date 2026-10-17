"""Hand-written TrialRecords for contract tests. The trials are made up.

Between them they cover every field, shared conditions and sponsors, a multi-phase trial,
a trial without locations, non-ASCII text, and a trial from a second registry. Each call
returns new objects, so tests can change them freely.
"""

import hashlib
import json
from datetime import date
from typing import Any

from trial_al.schema import Intervention, Location, MeshTerm, Outcome, Sponsor, TrialRecord


def raw_json(data: dict[str, Any]) -> bytes:
    """Compact JSON, the form storage returns ``TrialRecord.raw`` in."""
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()


def phase3_trial() -> TrialRecord:
    """Every field set: a recruiting phase 3 drug trial in three countries."""
    raw = raw_json(
        {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT90000001", "acronym": "TRAIL-AD"},
                "statusModule": {
                    "overallStatus": "RECRUITING",
                    "startDateStruct": {"date": "2024-03"},
                },
            },
            "hasResults": False,
        }
    )
    return TrialRecord(
        source="ctgov",
        source_id="NCT90000001",
        title="Remternetug in Early Alzheimer's Disease (TRAIL-AD)",
        official_title=(
            "A Phase 3, Randomized, Double-blind, Placebo-controlled Study of Remternetug in "
            "Participants With Early Symptomatic Alzheimer's Disease"
        ),
        status="RECRUITING",
        phase="PHASE3",
        study_type="INTERVENTIONAL",
        primary_purpose="TREATMENT",
        start_date=date(2024, 3, 1),
        primary_completion_date=date(2027, 6, 30),
        completion_date=date(2028, 1, 15),
        first_posted=date(2024, 2, 20),
        last_update=date(2026, 9, 30),
        enrollment=1800,
        enrollment_type="ESTIMATED",
        arms_count=2,
        has_results=False,
        min_age_days=50 * 365,
        max_age_days=85 * 365,
        sex="ALL",
        healthy_volunteers=False,
        brief_summary=(
            "This study tests whether monthly infusions of remternetug slow cognitive decline "
            "by clearing amyloid plaques in people with early Alzheimer's disease."
        ),
        description=(
            "Participants are randomized 1:1 to remternetug or placebo for 76 weeks. Amyloid "
            "PET scans measure plaque clearance at weeks 24, 52 and 76."
        ),
        eligibility_criteria=(
            "Inclusion Criteria:\n* MMSE score between 20 and 28\n* Amyloid positive on PET\n"
            "Exclusion Criteria:\n* Prior anti-amyloid therapy"
        ),
        outcomes=[
            Outcome(
                "primary",
                "Change from baseline in CDR-SB",
                "Clinical Dementia Rating Sum of Boxes; higher is worse.",
                "Baseline, week 76",
            ),
            Outcome("secondary", "Change in ADAS-Cog13", None, "Week 76"),
            Outcome("other", "Plasma p-tau217 concentration"),
        ],
        conditions=["Alzheimer Disease", "Mild Cognitive Impairment"],
        mesh_terms=[
            MeshTerm("D000544", "Alzheimer Disease", "condition"),
            MeshTerm("D060825", "Cognitive Dysfunction", "condition"),
            MeshTerm("D003704", "Dementia", "condition", ancestor=True),
            MeshTerm("D000911", "Antibodies, Monoclonal", "intervention", ancestor=True),
        ],
        interventions=[
            Intervention("Remternetug", "DRUG", ("TAL-0451", "LY-TEST-1")),
            Intervention("Placebo", "DRUG"),
        ],
        sponsors=[
            Sponsor("Tri-AL Test Pharma", "lead", "INDUSTRY"),
            Sponsor("National Institute on Aging (NIA)", "collaborator", "NIH"),
        ],
        countries=["US", "CA", "DE"],
        locations=[
            Location(
                "Memory Clinic of Boston",
                "Boston",
                "Massachusetts",
                "US",
                "RECRUITING",
                42.3601,
                -71.0589,
            ),
            Location(
                "Toronto Brain Health Centre",
                "Toronto",
                "Ontario",
                "CA",
                "NOT_YET_RECRUITING",
                43.6532,
                -79.3832,
            ),
            Location("Uniklinik Köln", "Köln", None, "DE", "RECRUITING", 50.9375, 6.9603),
        ],
        raw=raw,
        content_hash=hashlib.blake2b(raw, digest_size=16).digest(),
    )


def completed_behavioral_trial() -> TrialRecord:
    """Phase 2/3, completed with results, no locations; shares a condition and a sponsor."""
    return TrialRecord(
        source="ctgov",
        source_id="NCT90000002",
        title="Aerobic Exercise and Memory in Older Adults at Risk of Dementia",
        status="COMPLETED",
        phase="PHASE2_PHASE3",
        study_type="INTERVENTIONAL",
        primary_purpose="PREVENTION",
        start_date=date(2019, 9, 1),
        completion_date=date(2023, 4, 1),
        first_posted=date(2019, 8, 12),
        last_update=date(2024, 1, 5),
        enrollment=312,
        enrollment_type="ACTUAL",
        arms_count=3,
        has_results=True,
        min_age_days=65 * 365,
        sex="ALL",
        healthy_volunteers=True,
        brief_summary="Supervised treadmill walking three times a week for one year.",
        outcomes=[Outcome("primary", "Delayed recall on the RAVLT", time_frame="12 months")],
        conditions=["Alzheimer Disease", "Aging"],
        mesh_terms=[MeshTerm("D000544", "Alzheimer Disease", "condition")],
        interventions=[Intervention("Aerobic exercise", "BEHAVIORAL", ("Treadmill walking",))],
        sponsors=[Sponsor("National Institute on Aging (NIA)", "lead", "NIH")],
    )


def minimal_trial() -> TrialRecord:
    """Only the required fields."""
    return TrialRecord(source="ctgov", source_id="NCT90000003", title="Café Study of Sleep")


def other_registry_trial() -> TrialRecord:
    """A trial from another registry, outside the US, with a withdrawn status."""
    return TrialRecord(
        source="isrctn",
        source_id="ISRCTN00000001",
        title="Music Therapy for Agitation in Care Homes",
        status="WITHDRAWN",
        phase="NA",
        study_type="INTERVENTIONAL",
        conditions=["Agitation"],
        interventions=[Intervention("Group music therapy", "BEHAVIORAL")],
        sponsors=[Sponsor("Université Claude Bernard Lyon 1", "lead", "OTHER")],
        countries=["FR", "GB"],
        locations=[Location("Maison des Aînés", "Lyon", None, "FR")],
    )


def sample_trials() -> list[TrialRecord]:
    return [
        phase3_trial(),
        completed_behavioral_trial(),
        minimal_trial(),
        other_registry_trial(),
    ]
