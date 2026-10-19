"""Parts of a trial's text narrower than the full-text index's columns, checked in the text.

The index has one column for eligibility and one for outcomes, so it can say "warfarin" is in
a trial's eligibility criteria but not whether it's an inclusion or an exclusion criterion.
ClinicalTrials.gov's criteria are written under "Inclusion Criteria" and "Exclusion
Criteria" headings (both in 95% of trials, one of them in 2%; checked on 5,000), and
outcomes keep their kind. So the index finds the candidates, and their text, split into
these parts, is put into a small in-memory FTS5 table with the index's tokenizer, where the
same query decides: matching is exactly the index's, phrases and all. The same table makes
each hit's snippets.

Text before the first heading, and criteria without headings, belong to neither part.
"""

import re
import sqlite3
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from tri_al.storage import SNIPPET_MARKS, SnippetPart, docs, snippet_parts

_HEADING = re.compile(
    r"^[\W_]*(?:(?:key|main|major|general|other|additional|specific|principal)\s+)?"
    r"(inclusion|exclusion)(?:\s+(?:and|&)\s+(?:inclusion|exclusion))?\s+criteri(?:a|on)\b"
    r"[^\n]{0,60}$",
    re.IGNORECASE | re.MULTILINE,
)

COLUMNS = (
    "summary",
    "description",
    "eligibility",
    "inclusion",
    "exclusion",
    "outcomes",
    "primary_outcomes",
    "secondary_outcomes",
    "conditions",
    "interventions",
    "other_names",
)
"""The text table's columns: the index's (titles aside) and the narrower parts."""

TOKENS = 24
"""Words in a snippet."""


def split_eligibility(criteria: str | None) -> tuple[str | None, str | None]:
    """The inclusion and the exclusion criteria, each under its own heading."""
    if not criteria:
        return None, None
    parts: dict[str, list[str]] = {"inclusion": [], "exclusion": []}
    headings = list(_HEADING.finditer(criteria))
    ends = [heading.start() for heading in headings[1:]] + [len(criteria)] if headings else []
    for heading, end in zip(headings, ends, strict=True):
        if part := criteria[heading.end() : end].strip():
            parts[heading.group(1).lower()].append(part)
    return "\n".join(parts["inclusion"]) or None, "\n".join(parts["exclusion"]) or None


def outcome_text(outcomes: Iterable[docs.PackedOutcome], kind: str | None = None) -> str | None:
    """Outcome measures and descriptions as one text (of one ``kind``, if given)."""
    return (
        "\n".join(
            " ".join(part for part in (measure, description) if part)
            for outcome_kind, measure, description, _ in outcomes
            if kind is None or outcome_kind == kind
        ).strip()
        or None
    )


def text_row(
    text: docs.TrialText, names: Mapping[str, Sequence[str]] | None = None
) -> dict[str, str | None]:
    """A trial's row in the text table."""
    inclusion, exclusion = split_eligibility(text.eligibility_criteria)
    names = names or {}
    return {
        "summary": text.brief_summary,
        "description": text.description,
        "eligibility": text.eligibility_criteria,
        "inclusion": inclusion,
        "exclusion": exclusion,
        "outcomes": outcome_text(text.outcomes),
        "primary_outcomes": outcome_text(text.outcomes, "primary"),
        "secondary_outcomes": outcome_text(text.outcomes, "secondary"),
        "conditions": " ".join(names.get("conditions", ())) or None,
        "interventions": " ".join(names.get("interventions", ())) or None,
        "other_names": " ".join(names.get("other_names", ())) or None,
    }


@dataclass(frozen=True, slots=True)
class Snippet:
    field: str
    parts: tuple[SnippetPart, ...]


class TextTable:
    """A small in-memory FTS5 table per thread, with ``trials_fts``'s tokenizer.

    ``load`` fills it with some trials' rows; ``matching`` and ``snippets`` then ask it the
    same FTS5 queries the index answers, with the narrower columns besides.
    """

    def __init__(self) -> None:
        self._local = threading.local()
        self._lock = threading.Lock()
        self._conns: list[sqlite3.Connection] = []

    def _conn(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            with self._lock:
                self._conns.append(conn)
            self._local.conn = conn
        return conn

    def load(self, rows: Mapping[int, Mapping[str, str | None]]) -> sqlite3.Connection:
        """This thread's table holding just ``rows`` (by trial id; columns left out are empty)."""
        conn = self._conn()
        with conn:
            # A new table: deleting rows from an FTS5 table reads their text again.
            conn.execute("DROP TABLE IF EXISTS texts")
            conn.execute(
                f"CREATE VIRTUAL TABLE texts USING fts5({', '.join(COLUMNS)}, "
                "tokenize = 'porter unicode61 remove_diacritics 2')"
            )
            conn.executemany(
                f"INSERT INTO texts (rowid, {', '.join(COLUMNS)}) "
                f"VALUES (?, {', '.join('?' * len(COLUMNS))})",
                [(trial_id, *(row.get(c) for c in COLUMNS)) for trial_id, row in rows.items()],
            )
        return conn

    @staticmethod
    def matching(conn: sqlite3.Connection, expression: str) -> set[int]:
        """The loaded trials that ``expression`` (FTS5 syntax) matches."""
        return {
            rowid
            for (rowid,) in conn.execute(
                "SELECT rowid FROM texts WHERE texts MATCH ?", (expression,)
            )
        }

    @staticmethod
    def snippets(conn: sqlite3.Connection, expression: str) -> dict[int, tuple[SnippetPart, ...]]:
        """A snippet of each loaded trial that ``expression`` matches, from its best column."""
        return {
            rowid: snippet_parts(snippet)
            for rowid, snippet in conn.execute(
                "SELECT rowid, snippet(texts, -1, ?, ?, '…', ?) FROM texts WHERE texts MATCH ?",
                (*SNIPPET_MARKS, TOKENS, expression),
            )
        }

    def close(self) -> None:
        with self._lock:
            for conn in self._conns:
                conn.close()
            self._conns.clear()
