"""Term analyses (design §9): one condition or intervention, as a MeSH term, in depth.

The analysis page's Conditions and Interventions sections pick a MeSH term (the normalized
names; the registry's own are free text) and show its trials from many sides. A term's
trials are those tagged with it or with a narrower term, within the page's filter, and each
analysis compares them with the filter's other trials:

- **Activity** (``activity``): an overview; trials started per year by phase, with the
  term's share of all trials started (so a growing registry doesn't look like a growing
  field) and lead sponsors new to it; momentum, its share of newly posted trials against
  the year before, with an exact test; and active trials by when their main results are due.
- **Relations** (``related``): the conditions and interventions tagged with it more often
  than chance, by lift with a corrected exact test; their network, grouped into communities
  by modularity; and its pipeline, the other kind's terms by phase.
- **Outcomes** (``outcomes``): how often its trials stop early against the baseline phase by
  phase, and why (the stated reasons, sorted by keyword); how long they run and how long
  results take, as Kaplan-Meier curves; and how they're designed and whom they enroll, against
  a baseline standardized to its phases.
- **Meaning** (``semantic``): its sub-themes, clusters of its trials' vectors named by their
  distinctive words; and the terms whose trials read most alike.

Everything is computed from the API worker's ``TrialIndex`` (and the trial vectors) per
request, and cached by data version.
"""

from tri_al.terms.activity import Overview, Readouts, Timeline, overview, readouts, timeline
from tri_al.terms.outcomes import Attrition, Durations, Profile, attrition, durations, profile
from tri_al.terms.related import Pipeline, Related, pipeline, related
from tri_al.terms.scope import (
    Scope,
    TermCount,
    TermRef,
    TermTotals,
    as_of,
    find_term,
    lookup_terms,
    narrower_terms,
    scope_for,
    term_mask,
)
from tri_al.terms.semantic import Similar, TermVectorCache, Themes, similar, themes

__all__ = [
    "Attrition",
    "Durations",
    "Overview",
    "Pipeline",
    "Profile",
    "Readouts",
    "Related",
    "Scope",
    "Similar",
    "TermCount",
    "TermRef",
    "TermTotals",
    "TermVectorCache",
    "Themes",
    "Timeline",
    "as_of",
    "attrition",
    "durations",
    "find_term",
    "lookup_terms",
    "narrower_terms",
    "overview",
    "pipeline",
    "profile",
    "readouts",
    "related",
    "scope_for",
    "similar",
    "term_mask",
    "themes",
    "timeline",
]
