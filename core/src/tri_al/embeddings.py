"""Trial embeddings: one vector per trial, for clustering, similar trials and later search.

A trial's text (``trial_embedding_text``: title, official title, conditions, interventions
and brief summary, short fields first) goes through a Sentence Transformers bi-encoder,
``all-MiniLM-L6-v2`` by default, reading the first ``max_tokens`` (64) tokens in float16 on
a GPU: about 2,600 trials a second on Apple Silicon, so all 607k in under 5 minutes, with
nearest neighbours that share a MeSH condition as often as with a 768-dimension biomedical
model that took two hours.

Vectors are stored normalized, as little-endian float16, in ``trial_embeddings`` (one row
per trial) with the model that made them in ``embedding_models``. The model the pipeline
writes with is the *active* one (``meta``); a vector from any other model is stale, and the
backfill replaces it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import import_module
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt
from sqlalchemy import Connection, Select, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from tri_al.schema import TrialRecord
from tri_al.storage import docs
from tri_al.storage import tables as t

DEFAULT_ENGINE = "sentence-transformers"
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_MAX_TOKENS = 64
TEXT_VERSION = 1
"""Bump when :func:`trial_embedding_text` changes meaningfully."""

DTYPE = "float16"
"""How vectors are stored. Normalized vectors lose nothing that matters for cosine."""

ACTIVE_MODEL_KEY = "embeddings.model_id"
"""``meta``: the ``embedding_models.id`` the pipeline writes with."""

type Vectors = npt.NDArray[np.float32]


class EmbeddingError(Exception):
    """An embedding engine or its output can't be used."""


class EmbeddingEngine(Protocol):
    """A model that turns each text into one normalized vector."""

    name: str
    model: str
    max_tokens: int

    def encode(self, texts: Sequence[str]) -> Vectors:
        """One finite, normalized float32 vector per text, in order."""
        ...


@dataclass(slots=True)
class SentenceTransformerEngine:
    """A Sentence Transformers bi-encoder, loaded on first use.

    ``float16`` halves the work on a GPU (MPS or CUDA); on a CPU the model stays float32,
    which is faster there.
    """

    model: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS
    batch_size: int = 256
    device: str | None = None
    float16: bool = True
    name: str = field(default=DEFAULT_ENGINE, init=False)
    _encoder: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.model.startswith("cross-encoder/"):
            raise EmbeddingError(
                f"{self.model!r} is a cross-encoder: it scores query and document pairs and "
                f"makes no vectors to store; use a bi-encoder such as {DEFAULT_MODEL!r}"
            )

    def encode(self, texts: Sequence[str]) -> Vectors:
        if not texts:
            return np.empty((0, 0), np.float32)
        vectors = self.load().encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return validated(vectors, len(texts))

    def load(self) -> Any:
        """The model, loading it (and downloading it once) the first time."""
        if self._encoder is None:
            try:
                sentence_transformers = import_module("sentence_transformers")
                encoder = sentence_transformers.SentenceTransformer(self.model, device=self.device)
            except Exception as exc:
                raise EmbeddingError(
                    f"could not load the embedding model {self.model!r}: {exc}"
                ) from exc
            encoder.max_seq_length = self.max_tokens
            if self.float16 and encoder.device.type in ("mps", "cuda"):
                encoder.half()
            self._encoder = encoder
        return self._encoder


def create_engine(
    engine: str,
    model: str,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    batch_size: int = 256,
    device: str | None = None,
    float16: bool = True,
) -> EmbeddingEngine:
    """A configured engine; its model loads on first use."""
    if engine != DEFAULT_ENGINE:
        raise EmbeddingError(f"unknown embedding engine {engine!r}; use {DEFAULT_ENGINE!r}")
    return SentenceTransformerEngine(
        model=model, max_tokens=max_tokens, batch_size=batch_size, device=device, float16=float16
    )


def validated(vectors: Any, expected: int) -> Vectors:
    """``vectors`` as normalized float32 rows, after checking there's one finite row each."""
    result = np.array(vectors, dtype=np.float32, copy=True)
    if result.ndim != 2 or result.shape[0] != expected or result.shape[1] == 0:
        raise EmbeddingError(
            f"the embedding model returned shape {result.shape}; expected ({expected}, n)"
        )
    if not np.isfinite(result).all():
        raise EmbeddingError("the embedding model returned NaN or infinite values")
    norms = np.linalg.norm(result, axis=1)
    if not np.all(norms > 0):
        raise EmbeddingError("the embedding model returned an all-zero vector")
    result /= norms[:, np.newaxis]
    return result


# --- the text ---------------------------------------------------------------------------------


def trial_embedding_text(trial: TrialRecord) -> str:
    """The text a trial's vector stands for.

    Short, telling fields come first, since the model reads only the first ``max_tokens``
    tokens: at 64, about the title, conditions and interventions.
    """
    interventions = [
        " / ".join((intervention.name, *intervention.other_names))
        for intervention in trial.interventions
    ]
    return _compose_text(
        trial.title, trial.official_title, trial.conditions, interventions, trial.brief_summary
    )


def _compose_text(
    title: str,
    official_title: str | None,
    conditions: Sequence[str],
    interventions: Sequence[str],
    summary: str | None,
) -> str:
    parts: list[tuple[str, str | None]] = [
        ("Title", title),
        ("Official title", official_title),
        ("Conditions", "; ".join(conditions)),
        ("Interventions", "; ".join(interventions)),
        ("Summary", summary),
    ]
    return "\n".join(
        f"{label}: {value.strip()}" for label, value in parts if value and value.strip()
    )


@dataclass(frozen=True, slots=True)
class TrialText:
    trial_id: int
    content_hash: bytes | None  # the trial's version when its text was read
    text: str


def load_texts(
    conn: Connection, trial_ids: Sequence[int], decoder: docs.Decoder
) -> list[TrialText]:
    """The embedding text of ``trial_ids`` from storage, in a fixed number of queries.

    The same text ``trial_embedding_text`` makes from the trial's record.
    """
    if not trial_ids:
        return []
    ids = list(trial_ids)
    base = {
        row.id: row
        for row in conn.execute(
            select(
                t.trials.c.id, t.trials.c.title, t.trials.c.official_title, t.trials.c.content_hash
            ).where(t.trials.c.id.in_(ids))
        )
    }
    conditions: dict[int, list[str]] = {}
    for trial_id, name in conn.execute(
        select(t.trial_conditions.c.trial_id, t.conditions.c.name)
        .join(t.conditions)
        .where(t.trial_conditions.c.trial_id.in_(ids))
        .order_by(t.trial_conditions.c.trial_id, t.trial_conditions.c.position)
    ):
        conditions.setdefault(trial_id, []).append(name)
    aliases: dict[tuple[int, int], list[str]] = {}
    ia = t.intervention_aliases
    for trial_id, intervention_id, alias in conn.execute(
        select(ia.c.trial_id, ia.c.intervention_id, ia.c.alias)
        .where(ia.c.trial_id.in_(ids))
        .order_by(ia.c.trial_id, ia.c.intervention_id, ia.c.position)
    ):
        aliases.setdefault((trial_id, intervention_id), []).append(alias)
    interventions: dict[int, list[str]] = {}
    for trial_id, intervention_id, name in conn.execute(
        select(t.trial_interventions.c.trial_id, t.interventions.c.id, t.interventions.c.name)
        .join(t.interventions)
        .where(t.trial_interventions.c.trial_id.in_(ids))
        .order_by(t.trial_interventions.c.trial_id, t.trial_interventions.c.position)
    ):
        names = [name, *aliases.get((trial_id, intervention_id), ())]
        interventions.setdefault(trial_id, []).append(" / ".join(names))

    dictionaries: dict[int, bytes] = {}

    def dictionary(dict_id: int) -> bytes:
        if dict_id not in dictionaries:
            dictionaries[dict_id] = bytes(
                conn.execute(
                    select(t.doc_dicts.c.dict).where(t.doc_dicts.c.id == dict_id)
                ).scalar_one()
            )
        return dictionaries[dict_id]

    summaries: dict[int, str | None] = {}
    for trial_id, blob, dict_id in conn.execute(
        select(t.trial_text.c.trial_id, t.trial_text.c.text, t.trial_text.c.dict_id).where(
            t.trial_text.c.trial_id.in_(ids)
        )
    ):
        packed = decoder.decode(blob, dict_id, dictionary)
        summaries[trial_id] = docs.TrialText.unpack(packed).brief_summary

    return [
        TrialText(
            trial_id,
            base[trial_id].content_hash,
            _compose_text(
                base[trial_id].title,
                base[trial_id].official_title,
                conditions.get(trial_id, ()),
                interventions.get(trial_id, ()),
                summaries.get(trial_id),
            ),
        )
        for trial_id in ids
        if trial_id in base
    ]


# --- storage ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EmbeddingModel:
    id: int
    engine: str
    model: str
    max_tokens: int
    text_version: int
    dimensions: int
    dtype: str


def model_for(conn: Connection, engine: EmbeddingEngine, dimensions: int) -> EmbeddingModel:
    """The ``embedding_models`` row for ``engine``, added if new, and made the active one."""
    em = t.embedding_models
    key = {
        "engine": engine.name,
        "model": engine.model,
        "max_tokens": engine.max_tokens,
        "text_version": TEXT_VERSION,
        "dtype": DTYPE,
    }
    conn.execute(
        sqlite_insert(em)
        .values(**key, dimensions=dimensions, created_at=datetime.now(UTC))
        .on_conflict_do_nothing()
    )
    row = conn.execute(
        select(em).where(*(em.c[name] == value for name, value in key.items()))
    ).one()
    if row.dimensions != dimensions:
        raise EmbeddingError(
            f"{engine.model!r} made {dimensions}-dimension vectors, but its stored ones have "
            f"{row.dimensions}"
        )
    conn.execute(
        sqlite_insert(t.meta)
        .values(key=ACTIVE_MODEL_KEY, value=str(row.id))
        .on_conflict_do_update(index_elements=["key"], set_={"value": str(row.id)})
    )
    return _model(row)


def active_model(conn: Connection) -> EmbeddingModel | None:
    """The model the pipeline last wrote vectors with, if any."""
    model_id = conn.execute(
        select(t.meta.c.value).where(t.meta.c.key == ACTIVE_MODEL_KEY)
    ).scalar_one_or_none()
    if model_id is None:
        return None
    row = conn.execute(
        select(t.embedding_models).where(t.embedding_models.c.id == int(model_id))
    ).one_or_none()
    return None if row is None else _model(row)


def _model(row: Any) -> EmbeddingModel:
    return EmbeddingModel(
        row.id, row.engine, row.model, row.max_tokens, row.text_version, row.dimensions, row.dtype
    )


def store(
    conn: Connection, model: EmbeddingModel, trial_ids: Sequence[int], vectors: Vectors
) -> None:
    """Write (or replace) the vectors of ``trial_ids``, made by ``model``."""
    if len(trial_ids) != len(vectors):
        raise ValueError(f"{len(trial_ids)} trials but {len(vectors)} vectors")
    if not len(trial_ids):
        return
    if vectors.shape[1] != model.dimensions:
        raise EmbeddingError(f"vectors have {vectors.shape[1]} values, not {model.dimensions}")
    packed = np.ascontiguousarray(vectors, dtype="<f2")
    rows = [
        {"trial_id": int(trial_id), "model_id": model.id, "vector": packed[i].tobytes()}
        for i, trial_id in enumerate(trial_ids)
    ]
    statement = sqlite_insert(t.trial_embeddings)
    conn.execute(
        statement.on_conflict_do_update(
            index_elements=["trial_id"],
            set_={"model_id": statement.excluded.model_id, "vector": statement.excluded.vector},
        ),
        rows,
    )


def vectors_of(
    conn: Connection, model: EmbeddingModel, trials: Select[tuple[int]] | None = None
) -> tuple[list[int], Vectors]:
    """The trial ids that have a vector from ``model`` (among ``trials``) and the vectors.

    Ids ascending; the vectors as float32 rows.
    """
    te = t.trial_embeddings
    stmt = select(te.c.trial_id, te.c.vector).where(te.c.model_id == model.id)
    if trials is not None:
        stmt = stmt.where(te.c.trial_id.in_(trials))
    rows = conn.execute(stmt.order_by(te.c.trial_id)).all()
    ids = [row.trial_id for row in rows]
    if not rows:
        return ids, np.empty((0, model.dimensions), np.float32)
    matrix = np.frombuffer(b"".join(row.vector for row in rows), dtype="<f2")
    return ids, matrix.reshape(len(rows), model.dimensions).astype(np.float32)


def stale_trials(conn: Connection, model: EmbeddingModel, *, force: bool = False) -> list[int]:
    """Trials without a vector from ``model`` (every trial with ``force``), newest first.

    Newest by first posted date, so the recent trials that charts use are embedded first.
    """
    stmt = select(t.trials.c.id).order_by(
        t.trials.c.first_posted.desc().nulls_last(), t.trials.c.id.desc()
    )
    if not force:
        current = select(t.trial_embeddings.c.trial_id).where(
            t.trial_embeddings.c.model_id == model.id
        )
        stmt = stmt.where(t.trials.c.id.not_in(current))
    return list(conn.execute(stmt).scalars())


def unchanged(conn: Connection, texts: Iterable[TrialText]) -> list[TrialText]:
    """The ``texts`` whose trial is still the version they were read from."""
    texts = list(texts)
    if not texts:
        return []
    current = dict(
        conn.execute(
            select(t.trials.c.id, t.trials.c.content_hash).where(
                t.trials.c.id.in_([text.trial_id for text in texts])
            )
        ).all()
    )
    return [
        text
        for text in texts
        if text.trial_id in current and current[text.trial_id] == text.content_hash
    ]


__all__ = [
    "ACTIVE_MODEL_KEY",
    "DEFAULT_ENGINE",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MODEL",
    "DTYPE",
    "TEXT_VERSION",
    "EmbeddingEngine",
    "EmbeddingError",
    "EmbeddingModel",
    "SentenceTransformerEngine",
    "TrialText",
    "Vectors",
    "active_model",
    "create_engine",
    "load_texts",
    "model_for",
    "stale_trials",
    "store",
    "trial_embedding_text",
    "unchanged",
    "validated",
    "vectors_of",
]
