"""Advanced search (design §9): trials found by what chosen parts of them say, whom they take,
how they're designed and where they run, within the page's filter.

- **Text by field** (``query``): words in the title, conditions, interventions, summary,
  eligibility criteria or outcomes, with phrases, near, any-of, prefixes and exclusions, as
  one FTS5 query on the full-text index with each field restricted to its columns.
- **Narrower parts** (``sections``): inclusion or exclusion criteria, and primary or
  secondary outcomes, which the index can't tell apart, checked in the text of the newest
  candidates.
- **Participants and design**: the age someone is, sex, healthy volunteers, allocation,
  masking, model, purpose and placebo, from the trial index.
- **Places** (``places``): trials with a site within a distance of a city, from the sites'
  own coordinates.

Results are ordered by relevance (BM25, as search ranks), distance, or the trial list's sorts
(``results``), and cached by data version like the other analyses.
"""

from tri_al.advanced.places import NearestSite, Place, SiteCache, Sites
from tri_al.advanced.query import (
    EMPTY_QUERY,
    SECTION_FIELDS,
    TEXT_FIELDS,
    AdvancedQuery,
    Near,
    Sex,
    Term,
    TextField,
    Words,
)
from tri_al.advanced.results import (
    SECTION_CANDIDATES,
    Found,
    Hit,
    Order,
    SectionCheck,
    default_order,
    describe,
    find,
    participant_mask,
)
from tri_al.advanced.sections import Snippet, TextTable, split_eligibility

__all__ = [
    "EMPTY_QUERY",
    "SECTION_CANDIDATES",
    "SECTION_FIELDS",
    "TEXT_FIELDS",
    "AdvancedQuery",
    "Found",
    "Hit",
    "Near",
    "NearestSite",
    "Order",
    "Place",
    "SectionCheck",
    "Sex",
    "SiteCache",
    "Sites",
    "Snippet",
    "Term",
    "TextField",
    "TextTable",
    "Words",
    "default_order",
    "describe",
    "find",
    "participant_mask",
    "split_eligibility",
]
