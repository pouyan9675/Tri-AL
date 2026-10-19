"""The annotation task: mark the terms of each label in a trial's text.

The text is cut into pieces of about ``[ai.annotation] chunk_chars`` characters between
paragraphs, and each piece goes to the model on its own, several at once. The model lists
the terms it finds as JSON held to a schema (each term with one of the labels); each term is
then looked up in the piece, so only text that is really there gets marked, at every place
it appears. Small models (0.8B parameters) were measured on real trials to do best this way:
one request per piece with all labels at once, and an example made from the labels' own
examples (docs/design.md §15, decision 27).
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import cycle
from typing import Any

from tri_al.ai.models import ChatModel, Message
from tri_al.config import LABEL_COLORS, AnnotationLabel

PROMPT_VERSION = 1
"""Bump when the prompt or the grounding changes, so remembered answers are dropped."""

MAX_TERMS = 60
"""Terms a piece may yield; a small model sometimes lists every word instead."""

MAX_WORDS = 8
"""Longer "terms" are clauses or sentences, not names."""

GENERIC = frozenset(
    {
        *("patient", "patients", "participant", "participants", "subject", "subjects"),
        *("people", "person", "persons", "adult", "adults", "group", "groups"),
        *("study", "studies", "trial", "trials", "treatment", "treatments", "therapy"),
        *("safety", "efficacy", "data", "the", "and", "or", "of"),
    }
)
"""Words a label never stands for alone, however a small model labels them."""

APOSTROPHES = "['\u2019]"
"""Registry text has both kinds of apostrophe, and a model may copy either."""

RULES = """Rules:
- Only short names and terms (1 to 6 words), never whole sentences or clauses.
- Copy each term exactly as it appears in the text.
- Skip generic words such as patients, participants, study, safety, efficacy, treatment.
- Skip anything that does not clearly fit a label. When unsure, leave it out."""


@dataclass(frozen=True, slots=True)
class Span:
    """Characters ``start:end`` of the text are a term of ``label``."""

    start: int
    end: int
    label: str


@dataclass(frozen=True, slots=True)
class Chunk:
    index: int
    start: int  # where it starts in the whole text
    text: str


def normalize(text: str) -> str:
    """The text spans refer to: line breaks as ``\\n``, as the front end reads it too."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def colored(labels: Sequence[AnnotationLabel]) -> list[AnnotationLabel]:
    """``labels`` with a colour each: their own, or the next one no label has taken."""
    taken = {label.color for label in labels if label.color}
    free = cycle([color for color in LABEL_COLORS if color not in taken] or LABEL_COLORS)
    return [
        label if label.color else label.model_copy(update={"color": next(free)}) for label in labels
    ]


# --- splitting ----------------------------------------------------------------------------

_BREAKS = (
    re.compile(r"\n[ \t]*\n\s*"),  # paragraphs
    re.compile(r"\n"),  # lines
    re.compile(r"(?<=[.!?;:])\s+"),  # sentences
    re.compile(r"\s+"),  # words
)


def split(text: str, size: int) -> list[Chunk]:
    """Pieces of at most ``size`` characters, cut between paragraphs where possible.

    Neighbouring paragraphs share a piece while they fit; a longer paragraph is cut between
    lines, then sentences, then words. Pieces keep the text between their parts as it is.
    """
    parts = [(s, e) for s, e in _pieces(text, 0, len(text), size, 0) if text[s:e].strip()]
    spans: list[tuple[int, int]] = []
    for start, end in parts:
        if spans and end - spans[-1][0] <= size:
            spans[-1] = (spans[-1][0], end)
        else:
            spans.append((start, end))
    return [Chunk(index, start, text[start:end]) for index, (start, end) in enumerate(spans)]


def _pieces(text: str, start: int, end: int, size: int, level: int) -> list[tuple[int, int]]:
    if end - start <= size:
        return [(start, end)]
    if level == len(_BREAKS):
        return [(at, min(at + size, end)) for at in range(start, end, size)]
    out: list[tuple[int, int]] = []
    at = start
    for match in _BREAKS[level].finditer(text, start, end):
        if match.start() > at:
            out.extend(_pieces(text, at, match.start(), size, level + 1))
        at = match.end()
    if at < end:
        out.extend(_pieces(text, at, end, size, level + 1))
    return out


# --- prompting ----------------------------------------------------------------------------


def system_prompt(labels: Sequence[AnnotationLabel]) -> str:
    lines = [
        "You annotate clinical trial text.",
        "List every term in the text that belongs to one of these labels. "
        "Copy each term exactly as written in the text.",
        "",
        "Labels:",
    ]
    for label in labels:
        line = f"- {label.name}"
        if label.description:
            line += f": {label.description}"
        if label.examples:
            line += f" (for example {', '.join(label.examples)})"
        lines.append(line)
    lines += ["", RULES]
    example = _example(labels)
    if example is not None:
        text, answer = example
        lines += ["", f"Example text: {text}", f"Example answer: {json.dumps(answer)}"]
    lines += ["", "Answer with JSON only."]
    return "\n".join(lines)


def _example(labels: Sequence[AnnotationLabel]) -> tuple[str, dict[str, Any]] | None:
    """A worked example from the labels' own examples, so it fits any set of labels.

    It shows the answer's shape and that terms are short; without one, a small model
    labelled whole clauses, and once every single word of a paragraph.
    """
    firsts = [(label.examples[0], label.name) for label in labels if label.examples]
    seconds = [(label.examples[1], label.name) for label in labels if len(label.examples) > 1]
    if not firsts:
        return None
    text = "The participants in this study visit the clinic every month. Topics: "
    text += ", ".join(term for term, _ in firsts) + "."
    if seconds:
        text += " Also " + " and ".join(term for term, _ in seconds) + "."
    entities = [{"text": term, "label": name} for term, name in firsts + seconds]
    return text, {"entities": entities}


def answer_schema(labels: Sequence[AnnotationLabel]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "maxItems": MAX_TERMS,
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "label": {"type": "string", "enum": [label.name for label in labels]},
                    },
                    "required": ["text", "label"],
                },
            }
        },
        "required": ["entities"],
    }


def messages(labels: Sequence[AnnotationLabel], text: str) -> list[Message]:
    return [
        {"role": "system", "content": system_prompt(labels)},
        {"role": "user", "content": text},
    ]


def max_tokens(text: str) -> int:
    """Room for every term a piece could hold, and no more: a looping model stops sooner."""
    return 200 + len(text) // 2


# --- reading the answer -------------------------------------------------------------------

_ENTITY = re.compile(
    r'\{\s*"text"\s*:\s*("(?:[^"\\]|\\.)*")\s*,\s*"label"\s*:\s*("(?:[^"\\]|\\.)*")\s*\}'
)


def parse(reply: str, labels: Sequence[AnnotationLabel]) -> list[tuple[str, str]]:
    """The (term, label) pairs in the model's reply, with label names as configured.

    A reply cut short (the model ran out of tokens) still yields the terms it finished.
    """
    names = {label.name.casefold(): label.name for label in labels}
    pairs: list[tuple[Any, Any]]
    try:
        data = json.loads(_unfenced(reply))
        items = data["entities"] if isinstance(data, dict) else data
        pairs = [(item.get("text"), item.get("label")) for item in items if isinstance(item, dict)]
    except (ValueError, KeyError, TypeError, AttributeError):
        pairs = [(json.loads(t), json.loads(lb)) for t, lb in _ENTITY.findall(reply)]
    out = []
    for term, label in pairs[:MAX_TERMS]:
        if isinstance(term, str) and isinstance(label, str) and label.casefold() in names:
            out.append((term, names[label.casefold()]))
    return out


def _unfenced(reply: str) -> str:
    reply = reply.strip()
    if reply.startswith("```"):
        reply = reply.split("\n", 1)[-1].rsplit("```", 1)[0]
    return reply


def ground(chunk: Chunk, found: Sequence[tuple[str, str]]) -> list[Span]:
    """Where each term is in the piece, as spans of the whole text.

    A term marks every place it appears, matched without regard to case, line breaks or the
    kind of apostrophe, and only as whole words. Terms that aren't in the piece (a model
    that "corrected" a spelling) are dropped, as are generic words and clauses. Overlaps go
    to the longer term, then the earlier one.
    """
    candidates: list[tuple[int, int, str]] = []
    for term, label in found:
        pattern = _pattern(term, label)
        if pattern is None:
            continue
        for match in pattern.finditer(chunk.text):
            candidates.append((match.start(), match.end(), label))
    candidates.sort(key=lambda c: (c[0] - c[1], c[0]))  # longest first, then earliest
    taken: list[tuple[int, int, str]] = []
    for start, end, label in candidates:
        if all(end <= s or start >= e for s, e, _ in taken):
            taken.append((start, end, label))
    return [Span(chunk.start + s, chunk.start + e, label) for s, e, label in sorted(taken)]


def _pattern(term: str, label: str) -> re.Pattern[str] | None:
    term = term.strip().strip("\"'\u201c\u201d.,;:")
    words = term.split()
    key = term.casefold()
    if len(term) < 2 or not words or len(words) > MAX_WORDS:
        return None
    if key in GENERIC or key == label.casefold():
        return None
    body = r"\s+".join(re.escape(word) for word in words)
    body = re.sub(APOSTROPHES, APOSTROPHES, body)
    left = r"(?<!\w)" if re.match(r"\w", term) else ""
    right = r"(?!\w)" if re.search(r"\w$", term) else ""
    return re.compile(left + body + right, re.IGNORECASE)


def annotate_chunk(model: ChatModel, labels: Sequence[AnnotationLabel], chunk: Chunk) -> list[Span]:
    """Ask ``model`` for the terms in one piece, and find them in it."""
    reply = model.chat(
        messages(labels, chunk.text),
        schema=answer_schema(labels),
        max_tokens=max_tokens(chunk.text),
        thinking=False,  # thinking takes seconds and the token budget, for no better terms
    )
    return ground(chunk, parse(reply, labels))
