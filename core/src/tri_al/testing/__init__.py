"""Contract test suites that every implementation of a core interface must pass (design §5.6).

Importing this package needs pytest: install ``tri-al[testing]``.
"""

from tri_al.testing.embeddings import FakeEmbeddingEngine
from tri_al.testing.source import SourceContract
from tri_al.testing.sources import FakeSource, fake_study
from tri_al.testing.storage import StorageContract

__all__ = [
    "FakeEmbeddingEngine",
    "FakeSource",
    "SourceContract",
    "StorageContract",
    "fake_study",
]
