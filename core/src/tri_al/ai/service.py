"""What an API worker runs AI tasks with: the live ``[ai]`` settings, the backends, a cache."""

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

import orjson

from tri_al.ai.annotate import PROMPT_VERSION, Span, annotate_chunk, colored, normalize, split
from tri_al.ai.models import ChatModel, ModelBackend, ModelError, ModelInfo
from tri_al.ai.openai import OpenAICompatible
from tri_al.config import AiConfig, ConfigError, load_config

log = logging.getLogger(__name__)

CACHE_SIZE = 256
"""Annotated texts each API worker remembers, so showing one again costs nothing."""

type Event = dict[str, Any]


class AiService:
    """The AI engine as the API sees it.

    The settings are ``[ai]`` in ``tri-al.toml``, read again whenever the file changes, so a
    change made in the app (or by hand) applies to the next request in every API worker,
    with no restart. ``TRI_AL_AI__*`` variables still override the file.
    """

    def __init__(
        self,
        config: AiConfig,
        config_path: Path,
        backends: Mapping[str, ModelBackend] | None = None,
    ) -> None:
        self._config = config
        self._path = config_path
        self._seen = self._stamp()
        self._backends: dict[str, ModelBackend] = {"openai": OpenAICompatible()}
        self._backends.update(backends or {})
        self._cache: OrderedDict[bytes, tuple[int, list[Span]]] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def backends(self) -> dict[str, ModelBackend]:
        return dict(self._backends)

    def config(self) -> AiConfig:
        """The ``[ai]`` settings now. An invalid file keeps the last good ones (and logs why)."""
        stamp = self._stamp()
        if stamp != self._seen:
            with self._lock:
                if stamp != self._seen:
                    try:
                        self._config = load_config(self._path).ai
                    except ConfigError as exc:
                        log.warning("keeping the last [ai] settings: %s", exc)
                    self._seen = stamp
        return self._config

    def backend(self, config: AiConfig) -> ModelBackend:
        backend = self._backends.get(config.backend)
        if backend is None:
            names = ", ".join(sorted(self._backends))
            raise ModelError(f"no model backend named {config.backend!r}; there are {names}")
        return backend

    def models(self, config: AiConfig) -> list[ModelInfo]:
        return self.backend(config).models(config)

    def annotate(self, text: str, config: AiConfig) -> Iterator[Event]:
        """Events for annotating ``text``: ``start``, ``spans`` per piece as each finishes,
        then ``done``, or ``error`` if the model fails part way.

        The model is opened before this returns, so a server that can't be reached raises
        ``ModelError`` here rather than as an event.
        """
        labels = colored(config.annotation.labels)
        if not labels:
            raise ModelError("there are no annotation labels; add some in Settings")
        text = normalize(text)
        model = self.backend(config).open(config)
        key = _cache_key(config, model.id, text)
        header: Event = {
            "type": "start",
            "model": model.id,
            "length": len(text),
            "labels": [{"name": label.name, "color": label.color} for label in labels],
        }
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
        if cached is not None:
            return self._replay(header, *cached)
        return self._run(header, key, model, config, text)

    def close(self) -> None:
        for backend in self._backends.values():
            backend.close()

    def _replay(self, header: Event, chunks: int, spans: list[Span]) -> Iterator[Event]:
        yield {**header, "chunks": chunks, "cached": True}
        yield {"type": "spans", "chunk": 0, "spans": [_span(s) for s in spans]}
        yield {"type": "done", "spans": len(spans), "seconds": 0.0}

    def _run(
        self, header: Event, key: bytes, model: ChatModel, config: AiConfig, text: str
    ) -> Iterator[Event]:
        labels = colored(config.annotation.labels)
        chunks = split(text, config.annotation.chunk_chars)
        started = time.perf_counter()
        yield {**header, "chunks": len(chunks), "cached": False}
        found: list[Span] = []
        pool = ThreadPoolExecutor(max_workers=config.parallel, thread_name_prefix="tri-al-ai")
        try:
            pending: dict[Future[list[Span]], int] = {
                pool.submit(annotate_chunk, model, labels, chunk): chunk.index for chunk in chunks
            }
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    index = pending.pop(future)
                    try:
                        spans = future.result()
                    except ModelError as exc:
                        yield {"type": "error", "message": str(exc)}
                        return
                    found.extend(spans)
                    yield {"type": "spans", "chunk": index, "spans": [_span(s) for s in spans]}
        finally:
            # The client may leave mid-way: requests not yet sent are dropped.
            pool.shutdown(wait=False, cancel_futures=True)
        found.sort(key=lambda span: span.start)
        with self._lock:
            self._cache[key] = (len(chunks), found)
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        seconds = round(time.perf_counter() - started, 3)
        yield {"type": "done", "spans": len(found), "seconds": seconds}

    def _stamp(self) -> tuple[int, int] | None:
        try:
            stat = os.stat(self._path)
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)


def _span(span: Span) -> dict[str, Any]:
    return {"start": span.start, "end": span.end, "label": span.label}


def _cache_key(config: AiConfig, model: str, text: str) -> bytes:
    what = {
        "prompt": PROMPT_VERSION,
        "backend": config.backend,
        "server": config.server,
        "model": model,
        "annotation": config.annotation.model_dump(),
        "text": text,
    }
    return hashlib.blake2b(orjson.dumps(what, option=orjson.OPT_SORT_KEYS), digest_size=16).digest()
