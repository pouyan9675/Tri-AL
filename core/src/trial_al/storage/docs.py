"""Raw source documents in ``trial_docs``, compressed with zstd (docs/design.md §6).

Study documents are small and alike, so each one is compressed on its own against a shared
dictionary trained on the data. That keeps any single document quick to read back, and
compresses about as well as one big archive would: real ClinicalTrials.gov documents
shrink to about a fifth of their size.

The first batch written with at least ``MIN_SAMPLES`` documents trains the dictionary, and
every later write uses it. ``doc_dicts`` keeps each dictionary for good, and each row of
``trial_docs`` names the one it was compressed with (NULL means none).
"""

import sys
from collections.abc import Callable, Sequence

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd

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
