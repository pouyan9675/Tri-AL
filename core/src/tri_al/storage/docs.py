"""Compressed blobs: raw documents in ``trial_docs`` and text in ``trial_text`` (design §6).

Study documents are small and alike, so each one is compressed on its own with zstd against
a shared dictionary trained on the data. That keeps any single document quick to read
back, and compresses about as well as one big archive would: real ClinicalTrials.gov
documents shrink to about a fifth of their size, and their text to under a third.

The first batch written with at least ``MIN_SAMPLES`` blobs of a kind trains that kind's
dictionary, and every later write uses it. ``doc_dicts`` keeps each dictionary for good,
with its ``kind`` (``DOC`` or ``TEXT``), and each compressed row names the one it was
compressed with (NULL means none).
"""

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import orjson

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd

DOC = "doc"
"""``doc_dicts.kind`` of dictionaries for raw documents."""

TEXT = "text"
"""``doc_dicts.kind`` of dictionaries for trial text."""

LEVEL = 3
"""zstd's default level: about 450 MB/s with a dictionary, within a few percent of level 9."""

DICT_SIZE = 110 * 1024
"""zstd's default dictionary size; larger ones barely helped on real documents."""

MIN_SAMPLES = 1_000
"""Fewer documents than this are too few to train on; they're compressed without one."""

MAX_SAMPLES = 5_000
"""Documents a dictionary is trained on, at most (taken from the start of the batch)."""


def train(samples: Sequence[bytes]) -> bytes | None:
    """A dictionary trained on ``samples``, or None if there are too few to train on."""
    if len(samples) < MIN_SAMPLES:
        return None
    try:
        return zstd.train_dict(samples[:MAX_SAMPLES], DICT_SIZE).dict_content
    except zstd.ZstdError:
        # zstd refuses samples it can't learn from, such as identical documents.
        return None


class Encoder:
    """Compresses documents with one dictionary (``dict_id``), or with none."""

    def __init__(self, dict_id: int | None = None, content: bytes | None = None) -> None:
        self.dict_id = dict_id
        zstd_dict = None if content is None else zstd.ZstdDict(content).as_digested_dict
        self._compressor = zstd.ZstdCompressor(LEVEL, zstd_dict=zstd_dict)

    def encode(self, raw: bytes) -> bytes:
        return self._compressor.compress(raw, zstd.ZstdCompressor.FLUSH_FRAME)


class Decoder:
    """Decompresses documents, keeping each dictionary once it has been loaded."""

    def __init__(self) -> None:
        self._dicts: dict[int, zstd.ZstdDict] = {}

    def decode(self, doc: bytes, dict_id: int | None, load: Callable[[int], bytes]) -> bytes:
        """``doc`` decompressed; ``load(dict_id)`` fetches a dictionary not seen before."""
        if dict_id is None:
            return zstd.decompress(doc)
        zstd_dict = self._dicts.get(dict_id)
        if zstd_dict is None:
            zstd_dict = self._dicts[dict_id] = zstd.ZstdDict(load(dict_id))
        return zstd.decompress(doc, zstd_dict=zstd_dict.as_digested_dict)


type PackedOutcome = tuple[str, str, str | None, str | None]  # kind, measure, description, time
type PackedArm = tuple[str, str | None, str | None, tuple[str, ...]]  # label, type, ..., names


@dataclass(frozen=True, slots=True)
class TrialText:
    """A trial's long text, as ``trial_text`` keeps it (one compressed blob per trial).

    Besides the text the full-text index covers (summary, description, eligibility and
    outcomes), it holds what only the trial's page shows: keywords, arms, intervention
    descriptions (by intervention name), who is masked and why the trial stopped. Blobs written
    before migrations 5 and 6 have only the first four or eight parts; the rest read as empty.
    """

    brief_summary: str | None = None
    description: str | None = None
    eligibility_criteria: str | None = None
    outcomes: tuple[PackedOutcome, ...] = ()
    keywords: tuple[str, ...] = ()
    arms: tuple[PackedArm, ...] = ()
    intervention_descriptions: tuple[tuple[str, str], ...] = ()  # name, description
    masked_roles: tuple[str, ...] = ()
    why_stopped: str | None = None

    def pack(self) -> bytes:
        """The text as compact JSON, ready to compress."""
        return orjson.dumps(
            [
                self.brief_summary,
                self.description,
                self.eligibility_criteria,
                [list(outcome) for outcome in self.outcomes],
                list(self.keywords),
                [
                    [label, type_, description, list(names)]
                    for label, type_, description, names in self.arms
                ],
                [list(pair) for pair in self.intervention_descriptions],
                list(self.masked_roles),
                self.why_stopped,
            ]
        )

    @classmethod
    def unpack(cls, data: bytes) -> "TrialText":
        summary, description, eligibility, outcomes, *details = orjson.loads(data)
        keywords, arms, interventions, masked, why_stopped = [*details, [], [], [], [], None][:5]
        return cls(
            summary,
            description,
            eligibility,
            tuple(_outcome(o) for o in outcomes),
            tuple(keywords),
            tuple(_arm(arm) for arm in arms),
            tuple((name, text) for name, text in interventions),
            tuple(masked),
            why_stopped,
        )


def _outcome(row: list[Any]) -> PackedOutcome:
    kind, measure, description, time_frame = row
    return (kind, measure, description, time_frame)


def _arm(row: list[Any]) -> PackedArm:
    label, type_, description, names = row
    return (label, type_, description, tuple(names))
