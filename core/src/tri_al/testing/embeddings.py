"""A stand-in embedding model for tests: no download, instant, deterministic."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from tri_al.embeddings import Vectors, validated


@dataclass
class FakeEmbeddingEngine:
    """Vectors from each text's length and bytes, so different texts get different vectors.

    ``calls`` records how many texts each call encoded; ``during(n)`` runs inside call ``n``,
    to change the database while a batch is being embedded.
    """

    name: str = "fake"
    model: str = "tiny"
    max_tokens: int = 64
    calls: list[int] = field(default_factory=list)
    during: Callable[[int], None] | None = None

    def encode(self, texts: Sequence[str]) -> Vectors:
        self.calls.append(len(texts))
        if self.during is not None:
            self.during(len(self.calls))
        rows = [[len(text), sum(text.encode()) % 101 + 1, 7] for text in texts]
        return validated(rows, len(texts))
