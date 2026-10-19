"""What an advanced search asks: words in chosen parts of a trial, and whom and how it studies.

Each text field takes a small search syntax, read by ``Words.parse``:

- ``amyloid tau``: every word (in any order)
- ``"amyloid PET"``: the words together, in this order; ``ADAS-Cog`` is the phrase "ADAS Cog"
- ``"amyloid PET"~5``: the words within 5 words of each other, in any order
- ``donepezil OR rivastigmine``: either one
- ``anticoag*``: a word starting with ``anticoag`` (3 letters at least before the ``*``)
- ``-warfarin``, ``-"open label"``: not this

Words are matched the way the full-text index matches them (Porter stems, any case, accents
ignored), since the syntax becomes an FTS5 query restricted to the field's columns. Nothing
typed reaches FTS5 as syntax: words are quoted, and only the operators above are written.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal, get_args

from tri_al.filters import IntRange

type TextField = Literal[
    "text",
    "title",
    "condition",
    "intervention",
    "summary",
    "eligibility",
    "inclusion",
    "exclusion",
    "outcome",
    "primary_outcome",
    "secondary_outcome",
]

TEXT_FIELDS: tuple[TextField, ...] = get_args(TextField.__value__)

FIELD_COLUMNS: dict[TextField, tuple[str, ...]] = {
    "text": (),  # every column
    "title": ("title", "official_title"),
    "condition": ("conditions",),
    "intervention": ("interventions", "other_names"),
    "summary": ("summary", "description"),
    "eligibility": ("eligibility",),
    "inclusion": ("eligibility",),
    "exclusion": ("eligibility",),
    "outcome": ("outcomes",),
    "primary_outcome": ("outcomes",),
    "secondary_outcome": ("outcomes",),
}
"""The ``trials_fts`` columns each field searches."""

SECTION_FIELDS: dict[TextField, str] = {
    "inclusion": "inclusion",
    "exclusion": "exclusion",
    "primary_outcome": "primary_outcomes",
    "secondary_outcome": "secondary_outcomes",
}
"""Fields narrower than an index column, and the part of the text they check
(``tri_al.advanced.sections``): the index finds candidates, the text decides."""

type Sex = Literal["FEMALE", "MALE"]

MIN_PREFIX = 3
"""Letters a word needs before ``*``: FTS5 expands a prefix to every word starting with it."""

MAX_NEAR = 50

_TOKEN = re.compile(r'(-?)"([^"]*)"?(?:~(\d+))?|(\S+)')
_WORD = re.compile(r"\w+")


@dataclass(frozen=True, slots=True)
class Term:
    """One word, or several together: a phrase, or words near one another."""

    words: tuple[str, ...]
    prefix: bool = False  # the last word may go on: ``anticoag*``
    near: int | None = None  # within this many words of each other, in any order

    def fts(self) -> str:
        """The term in FTS5 syntax; every word is quoted, so it's never read as syntax."""
        if self.near is not None:
            return f"NEAR({' '.join(f'"{word}"' for word in self.words)}, {self.near})"
        return f'"{" ".join(self.words)}"' + ("*" if self.prefix else "")

    def __str__(self) -> str:
        """The term as it would be typed."""
        text = " ".join(self.words)
        if len(self.words) > 1 or self.near is not None:
            text = f'"{text}"'
        if self.near is not None:
            text += f"~{self.near}"
        return text + ("*" if self.prefix else "")


@dataclass(frozen=True, slots=True)
class Words:
    """One field's text: groups that must all match (each by any of its terms), and terms
    that mustn't."""

    groups: tuple[tuple[Term, ...], ...] = ()
    excluded: tuple[Term, ...] = ()

    @classmethod
    def parse(cls, text: str) -> "Words":
        groups: list[list[Term]] = []
        excluded: list[Term] = []
        join = False  # the last token was OR
        for match in _TOKEN.finditer(text):
            negated, quoted, near, bare = match.groups()
            if bare is not None:
                if bare == "OR":
                    join = bool(groups)
                    continue
                negated = "-" if bare.startswith("-") and len(bare) > 1 else ""
                term = _bare(bare[1:] if negated else bare)
            else:
                term = _quoted(quoted, near)
            if term is None:
                continue
            if negated:
                excluded.append(term)
            elif join:
                groups[-1].append(term)
            else:
                groups.append([term])
            join = False
        return cls(
            tuple(tuple(dict.fromkeys(group)) for group in dict.fromkeys(map(tuple, groups))),
            tuple(dict.fromkeys(excluded)),
        )

    @property
    def is_empty(self) -> bool:
        return not self.groups and not self.excluded

    def positive(self) -> str | None:
        """What must match, in FTS5 syntax; None if nothing must."""
        if not self.groups:
            return None
        return " AND ".join(
            group[0].fts() if len(group) == 1 else f"({' OR '.join(t.fts() for t in group)})"
            for group in self.groups
        )

    def negative(self) -> str | None:
        """What mustn't match (any of it), in FTS5 syntax; None if nothing is excluded."""
        if not self.excluded:
            return None
        return " OR ".join(term.fts() for term in self.excluded)

    def expression(self) -> str | None:
        """The whole field in FTS5 syntax, when something must match."""
        positive, negative = self.positive(), self.negative()
        if positive is None:
            return None
        return positive if negative is None else f"({positive}) NOT ({negative})"


def _bare(token: str) -> Term | None:
    prefix = token.endswith("*")
    words = tuple(_WORD.findall(token))
    if not words:
        return None
    return Term(words, prefix=prefix and len(words[-1]) >= MIN_PREFIX)


def _quoted(text: str, near: str | None) -> Term | None:
    prefix = text.rstrip().endswith("*")
    words = tuple(_WORD.findall(text))
    if not words:
        return None
    if near is not None and len(words) > 1:
        return Term(words, near=min(max(int(near), 1), MAX_NEAR))
    return Term(words, prefix=prefix and len(words[-1]) >= MIN_PREFIX)


def column_filter(columns: Iterable[str], expression: str) -> str:
    """``expression`` restricted to ``columns`` (all of them if none)."""
    columns = tuple(columns)
    return f"({expression})" if not columns else f"{{{' '.join(columns)}}} : ({expression})"


@dataclass(frozen=True, slots=True)
class Near:
    """Trials with a site within ``km`` of a point."""

    lat: float
    lon: float
    km: float

    def __post_init__(self) -> None:
        if not (-90 <= self.lat <= 90 and -180 <= self.lon <= 180):
            raise ValueError(f"{self.lat},{self.lon} isn't a latitude and longitude")
        if not 0 < self.km <= 20_000:
            raise ValueError("the distance must be between 0 and 20,000 km")

    @classmethod
    def parse(cls, point: str, km: float) -> "Near":
        """``43.7,-79.4`` and a distance."""
        try:
            lat, lon = (float(part) for part in point.split(","))
        except ValueError:
            raise ValueError(f"{point!r} isn't `latitude,longitude`") from None
        return cls(round(lat, 4), round(lon, 4), km)


@dataclass(frozen=True, slots=True)
class AdvancedQuery:
    """An advanced search, besides the page's ``TrialFilter``: frozen and normalized, so equal
    queries are equal cache keys."""

    text: tuple[tuple[TextField, Words], ...] = ()  # in ``TEXT_FIELDS`` order, none empty
    ages: IntRange | None = None  # years: trials that take someone of an age in the range
    sex: Sex | None = None  # trials that take this sex (or both, or don't say)
    healthy_volunteers: bool | None = None
    allocation: tuple[str, ...] = ()
    masking: tuple[str, ...] = ()
    intervention_model: tuple[str, ...] = ()
    primary_purpose: tuple[str, ...] = ()
    placebo: bool | None = None  # an intervention named placebo
    near: Near | None = None
    _texts: dict[TextField, Words] = field(init=False, repr=False, compare=False, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_texts", dict(self.text))
        for name in ("allocation", "masking", "intervention_model", "primary_purpose"):
            object.__setattr__(self, name, tuple(sorted(set(getattr(self, name)))))
        if self.ages is not None and (self.ages.low or 0) < 0:
            raise ValueError("ages can't be negative")

    @classmethod
    def make(cls, texts: Mapping[TextField, str | None], **fields: object) -> "AdvancedQuery":
        """A query from each text field's typed text (empty ones are left out)."""
        parsed = ((name, Words.parse(text)) for name in TEXT_FIELDS if (text := texts.get(name)))
        return cls(tuple((name, words) for name, words in parsed if not words.is_empty), **fields)  # type: ignore[arg-type]

    def words(self, name: TextField) -> Words | None:
        return self._texts.get(name)

    @property
    def sections(self) -> tuple[tuple[TextField, Words], ...]:
        """Text fields that need the text itself checked (``SECTION_FIELDS``)."""
        return tuple((name, words) for name, words in self.text if name in SECTION_FIELDS)

    def index_expressions(self) -> tuple[str | None, str | None]:
        """What the full-text index must match, and what it mustn't, in FTS5 syntax.

        A section field asks its column for what must match; what it excludes can only be
        told from the text (a word may be in the inclusion criteria but not the exclusion).
        """
        positive: list[str] = []
        negative: list[str] = []
        for name, words in self.text:
            columns = FIELD_COLUMNS[name]
            if (expression := words.positive()) is not None:
                positive.append(column_filter(columns, expression))
            if name not in SECTION_FIELDS and (expression := words.negative()) is not None:
                negative.append(column_filter(columns, expression))
        return (
            " AND ".join(positive) or None,
            " OR ".join(negative) or None,
        )

    @property
    def has_text(self) -> bool:
        return bool(self.text)

    @property
    def is_empty(self) -> bool:
        return self == EMPTY_QUERY


EMPTY_QUERY = AdvancedQuery()
